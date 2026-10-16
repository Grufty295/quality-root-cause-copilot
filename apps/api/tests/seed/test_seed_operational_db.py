"""Carga de eventos y órdenes contra Postgres real: mapeo, idempotencia y sincronización."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.seed.service import SeedService
from tests.paths import STRUCTURED_DIR
from tests.seed.test_seed_operational import EVENT_OK, ORDER_OK, _write


@pytest.fixture
def service(db_conn):
    @contextmanager
    def connect():
        with db_conn.begin_nested():
            yield db_conn

    return SeedService(connect, plant_id="JRZ1")


def _events(conn):
    return conn.execute(
        text(
            "SELECT source_id, occurred_at AT TIME ZONE 'UTC', detected_on, plant_id, line_id, shift, part_id, "
            "defect_family_id, station, quantity, detection_point, applicator_id, terminal_lot "
            "FROM defect_event WHERE source_id IS NOT NULL ORDER BY source_id"
        )
    ).all()


def test_events_and_orders_are_loaded_with_every_field(service, db_conn, estructurados):
    _write(estructurados, EVENT_OK, ORDER_OK)
    report = service.load_structured(estructurados)
    assert (report.defect_events, report.maintenance_orders) == (2, 2)
    first, second = _events(db_conn)
    assert first[:4] == ("EV-00001", first[1], first[2], "JRZ1")
    assert second[0] == "EV-00002"
    assert (second[1].isoformat(), second[2].isoformat()) == (
        "2026-04-01T00:00:00",
        "2026-04-09",
    )
    assert second[4:] == (
        "L2",
        3,
        "A7-DRH-2210-M",
        "DEF-02",
        "CRP-L2",
        2,
        "CLIENTE",
        "APL-L2-04",
        "LT-A-2603-01",
    )
    orders = db_conn.execute(
        text(
            "SELECT id, order_type, due_date, completed_at AT TIME ZONE 'UTC', status, reschedule_reason, cycles_at_event "
            "FROM maintenance_order ORDER BY id"
        )
    ).all()
    assert (
        orders[0][1:3] == ("preventivo", orders[0][2]) and orders[0][4] == "completada"
    )
    assert orders[0][3].isoformat() == "2026-03-30T00:00:00" and orders[0][6] == 185762
    assert (orders[1][3], orders[1][4], orders[1][5], orders[1][6]) == (
        None,
        "reprogramada",
        "Carga de producción",
        None,
    )


def test_loading_twice_changes_nothing(service, db_conn, estructurados):
    _write(estructurados, EVENT_OK, ORDER_OK)
    service.load_structured(estructurados)
    before = _events(db_conn)
    report = service.load_structured(estructurados)
    assert _events(db_conn) == before
    assert report.removed_events == report.removed_orders == 0
    assert (
        db_conn.execute(text("SELECT count(*) FROM maintenance_order")).scalar_one()
        == 2
    )


def test_the_csv_is_the_source_of_truth_for_its_plant(service, db_conn, estructurados):
    _write(estructurados, EVENT_OK, ORDER_OK)
    service.load_structured(estructurados)
    # Una fila capturada a mano y una de otra planta no deben tocarse.
    db_conn.execute(
        text(
            "INSERT INTO defect_event (occurred_at, detected_on, plant_id, line_id, shift, defect_family_id, quantity) "
            "VALUES ('2026-04-02', '2026-04-02', 'JRZ1', 'L1', 1, 'DEF-01', 1)"
        )
    )
    db_conn.execute(
        text(
            "INSERT INTO defect_event (source_id, occurred_at, detected_on, plant_id, line_id, shift, defect_family_id, quantity) "
            "VALUES ('EV-OTRA', '2026-04-02', '2026-04-02', 'JRZ2', 'L1', 1, 'DEF-01', 1)"
        )
    )
    # Segunda versión del CSV: cambia el evento 2, desaparece el 1, desaparece la OT-2.
    changed = EVENT_OK.splitlines(keepends=True)[1].replace(",2,TRM", ",3,TRM")
    _write(estructurados, changed, ORDER_OK.splitlines(keepends=True)[0])
    report = service.load_structured(estructurados)
    assert (report.removed_events, report.removed_orders) == (1, 1)
    rows = _events(db_conn)
    assert [r[0] for r in rows if r[3] == "JRZ1"] == ["EV-00002"]
    assert [r[9] for r in rows if r[0] == "EV-00002"] == [3]
    assert (
        db_conn.execute(
            text("SELECT count(*) FROM defect_event WHERE source_id IS NULL")
        ).scalar_one()
        == 1
    )
    assert (
        db_conn.execute(
            text("SELECT count(*) FROM defect_event WHERE source_id = 'EV-OTRA'")
        ).scalar_one()
        == 1
    )
    assert db_conn.execute(
        text("SELECT id FROM maintenance_order")
    ).scalars().all() == ["OT-1"]


def test_an_invalid_csv_writes_nothing_at_all(service, db_conn, estructurados):
    count = "SELECT (SELECT count(*) FROM maintenance_order) + (SELECT count(*) FROM defect_event) + (SELECT count(*) FROM app_user)"
    before = db_conn.execute(text(count)).scalar_one()
    _write(estructurados, EVENT_OK.replace("DEF-02", "DEF-99"), ORDER_OK)
    with pytest.raises(ValueError, match="defecto desconocido"):
        service.load_structured(estructurados)
    assert db_conn.execute(text(count)).scalar_one() == before


def test_a_failure_halfway_through_rolls_back_everything(
    service, db_conn, estructurados, monkeypatch
):
    from app.seed import repository

    count = "SELECT (SELECT count(*) FROM maintenance_order) + (SELECT count(*) FROM defect_event) + (SELECT count(*) FROM app_user)"
    before = db_conn.execute(text(count)).scalar_one()
    _write(estructurados, EVENT_OK, ORDER_OK)

    def boom(*_args, **_kwargs):
        raise RuntimeError("se cayó a la mitad")

    monkeypatch.setattr(repository, "sync_maintenance_orders", boom)
    with pytest.raises(RuntimeError):
        service.load_structured(
            estructurados
        )  # los eventos ya estaban escritos en la transacción
    assert db_conn.execute(text(count)).scalar_one() == before


def test_without_the_csvs_existing_rows_are_left_alone(service, db_conn, estructurados):
    _write(estructurados, EVENT_OK, ORDER_OK)
    service.load_structured(estructurados)
    (estructurados / "eventos_defecto.csv").unlink()
    (estructurados / "mantenimiento.csv").unlink()
    report = service.load_structured(estructurados)
    assert report.defect_events is None and report.maintenance_orders is None
    assert len(_events(db_conn)) == 2


def test_database_rejects_incoherent_rows_even_if_the_loader_is_bypassed(
    service, db_conn, estructurados
):
    _write(estructurados, EVENT_OK, ORDER_OK)
    service.load_structured(estructurados)

    def insert_event(made, detected):
        with db_conn.begin_nested():
            db_conn.execute(
                text(
                    "INSERT INTO defect_event (occurred_at, detected_on, plant_id, line_id, shift, defect_family_id) "
                    "VALUES (:m, :d, 'JRZ1', 'L1', 1, 'DEF-01')"
                ),
                {"m": made, "d": detected},
            )

    with pytest.raises(IntegrityError, match="detected_after_made"):
        insert_event("2026-04-10", "2026-04-09")

    def insert_order(status, completed):
        with db_conn.begin_nested():
            db_conn.execute(
                text(
                    "INSERT INTO maintenance_order (id, plant_id, line_id, equipment, order_type, status, completed_at) "
                    "VALUES ('OT-X', 'JRZ1', 'L1', 'APL-L1-01', 'preventivo', :s, :c)"
                ),
                {"s": status, "c": completed},
            )

    with pytest.raises(IntegrityError, match="done_ck"):
        insert_order("completada", None)
    with pytest.raises(IntegrityError, match="done_ck"):
        insert_order("pendiente", "2026-04-10")
    with pytest.raises(IntegrityError, match="status_ck"):
        insert_order("cerrada", None)


REAL = STRUCTURED_DIR


@pytest.mark.skipif(
    not (REAL / "eventos_defecto.csv").exists(), reason="no está el dataset real"
)
def test_real_dataset_loads_and_matches_independent_totals(service, db_conn):
    import csv

    report = service.load_structured(REAL)
    with (REAL / "eventos_defecto.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with (REAL / "mantenimiento.csv").open(encoding="utf-8-sig", newline="") as fh:
        orders = list(csv.DictReader(fh))
    assert report.defect_events == len(rows) and report.maintenance_orders == len(
        orders
    )
    assert db_conn.execute(
        text("SELECT sum(quantity) FROM defect_event WHERE source_id IS NOT NULL")
    ).scalar_one() == sum(int(r["cantidad"]) for r in rows)
    by_line = dict(
        db_conn.execute(
            text("SELECT line_id, sum(quantity)::int FROM defect_event GROUP BY 1")
        ).all()
    )
    for line in ("L1", "L2"):
        assert by_line[line] == sum(
            int(r["cantidad"]) for r in rows if r["linea"] == line
        )
    assert db_conn.execute(
        text("SELECT count(*) FROM defect_event WHERE applicator_id IS NOT NULL")
    ).scalar_one() == sum(1 for r in rows if r["aplicador_id"])
    # Lo que se detecta tarde tiene que seguir detectándose tarde.
    assert db_conn.execute(
        text(
            "SELECT count(*) FROM defect_event WHERE detected_on > (occurred_at AT TIME ZONE 'UTC')::date"
        )
    ).scalar_one() == sum(
        1 for r in rows if r["fecha_deteccion"] != r["fecha_fabricacion"]
    )
    states = dict(
        db_conn.execute(
            text("SELECT status, count(*)::int FROM maintenance_order GROUP BY 1")
        ).all()
    )
    expected: dict[str, int] = {}
    for o in orders:
        expected[o["estado"].lower()] = expected.get(o["estado"].lower(), 0) + 1
    assert states == expected
    assert db_conn.execute(
        text("SELECT sum(cycles_at_event) FROM maintenance_order")
    ).scalar_one() == sum(
        int(o["ciclos_al_evento"]) for o in orders if o["ciclos_al_evento"]
    )
    assert service.load_structured(REAL).removed_events == 0  # idempotente
