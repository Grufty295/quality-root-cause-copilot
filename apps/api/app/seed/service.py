"""Orquestación del seed.

1. Catálogos y usuarios, en UNA transacción: o queda todo o no queda nada.
2. El corpus, con IngestService: un documento por transacción, y los fallos se
   reportan sin detener el resto.

El orden importa: la ingesta necesita planta y líneas, y los usuarios necesitan
las líneas para resolver su alcance.

Idempotente: correrlo de nuevo deja lo mismo (upserts, alcances reemplazados y
la ingesta salta lo que no cambió).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection

from app.ingest.service import IngestReport, IngestService
from app.modules.auth.demo_users import (
    JRZ2_EXTRA_USERS,
    OTHER_PLANT_USER,
    DemoUser,
    read_roster,
    seed_demo_users,
)
from app.retrieval.embedder import Embedder
from app.seed import repository as repo
from app.seed.sources import PLANTS, read_catalogs, read_operational

ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


@dataclass
class SeedReport:
    plants: int = 0
    customers: int = 0
    parts: int = 0
    skipped_parts: tuple[str, ...] = ()
    defect_families: int = 0
    users: int = 0
    defect_events: int | None = None
    """None = no había eventos_defecto.csv."""
    maintenance_orders: int | None = None
    removed_events: int = 0
    removed_orders: int = 0
    equipment: int | None = None
    applicator_cycles: int | None = None
    removed_equipment: int = 0
    crimp_measurements: int | None = None
    changes: int | None = None
    material_lots: int | None = None
    suppliers: int | None = None
    production: int | None = None
    ingest: IngestReport | None = None

    @property
    def ok(self) -> bool:
        return self.ingest is None or self.ingest.ok


def build_roster(estructurados: Path) -> list[DemoUser]:
    return [*read_roster(estructurados / "usuarios_demo.csv"), OTHER_PLANT_USER, *JRZ2_EXTRA_USERS]


class SeedService:
    def __init__(self, connect: ConnectionFactory, *, plant_id: str = "JRZ1") -> None:
        self._connect = connect
        self._plant_id = plant_id

    def load_structured(self, estructurados: Path) -> SeedReport:
        # Se lee y valida todo antes de abrir la transacción.
        catalogs = read_catalogs(estructurados)
        roster = build_roster(estructurados)
        plant = next((p for p in PLANTS if p.id == self._plant_id), None)
        if plant is None:
            raise ValueError(f"la planta {self._plant_id!r} no está definida")
        operational = read_operational(
            estructurados, catalogs, lines={line.id for line in plant.lines}
        )

        with self._connect() as conn:
            repo.upsert_plants(conn, PLANTS)
            repo.upsert_customers(conn, catalogs.customers)
            repo.upsert_parts(conn, catalogs.parts)
            repo.upsert_defect_families(conn, catalogs.defect_families)
            users = seed_demo_users(
                conn,
                roster,
                default_plant_id=self._plant_id,
                lines_by_plant=repo.lines_by_plant(conn),
            )
            removed_events = removed_orders = removed_equipment = 0
            # El catálogo de equipos va primero: los ciclos lo referencian.
            if operational.equipment is not None:
                removed_equipment = repo.sync_equipment(
                    conn,
                    self._plant_id,
                    operational.equipment,
                    operational.applicator_cycles,
                )
            if operational.crimp_measurements is not None:
                repo.replace_crimp_measurements(
                    conn, self._plant_id, operational.crimp_measurements
                )
            if operational.changes is not None:
                repo.replace_change_log(conn, self._plant_id, operational.changes)
            if operational.suppliers is not None:
                repo.upsert_suppliers(conn, operational.suppliers)
            if operational.production is not None:
                repo.replace_production(conn, self._plant_id, operational.production)
            if operational.material_lots is not None:
                repo.replace_material_lots(
                    conn, self._plant_id, operational.material_lots
                )
            if operational.defect_events is not None:
                removed_events = repo.sync_defect_events(
                    conn, self._plant_id, operational.defect_events
                )
            if operational.maintenance_orders is not None:
                removed_orders = repo.sync_maintenance_orders(
                    conn, self._plant_id, operational.maintenance_orders
                )
        return SeedReport(
            plants=len(PLANTS),
            customers=len(catalogs.customers),
            parts=len(catalogs.parts),
            skipped_parts=catalogs.skipped_parts,
            defect_families=len(catalogs.defect_families),
            users=users,
            defect_events=None
            if operational.defect_events is None
            else len(operational.defect_events),
            maintenance_orders=None
            if operational.maintenance_orders is None
            else len(operational.maintenance_orders),
            removed_events=removed_events,
            removed_orders=removed_orders,
            equipment=None
            if operational.equipment is None
            else len(operational.equipment),
            applicator_cycles=None
            if operational.applicator_cycles is None
            else len(operational.applicator_cycles),
            removed_equipment=removed_equipment,
            crimp_measurements=None
            if operational.crimp_measurements is None
            else len(operational.crimp_measurements),
            changes=None if operational.changes is None else len(operational.changes),
            material_lots=None
            if operational.material_lots is None
            else len(operational.material_lots),
            suppliers=None
            if operational.suppliers is None
            else len(operational.suppliers),
            production=None
            if operational.production is None
            else len(operational.production),
        )

    def run(self, data_dir: Path, *, embedder: Embedder | None) -> SeedReport:
        """`embedder=None` salta el corpus (no carga ni descarga el modelo)."""
        report = self.load_structured(data_dir / "estructurados")
        if embedder is not None:
            ingest = IngestService(self._connect, embedder, plant_id=self._plant_id)
            ingest.check_environment()
            report.ingest = ingest.ingest_directory(data_dir / "corpus")
        return report