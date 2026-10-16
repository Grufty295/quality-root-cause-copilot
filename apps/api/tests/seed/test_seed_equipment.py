"""Catálogo de equipos y ciclos diarios: lectura y validación cruzada (sin base de datos)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.seed.sources import PLANTS, read_catalogs, read_operational
from tests.seed.test_seed_operational import EVENT_OK, ORDER_OK, _write

EQUIPMENT_HEADER = "equipo_id,tipo,linea,familia_terminal,numero_parte_terminal,aloja_en,umbral_pm_ciclos\n"
EQUIPMENT_OK = (
    "APL-L1-01,Aplicador,L1,A,TRM-A-1064,PRS-L1-01,250000\n"
    "APL-L2-04,Aplicador,L2,B,TRM-B-2150,PRS-L2-02,250000\n"
    "PRS-L1-01,Prensa de crimpado,L1,,,,\n"
    "PRS-L2-02,Prensa de crimpado,L2,,,,\n"
    "CUT-L2-01,Máquina de corte y desforre,L2,,,,\n"
)
CYCLES = "fecha,aplicador_id,ciclos\n2026-04-01,APL-L1-01,18666\n2026-04-02,APL-L1-01,0\n2026-04-01,APL-L2-04,4622\n"
LINES = {line.id for line in PLANTS[0].lines}


def _equipment(
    est: Path, body: str = EQUIPMENT_OK, cycles: str | None = CYCLES
) -> None:
    (est / "catalogo_equipos.csv").write_text(EQUIPMENT_HEADER + body, encoding="utf-8")
    if cycles is not None:
        (est / "ciclos_aplicador.csv").write_text(cycles, encoding="utf-8")


def _read(est: Path):
    return read_operational(est, read_catalogs(est), lines=LINES)


def test_equipment_and_cycles_are_mapped(estructurados):
    _equipment(estructurados)
    op = _read(estructurados)
    by_id = {e.id: e for e in op.equipment}
    apl = by_id["APL-L1-01"]
    assert (
        apl.is_applicator
        and apl.pm_threshold_cycles == 250000
        and apl.housed_in == "PRS-L1-01"
    )
    press = by_id["PRS-L1-01"]
    assert (
        not press.is_applicator
        and press.pm_threshold_cycles is None
        and press.terminal_family is None
    )
    assert [
        (c.equipment_id, c.day.isoformat(), c.cycles) for c in op.applicator_cycles
    ][:2] == [
        ("APL-L1-01", "2026-04-01", 18666),
        ("APL-L1-01", "2026-04-02", 0),
    ]


def test_cycles_without_the_equipment_catalog_are_an_error(estructurados):
    (estructurados / "ciclos_aplicador.csv").write_text(CYCLES, encoding="utf-8")
    with pytest.raises(ValueError, match="necesita catalogo_equipos"):
        _read(estructurados)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("APL-L2-04,Aplicador,L2", "APL-L1-01,Aplicador,L2", "repetido"),
        (",L2,B,TRM-B-2150", ",L9,B,TRM-B-2150", "línea desconocida"),
        (
            "B,TRM-B-2150,PRS-L2-02,250000",
            "B,TRM-B-2150,PRS-L2-02,",
            "necesita umbral_pm_ciclos",
        ),
        ("PRS-L2-02,250000", "PRS-X-99,250000", "aloja_en apunta a 'PRS-X-99'"),
        ("250000\nAPL-L2", "-5\nAPL-L2", "greater than 0"),
    ],
)
def test_invalid_equipment_is_rejected(estructurados, old, new, message):
    _equipment(estructurados, EQUIPMENT_OK.replace(old, new, 1), cycles=None)
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "catalogo_equipos.csv" in str(err.value)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("2026-04-02,APL-L1-01", "2026-04-02,APL-L9-09", "aplicador desconocido"),
        (
            "2026-04-02,APL-L1-01",
            "2026-04-02,PRS-L1-01",
            "aplicador desconocido",
        ),  # no es aplicador
        ("2026-04-02,APL-L1-01,0", "2026-04-01,APL-L1-01,0", "día repetido"),
        ("18666", "-1", "greater than or equal to 0"),
        ("2026-04-02", "02/04/2026", "Invalid isoformat"),
    ],
)
def test_invalid_cycles_are_rejected(estructurados, old, new, message):
    _equipment(estructurados, cycles=CYCLES.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "ciclos_aplicador.csv" in str(err.value)


def test_events_and_orders_are_checked_against_the_catalog_when_it_exists(
    estructurados,
):
    _equipment(estructurados, cycles=None)
    _write(estructurados, EVENT_OK, ORDER_OK.replace("APL-L1-02", "APL-L1-01"))
    _read(
        estructurados
    )  # EV-2 usa APL-L2-04 en L2: coincide; OT-1/OT-2 usan APL-L1-01 en L1

    def with_events(old, new):
        _write(estructurados, EVENT_OK.replace(old, new, 1))
        return _read(estructurados)

    with pytest.raises(ValueError, match="equipo desconocido 'APL-L2-99'"):
        with_events("APL-L2-04", "APL-L2-99")
    with pytest.raises(ValueError, match="es de la línea L2, no de L1"):
        with_events(",L2,CRP-L2,APL-L2-04", ",L1,CRP-L1,APL-L2-04")
    with pytest.raises(ValueError, match="no es un aplicador"):
        with_events("APL-L2-04", "PRS-L2-02")
    with pytest.raises(ValueError, match="equipo desconocido 'CUT-X'"):
        with_events("APL-L2-04,", "APL-L2-04,CUT-X")
    # Eventos válidos otra vez; OT-2 usa APL-L1-02, que no está en el catálogo.
    _write(estructurados, EVENT_OK, ORDER_OK)
    with pytest.raises(
        ValueError, match="(?s)mantenimiento.csv.*equipo desconocido 'APL-L1-02'"
    ):
        _read(estructurados)


def test_without_the_catalog_nothing_is_cross_checked(estructurados):
    _write(estructurados, EVENT_OK.replace("APL-L2-04", "APL-L2-99"), ORDER_OK)
    op = _read(estructurados)
    assert (
        op.equipment is None
        and op.applicator_cycles is None
        and len(op.defect_events) == 2
    )
