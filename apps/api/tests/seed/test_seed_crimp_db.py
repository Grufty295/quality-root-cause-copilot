"""mediciones_crimpado.csv contra Postgres real: carga, reemplazo, restricciones y dataset real."""

from __future__ import annotations

import csv
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.seed.service import SeedService
from tests.paths import STRUCTURED_DIR
from tests.seed.test_seed_crimp import CRIMP_HEADER, CRIMP_OK, _crimp
from tests.seed.test_seed_equipment import EQUIPMENT_HEADER, EQUIPMENT_OK


@pytest.fixture
def service(db_conn):
    @contextmanager
    def connect():
        with db_conn.begin_nested():
            yield db_conn

    return SeedService(connect, plant_id="JRZ1")


def _count(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM crimp_measurement")).scalar_one()


def test_measurements_are_loaded_with_generated_flags_and_reloading_changes_nothing(
    service, db_conn, estructurados
):
    _crimp(estructurados)
    report = service.load_structured(estructurados)
    assert report.crimp_measurements == 3 and _count(db_conn) == 3
    flags = db_conn.execute(
        text(
            "SELECT shift, height_ok, pull_ok FROM crimp_measurement "
            "WHERE equipment_id = 'APL-L1-01' ORDER BY shift"
        )
    ).all()
    assert [tuple(f) for f in flags] == [(1, True, True), (2, False, False)]
    service.load_structured(estructurados)
    assert _count(db_conn) == 3


def test_the_csv_replaces_the_measurements(service, db_conn, estructurados):
    _crimp(estructurados)
    service.load_structured(estructurados)
    _crimp(estructurados, CRIMP_OK.splitlines(keepends=True)[0])
    service.load_structured(estructurados)
    assert _count(db_conn) == 1


def test_an_invalid_file_changes_nothing(service, db_conn, estructurados):
    _crimp(estructurados)
    service.load_structured(estructurados)
    _crimp(estructurados, CRIMP_OK.replace("T1,L1", "T9,L1", 1))
    with pytest.raises(ValueError, match="turno desconocido"):
        service.load_structured(estructurados)
    assert _count(db_conn) == 3


def test_removing_equipment_removes_its_measurements(service, db_conn, estructurados):
    _crimp(estructurados)
    service.load_structured(estructurados)
    only_l2 = "\n".join(line for line in EQUIPMENT_OK.splitlines() if "L1" not in line)
    # catálogo sin L1 y mediciones solo de L2: las de L1 desaparecen con sus equipos
    (estructurados / "catalogo_equipos.csv").write_text(
        EQUIPMENT_HEADER + only_l2 + "\n", encoding="utf-8"
    )
    (estructurados / "mediciones_crimpado.csv").write_text(
        CRIMP_HEADER + CRIMP_OK.splitlines(keepends=True)[2], encoding="utf-8"
    )
    report = service.load_structured(estructurados)
    assert report.removed_equipment == 2 and _count(db_conn) == 1


def test_the_database_enforces_its_constraints(service, db_conn, estructurados):
    _crimp(estructurados)
    service.load_structured(estructurados)
    insert = (
        "INSERT INTO crimp_measurement (plant_id, equipment_id, measured_on, shift, terminal_part_number, "
        "cable_part_number, line_id, press_id, height_mm, height_lsl, height_usl, pull_n, pull_min_n) "
        "VALUES ('JRZ1', :eq, '2026-05-01', :shift, 'TRM-A-1064', 'WIR-035', 'L1', 'PRS-L1-01', "
        "0.8, :lsl, :usl, 60, 50)"
    )
    base = {"eq": "APL-L1-01", "shift": 1, "lsl": 0.77, "usl": 0.83}
    for override, match in (
        ({"eq": "APL-X"}, "foreign key"),
        ({"shift": 4}, "shift_check"),
        ({"lsl": 0.9, "usl": 0.8}, "check"),
    ):
        with pytest.raises(IntegrityError, match=match), db_conn.begin_nested():
            db_conn.execute(text(insert), base | override)
    with db_conn.begin_nested():
        db_conn.execute(text(insert), base)
    with pytest.raises(IntegrityError, match="pkey|unique"), db_conn.begin_nested():
        db_conn.execute(text(insert), base)


REAL = STRUCTURED_DIR


@pytest.mark.skipif(
    not (REAL / "mediciones_crimpado.csv").exists(), reason="no está el dataset real"
)
def test_real_dataset_totals_match_the_csv(service, db_conn):
    service.load_structured(REAL)
    with (REAL / "mediciones_crimpado.csv").open(
        encoding="utf-8-sig", newline=""
    ) as fh:
        rows = list(csv.DictReader(fh))
    got = db_conn.execute(
        text(
            "SELECT count(*), count(*) FILTER (WHERE NOT height_ok), "
            "count(*) FILTER (WHERE NOT pull_ok) FROM crimp_measurement"
        )
    ).one()
    assert tuple(got) == (
        len(rows),
        sum(r["resultado_altura"] == "NOK" for r in rows),
        sum(r["resultado_traccion"] == "NOK" for r in rows),
    )
