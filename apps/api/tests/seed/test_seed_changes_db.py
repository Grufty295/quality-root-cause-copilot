"""cambios.csv y lotes_material.csv contra Postgres real."""

from __future__ import annotations

import csv
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.seed.service import SeedService
from tests.paths import STRUCTURED_DIR
from tests.seed.test_seed_changes import (
    CHANGE_OK,
    LOT_OK,
    PRODUCTION_OK,
    SUPPLIER_OK,
    _changes,
    _lots,
    _production,
    _suppliers,
)


@pytest.fixture
def service(db_conn):
    @contextmanager
    def connect():
        with db_conn.begin_nested():
            yield db_conn

    return SeedService(connect, plant_id="JRZ1")


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_changes_and_lots_are_loaded_replaced_and_idempotent(
    service, db_conn, estructurados
):
    _changes(estructurados)
    _lots(estructurados, catalog=False)
    report = service.load_structured(estructurados)
    assert (report.changes, report.material_lots) == (3, 2)
    row = db_conn.execute(
        text(
            "SELECT equipment_ids, line_ids, previous_revision, board_updated FROM change_log WHERE id = 'CHG-3'"
        )
    ).one()
    assert tuple(row) == (["PRS-L1-01", "PRS-L2-02"], ["L1", "L2"], "H", "No")
    service.load_structured(estructurados)
    assert (_count(db_conn, "change_log"), _count(db_conn, "material_lot")) == (3, 2)
    _changes(estructurados, CHANGE_OK.splitlines(keepends=True)[0], catalog=False)
    _lots(estructurados, LOT_OK.splitlines(keepends=True)[0], catalog=False)
    service.load_structured(estructurados)
    assert (_count(db_conn, "change_log"), _count(db_conn, "material_lot")) == (1, 1)


def test_an_invalid_file_changes_nothing(service, db_conn, estructurados):
    _changes(estructurados)
    service.load_structured(estructurados)
    _changes(estructurados, CHANGE_OK.replace("ECN,", "Ajuste,", 1))
    with pytest.raises(ValueError, match="tipo desconocido"):
        service.load_structured(estructurados)
    assert _count(db_conn, "change_log") == 3


def test_other_plants_are_untouched(service, db_conn, estructurados):
    _changes(estructurados)
    service.load_structured(estructurados)  # crea las plantas
    db_conn.execute(
        text(
            "INSERT INTO change_log (plant_id, id, changed_on, kind, line_ids, description, approved_by_role) "
            "VALUES ('JRZ2', 'CHG-1', '2026-01-01', 'ECN', ARRAY['L1'], 'x', 'y')"
        )
    )
    service.load_structured(estructurados)
    assert (
        db_conn.execute(
            text("SELECT count(*) FROM change_log WHERE plant_id = 'JRZ2'")
        ).scalar_one()
        == 1
    )


def test_the_database_enforces_its_constraints(service, db_conn, estructurados):
    _changes(estructurados)
    _lots(estructurados)
    service.load_structured(estructurados)
    change = (
        "INSERT INTO change_log (plant_id, id, changed_on, kind, line_ids, previous_revision, new_revision, "
        "description, approved_by_role) VALUES ('JRZ1', 'CHG-X', '2026-05-01', 'ECN', :lines, :prev, :new, 'd', 'r')"
    )
    for params, match in (
        ({"lines": [], "prev": None, "new": None}, "line_ids_check"),
        ({"lines": ["L1"], "prev": "A", "new": None}, "check"),
    ):
        with pytest.raises(IntegrityError, match=match), db_conn.begin_nested():
            db_conn.execute(text(change), params)
    lot = (
        "INSERT INTO material_lot (plant_id, id, part_number, family, supplier_id, received_on, "
        "quantity, inspection_type, inspection_result, consumed_from, consumed_to, status) "
        "VALUES ('JRZ1', :id, 'TRM-A-1064', 'A', :sup, :recv, :qty, 't', 'r', '2026-05-02', '2026-05-03', 's')"
    )
    base = {"id": "LT-X", "recv": "2026-05-01", "qty": 10, "sup": "PRV-01"}
    for override, match in (
        ({"id": "LT-A-2603-01"}, "pkey|unique"),
        ({"qty": 0}, "quantity_check"),
        ({"sup": "PRV-99"}, "supplier_id_fkey"),
        ({"recv": "2026-05-09"}, "check"),
    ):
        with pytest.raises(IntegrityError, match=match), db_conn.begin_nested():
            db_conn.execute(text(lot), base | override)


REAL = STRUCTURED_DIR


@pytest.mark.skipif(
    not (REAL / "lotes_material.csv").exists(), reason="no está el dataset real"
)
def test_real_dataset_totals_match_the_csv(service, db_conn):
    service.load_structured(REAL)
    for table, filename in (
        ("supplier", "catalogo_proveedores.csv"),
        ("production", "produccion.csv"),
        ("change_log", "cambios.csv"),
        ("material_lot", "lotes_material.csv"),
    ):
        with (REAL / filename).open(encoding="utf-8-sig", newline="") as fh:
            assert _count(db_conn, table) == len(list(csv.DictReader(fh)))
    assert (
        db_conn.execute(
            text(
                "SELECT sum(quantity) FROM material_lot WHERE part_number = 'TRM-A-1064'"
            )
        ).scalar_one()
        == 2_800_000
    )


def test_suppliers_are_upserted_and_lots_reference_them(
    service, db_conn, estructurados
):
    _lots(estructurados, catalog=False)
    report = service.load_structured(estructurados)
    assert report.suppliers == 2
    got = db_conn.execute(
        text("SELECT name, supplies FROM supplier WHERE id = 'PRV-01'")
    ).one()
    assert tuple(got) == ("Vértice Conectores", ["TRM-A-1064", "TRM-B-2150"])
    # Cambiar el catálogo actualiza; los lotes siguen apuntando al mismo id.
    _suppliers(estructurados, SUPPLIER_OK.replace("Vértice Conectores", "Vértice SA"))
    (estructurados / "lotes_material.csv").write_text(
        (estructurados / "lotes_material.csv")
        .read_text(encoding="utf-8")
        .replace("Vértice Conectores", "Vértice SA"),
        encoding="utf-8",
    )
    service.load_structured(estructurados)
    assert (
        db_conn.execute(
            text(
                "SELECT s.name FROM material_lot m JOIN supplier s ON s.id = m.supplier_id WHERE m.id = 'LT-A-2603-01'"
            )
        ).scalar_one()
        == "Vértice SA"
    )


def test_production_is_loaded_replaced_and_idempotent(service, db_conn, estructurados):
    _production(estructurados)
    report = service.load_structured(estructurados)
    assert report.production == 2
    assert _count(db_conn, "production") == 2
    service.load_structured(estructurados)
    assert _count(db_conn, "production") == 2
    _production(estructurados, PRODUCTION_OK.splitlines(keepends=True)[0])
    service.load_structured(estructurados)
    assert _count(db_conn, "production") == 1
    with pytest.raises(IntegrityError, match="units_check"), db_conn.begin_nested():
        db_conn.execute(
            text(
                "INSERT INTO production (plant_id, produced_on, shift, line_id, part_id, units) "
                "VALUES ('JRZ1', '2026-05-01', 1, 'L1', 'B3-FDH-0451', 0)"
            )
        )
