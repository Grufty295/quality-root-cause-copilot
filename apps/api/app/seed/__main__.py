"""Seed de la demo: catálogos, usuarios y corpus.

    python -m app.seed                    # datos en /workspace/data/seed, planta JRZ1
    python -m app.seed --skip-corpus      # sin indexar: no carga ni descarga el modelo de embeddings
    python -m app.seed --dry-run          # solo lee y valida los CSV; no toca la base

Carga plantas y líneas, clientes, números de parte de cliente, familias de
defecto, los equipos con sus ciclos y mediciones de crimpado, los eventos de defecto y las órdenes de mantenimiento (si están los CSV;
el CSV es la fuente de verdad: lo que ya no esté se borra de esa planta), los usuarios de usuarios_demo.csv (más uno de otra planta para la demo
de aislamiento) y el corpus. Es idempotente.

Los CSV y el corpus los escribe data/generator/generate.py. Este comando no
los regenera: el generador borra data/seed y evals/ completos antes de escribir.

Sale con código 1 si algún documento del corpus falló y con 2 si los datos de
entrada son inválidos.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DATA = Path("/workspace/data/seed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="carpeta con estructurados/ y corpus/",
    )
    parser.add_argument(
        "--plant", default="JRZ1", help="planta de los usuarios y del corpus"
    )
    parser.add_argument(
        "--skip-corpus", action="store_true", help="no indexa el corpus"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="valida los CSV sin tocar la base"
    )
    args = parser.parse_args(argv)

    if "evals" in args.data.resolve().parts:
        print(
            "Se rechaza evals/ como fuente: los casos de evaluación no se cargan.",
            file=sys.stderr,
        )
        return 2

    from pydantic import ValidationError

    from app.ingest.service import IngestError

    try:
        if args.dry_run:
            return _dry_run(args.data, args.plant)
        return _run(args.data, args.plant, skip_corpus=args.skip_corpus)
    except (ValueError, ValidationError, OSError, IngestError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(data: Path, plant: str, *, skip_corpus: bool) -> int:
    from app.core.db import get_engine
    from app.retrieval.embedder import get_embedder
    from app.seed.service import SeedService

    service = SeedService(get_engine().begin, plant_id=plant)
    report = service.run(data, embedder=None if skip_corpus else get_embedder())

    print(
        f"plantas {report.plants} · clientes {report.customers} · partes {report.parts} · "
        f"familias de defecto {report.defect_families} · usuarios {report.users}"
    )
    _print_operational(
        report.defect_events,
        report.maintenance_orders,
        report.removed_events,
        report.removed_orders,
        equipment=report.equipment,
        cycles=report.applicator_cycles,
        removed_equipment=report.removed_equipment,
        crimp=report.crimp_measurements,
        changes=report.changes,
        lots=report.material_lots,
        suppliers=report.suppliers,
        production=report.production,
    )
    if report.skipped_parts:
        print(
            f"  sin cliente, no se cargan como parte: {', '.join(report.skipped_parts)}"
        )
    if report.ingest is None:
        print("corpus: omitido (--skip-corpus)")
        return 0
    ing = report.ingest
    print(
        f"corpus: creados {len(ing.created)} · actualizados {len(ing.updated)} · "
        f"sin cambios {len(ing.unchanged)} · fallidos {len(ing.failed)} · fragmentos {ing.fragments}"
    )
    for name, msg in ing.warnings:
        print(f"  aviso  {name}: {msg}")
    for name, msg in ing.failed:
        print(f"  fallo  {name}: {msg}", file=sys.stderr)
    return 0 if report.ok else 1


def _print_operational(
    events: int | None,
    orders: int | None,
    removed_events: int,
    removed_orders: int,
    *,
    equipment: int | None = None,
    cycles: int | None = None,
    removed_equipment: int = 0,
    crimp: int | None = None,
    changes: int | None = None,
    lots: int | None = None,
    suppliers: int | None = None,
    production: int | None = None,
) -> None:
    def line(label: str, count: int | None, removed: int, filename: str) -> str:
        if count is None:
            return f"{label}: omitido (no hay {filename})"
        extra = f" · obsoletos borrados {removed}" if removed else ""
        return f"{label}: {count}{extra}"

    print(line("equipos", equipment, removed_equipment, "catalogo_equipos.csv"))
    print(line("ciclos de aplicador (días)", cycles, 0, "ciclos_aplicador.csv"))
    print(line("mediciones de crimpado", crimp, 0, "mediciones_crimpado.csv"))
    print(line("bitácora de cambios", changes, 0, "cambios.csv"))
    print(line("proveedores", suppliers, 0, "catalogo_proveedores.csv"))
    print(line("producción (turno · línea · parte)", production, 0, "produccion.csv"))
    print(line("lotes de material", lots, 0, "lotes_material.csv"))
    print(line("eventos de defecto", events, removed_events, "eventos_defecto.csv"))
    print(line("órdenes de mantenimiento", orders, removed_orders, "mantenimiento.csv"))


def _dry_run(data: Path, plant: str) -> int:
    from app.modules.auth.demo_users import scopes_for
    from app.seed.service import build_roster
    from app.seed.sources import PLANTS, read_catalogs, read_operational

    estructurados = data / "estructurados"
    catalogs = read_catalogs(estructurados)
    plant_def = next((p for p in PLANTS if p.id == plant), None)
    if plant_def is None:
        raise ValueError(f"la planta {plant!r} no está definida")
    operational = read_operational(
        estructurados, catalogs, lines={line.id for line in plant_def.lines}
    )
    roster = build_roster(estructurados)
    lines = {p.id: {line.id for line in p.lines} for p in PLANTS}
    for user in roster:
        plant_id = user.plant_id or plant
        if plant_id not in lines:
            raise ValueError(f"{user.username}: la planta {plant_id!r} no existe")
        scopes = scopes_for(user, plant_id=plant_id, plant_lines=lines[plant_id])
        shown = ", ".join(f"{p}/{line or '*'}" for p, line in scopes)
        print(f"  {user.username:<16} {user.role:<10} {shown}")
    print(
        f"clientes {len(catalogs.customers)} · partes {len(catalogs.parts)} "
        f"(sin cliente: {len(catalogs.skipped_parts)}) · familias de defecto {len(catalogs.defect_families)} · "
        f"usuarios {len(roster)}"
    )
    _print_operational(
        None if operational.defect_events is None else len(operational.defect_events),
        None
        if operational.maintenance_orders is None
        else len(operational.maintenance_orders),
        0,
        0,
        equipment=None if operational.equipment is None else len(operational.equipment),
        cycles=None
        if operational.applicator_cycles is None
        else len(operational.applicator_cycles),
        crimp=None
        if operational.crimp_measurements is None
        else len(operational.crimp_measurements),
        changes=None if operational.changes is None else len(operational.changes),
        lots=None
        if operational.material_lots is None
        else len(operational.material_lots),
        suppliers=None if operational.suppliers is None else len(operational.suppliers),
        production=None
        if operational.production is None
        else len(operational.production),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
