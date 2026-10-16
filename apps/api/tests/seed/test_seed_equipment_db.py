"""Equipos y ciclos contra Postgres real, y la regla de ciclos contra el dataset real."""

from __future__ import annotations

import csv
import re
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.agent.tools import QualityTools, ToolBudget
from app.modules.auth import repository as auth_repo
from app.retrieval.service import RetrievalService
from app.seed.service import SeedService
from tests.paths import STRUCTURED_DIR
from tests.retrieval.fakes import HashingEmbedder
from tests.seed.test_seed_equipment import EQUIPMENT_OK, _equipment


@pytest.fixture
def service(db_conn):
    @contextmanager
    def connect():
        with db_conn.begin_nested():
            yield db_conn

    return SeedService(connect, plant_id="JRZ1")


def _counts(conn):
    return conn.execute(
        text(
            "SELECT (SELECT count(*) FROM equipment), (SELECT count(*) FROM applicator_cycles)"
        )
    ).one()


def test_equipment_and_cycles_are_loaded_and_reloading_changes_nothing(
    service, db_conn, estructurados
):
    _equipment(estructurados)
    report = service.load_structured(estructurados)
    assert (report.equipment, report.applicator_cycles) == (5, 3)
    assert tuple(_counts(db_conn)) == (5, 3)
    row = db_conn.execute(
        text(
            "SELECT kind, terminal_family, housed_in, pm_threshold_cycles FROM equipment WHERE id = 'APL-L1-01'"
        )
    ).one()
    assert tuple(row) == ("Aplicador", "A", "PRS-L1-01", 250000)
    again = service.load_structured(estructurados)
    assert tuple(_counts(db_conn)) == (5, 3) and again.removed_equipment == 0


def test_the_csv_replaces_cycles_and_removes_obsolete_equipment_with_their_cycles(
    service, db_conn, estructurados
):
    _equipment(estructurados)
    service.load_structured(estructurados)
    only_l1 = (
        "\n".join(line for line in EQUIPMENT_OK.splitlines() if "L2" not in line) + "\n"
    )
    new_cycles = "fecha,aplicador_id,ciclos\n2026-04-01,APL-L1-01,99\n"
    _equipment(estructurados, only_l1, new_cycles)
    report = service.load_structured(estructurados)
    assert report.removed_equipment == 3  # APL-L2-04, PRS-L2-02 y CUT-L2-01
    assert db_conn.execute(
        text("SELECT id FROM equipment ORDER BY id")
    ).scalars().all() == ["APL-L1-01", "PRS-L1-01"]
    assert db_conn.execute(
        text("SELECT cycles FROM applicator_cycles")
    ).scalars().all() == [99]


def test_other_plants_are_untouched(service, db_conn, estructurados):
    db_conn.execute(
        text(
            "INSERT INTO equipment (plant_id, id, line_id, kind, pm_threshold_cycles) "
            "VALUES ('JRZ2', 'APL-L1-01', 'L1', 'Aplicador', 100000)"
        )
    )
    _equipment(estructurados)
    service.load_structured(estructurados)
    assert (
        db_conn.execute(
            text("SELECT pm_threshold_cycles FROM equipment WHERE plant_id = 'JRZ2'")
        ).scalar_one()
        == 100000
    )


def test_the_database_enforces_the_equipment_foreign_key(
    service, db_conn, estructurados
):
    _equipment(estructurados)
    service.load_structured(estructurados)
    with pytest.raises(IntegrityError), db_conn.begin_nested():
        db_conn.execute(
            text(
                "INSERT INTO applicator_cycles (plant_id, equipment_id, day, cycles) VALUES ('JRZ1', 'APL-X', '2026-04-01', 1)"
            )
        )
    with pytest.raises(IntegrityError, match="cycles_check"), db_conn.begin_nested():
        db_conn.execute(
            text(
                "INSERT INTO applicator_cycles (plant_id, equipment_id, day, cycles) VALUES ('JRZ1', 'APL-L1-01', '2026-05-01', -1)"
            )
        )


REAL = STRUCTURED_DIR


@pytest.mark.skipif(
    not (REAL / "ciclos_aplicador.csv").exists(), reason="no está el dataset real"
)
def test_cycles_since_service_reproduce_every_recorded_cycles_at_event(
    service, db_conn
):
    """La regla de la tool coincide con los 71 `ciclos_al_evento` del dataset real.

    Un día antes del servicio, más los ciclos de ese día, es lo que registró la planta
    (en el correctivo OT-2026-0020 el día del servicio no cuenta: ahí basta el día anterior).
    """
    service.load_structured(REAL)
    user = auth_repo.get_user(
        db_conn, auth_repo.find_active_user_id(db_conn, "u-ingcal-1")
    )
    tools = QualityTools(
        db_conn,
        user,
        RetrievalService(db_conn, HashingEmbedder()),
        ToolBudget(1000),
        today=date(2026, 10, 15),
    )
    with (REAL / "mantenimiento.csv").open(encoding="utf-8-sig", newline="") as fh:
        orders = [
            o
            for o in csv.DictReader(fh)
            if o["estado"] == "Completada"
            and o["equipo_id"].startswith("APL")
            and o["ciclos_al_evento"]
        ]
    assert len(orders) == 71
    for o in orders:
        day = date.fromisoformat(o["fecha_ejecucion"])
        out = tools.applicator_wear(
            "JRZ1", o["linea"], equipment=o["equipo_id"], on=day - timedelta(days=1)
        ).text
        before = int(re.search(r": ([\d,]+) ciclos", out).group(1).replace(",", ""))
        same_day = db_conn.execute(
            text(
                "SELECT coalesce(sum(cycles), 0) FROM applicator_cycles WHERE equipment_id = :e AND day = :d"
            ),
            {"e": o["equipo_id"], "d": day},
        ).scalar_one()
        assert int(o["ciclos_al_evento"]) in (before + same_day, before), o["ot_id"]
    total = db_conn.execute(
        text("SELECT sum(cycles) FROM applicator_cycles")
    ).scalar_one()
    with (REAL / "ciclos_aplicador.csv").open(encoding="utf-8-sig", newline="") as fh:
        assert total == sum(int(r["ciclos"]) for r in csv.DictReader(fh))
