"""Lectura y validación de eventos_defecto.csv y mantenimiento.csv (sin base de datos)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.seed.sources import PLANTS, read_catalogs, read_operational

EVENT_HEADER = (
    "evento_id,fecha_fabricacion,fecha_deteccion,turno,linea,estacion_origen,aplicador_id,maquina_corte,"
    "numero_parte,variante,cliente,defecto_codigo,defecto,cantidad,numero_parte_terminal,lote_terminal,"
    "numero_parte_cable,detectado_en\n"
)
EVENT_OK = (
    "EV-00001,2026-04-01,2026-04-01,T1,L1,BRD-L1,,,B3-FDH-0451,Base,Kestrel Modules,DEF-01,x,1,,,,INF\n"
    "EV-00002,2026-04-01,2026-04-09,T3,L2,CRP-L2,APL-L2-04,,A7-DRH-2210-M,Media,Norvane Motors,DEF-02,x,2,"
    "TRM-A-1064,LT-A-2603-01,WIR-100,CLIENTE\n"
)
ORDER_HEADER = (
    "ot_id,equipo_id,linea,tipo,fecha_programada,fecha_ejecucion,estado,motivo_reprogramacion,descripcion,"
    "ciclos_al_evento\n"
)
ORDER_OK = (
    "OT-1,APL-L1-01,L1,Preventivo,2026-03-29,2026-03-30,Completada,,PM de aplicador,185762\n"
    "OT-2,APL-L1-02,L1,Preventivo,2026-04-12,,Reprogramada,Carga de producción,PM de aplicador,\n"
)
LINES = {line.id for line in PLANTS[0].lines}


def _write(est: Path, events: str | None = None, orders: str | None = None) -> None:
    if events is not None:
        (est / "eventos_defecto.csv").write_text(
            EVENT_HEADER + events, encoding="utf-8"
        )
    if orders is not None:
        (est / "mantenimiento.csv").write_text(ORDER_HEADER + orders, encoding="utf-8")


def _read(est: Path):
    return read_operational(est, read_catalogs(est), lines=LINES)


def test_valid_rows_are_mapped(estructurados):
    _write(estructurados, EVENT_OK, ORDER_OK)
    op = _read(estructurados)
    first, second = op.defect_events
    assert (
        first.shift == 1 and first.applicator_id is None and first.terminal_lot is None
    )
    assert (second.shift, second.quantity, second.applicator_id) == (3, 2, "APL-L2-04")
    assert (
        second.made_on.isoformat() == "2026-04-01"
        and second.detected_on.isoformat() == "2026-04-09"
    )
    assert second.detection_point == "CLIENTE" and second.terminal_lot == "LT-A-2603-01"
    done, resched = op.maintenance_orders
    assert (done.status, done.order_type, done.cycles_at_event) == (
        "completada",
        "preventivo",
        185762,
    )
    assert done.completed_on.isoformat() == "2026-03-30"
    assert (resched.status, resched.completed_on, resched.reschedule_reason) == (
        "reprogramada",
        None,
        "Carga de producción",
    )


def test_missing_files_are_reported_as_none_not_as_errors(estructurados):
    op = _read(estructurados)
    assert op.defect_events is None and op.maintenance_orders is None
    _write(estructurados, EVENT_OK)
    op = _read(estructurados)
    assert len(op.defect_events) == 2 and op.maintenance_orders is None


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("2026-04-09,T3", "2026-03-30,T3", "antes de fabricarse"),
        (",T3,", ",T4,", "turno desconocido"),
        (",L2,CRP-L2", ",L9,CRP-L9", "línea desconocida"),
        (",L2,CRP-L2", ",L2,CRP-L1", "no es de la línea L2"),
        ("DEF-02", "DEF-99", "defecto desconocido"),
        ("A7-DRH-2210-M", "ZZ-0000", "número de parte desconocido"),
        ("Norvane Motors", "Kestrel Modules", "no es el de la parte"),
        (
            "Media,Norvane Motors,DEF-02,x,2",
            "Media,Norvane Motors,DEF-02,x,0",
            "greater than or equal to 1",
        ),
        ("2026-04-09", "09/04/2026", "Invalid isoformat"),
        (
            ",TRM-A-1064,LT-A-2603-01",
            ",,LT-A-2603-01",
            "lote de terminal sin número de parte",
        ),
    ],
)
def test_invalid_event_rows_are_rejected_with_a_readable_reason(
    estructurados, old, new, message
):
    _write(estructurados, EVENT_OK.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "eventos_defecto.csv" in str(err.value) and "EV-00002" in str(err.value)


def test_duplicate_event_ids_are_rejected(estructurados):
    _write(estructurados, EVENT_OK.replace("EV-00002", "EV-00001"))
    with pytest.raises(ValueError, match="repetido"):
        _read(estructurados)


def test_all_problems_are_reported_together_and_capped(estructurados):
    bad = "".join(
        f"EV-{i:05d},2026-04-01,2026-04-01,T9,L1,BRD-L1,,,B3-FDH-0451,Base,Kestrel Modules,DEF-01,x,1,,,,INF\n"
        for i in range(25)
    )
    _write(estructurados, bad)
    with pytest.raises(ValueError) as err:
        _read(estructurados)
    text = str(err.value)
    assert (
        "25 filas inválidas" in text
        and "y 15 más" in text
        and text.count("fila ") == 10
    )


def test_empty_file_is_an_error_because_the_load_would_wipe_the_table(estructurados):
    _write(estructurados, "")
    with pytest.raises(ValueError, match="no tiene filas"):
        _read(estructurados)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (",Completada,", ",Cerrada,", "estado desconocido"),
        ("Preventivo", "Predictivo", "tipo desconocido"),
        ("2026-03-30,Completada", ",Completada", "necesita fecha_ejecucion"),
        (",Reprogramada,", ",Completada,", "necesita fecha_ejecucion"),
        ("APL-L1-01", "APL L1 01", "equipo_id inválido"),
        ("185762", "-5", "greater than or equal to 0"),
        (",L1,Preventivo,2026-03-29", ",L7,Preventivo,2026-03-29", "línea desconocida"),
    ],
)
def test_invalid_order_rows_are_rejected(estructurados, old, new, message):
    _write(estructurados, orders=ORDER_OK.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "mantenimiento.csv" in str(err.value)


def test_duplicate_order_ids_are_rejected(estructurados):
    _write(estructurados, orders=ORDER_OK.replace("OT-2", "OT-1"))
    with pytest.raises(ValueError, match="repetido"):
        _read(estructurados)


def test_missing_column_is_named(estructurados):
    (estructurados / "mantenimiento.csv").write_text(
        "ot_id,equipo_id\nOT-1,APL-L1-01\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="faltan columnas"):
        _read(estructurados)
