"""mediciones_crimpado.csv: lectura y validación cruzada con el catálogo (sin base de datos)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.seed.test_seed_equipment import EQUIPMENT_OK, _equipment, _read

CRIMP_HEADER = (
    "fecha,turno,linea,aplicador_id,prensa_id,combinacion,altura_mm,altura_lsl,altura_usl,"
    "resultado_altura,traccion_n,traccion_min,resultado_traccion,accion\n"
)
CRIMP_OK = (
    "2026-04-01,T1,L1,APL-L1-01,PRS-L1-01,TRM-A-1064 / WIR-035,0.800,0.770,0.830,OK,62.0,50.0,OK,\n"
    "2026-04-01,T2,L1,APL-L1-01,PRS-L1-01,TRM-A-1064 / WIR-035,0.840,0.770,0.830,NOK,45.0,50.0,NOK,"
    "Re-medición de la misma pieza dentro de especificación; se continúa\n"
    "2026-04-01,T3,L2,APL-L2-04,PRS-L2-02,TRM-B-2150 / WIR-100,1.350,1.320,1.380,OK,160.0,140.0,OK,\n"
)


def _crimp(est: Path, body: str = CRIMP_OK, **equipment) -> None:
    _equipment(est, cycles=None, **equipment)
    (est / "mediciones_crimpado.csv").write_text(CRIMP_HEADER + body, encoding="utf-8")


def test_measurements_are_mapped(estructurados):
    _crimp(estructurados)
    rows = _read(estructurados).crimp_measurements
    assert [(r.equipment_id, r.shift) for r in rows] == [
        ("APL-L1-01", 1),
        ("APL-L1-01", 2),
        ("APL-L2-04", 3),
    ]
    first = rows[0]
    assert (first.press_id, first.terminal_part_number, first.cable_part_number) == (
        "PRS-L1-01",
        "TRM-A-1064",
        "WIR-035",
    )
    assert str(first.height_mm) == "0.800" and str(first.pull_n) == "62.0"
    assert rows[1].action and "Re-medición" in rows[1].action
    assert rows[0].action is None


def test_measurements_without_the_equipment_catalog_are_an_error(estructurados):
    (estructurados / "mediciones_crimpado.csv").write_text(
        CRIMP_HEADER + CRIMP_OK, encoding="utf-8"
    )
    with pytest.raises(ValueError, match="necesita catalogo_equipos"):
        _read(estructurados)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("2026-04-01,T1,L1", "2026-04-01,T9,L1", "turno desconocido"),
        ("T1,L1,APL-L1-01", "T1,L9,APL-L1-01", "línea desconocida"),
        ("T1,L1,APL-L1-01", "T1,L1,APL-L1-99", "equipo desconocido"),
        ("T1,L1,APL-L1-01", "T1,L1,PRS-L1-01", "no es un aplicador"),
        (
            "T1,L1,APL-L1-01,PRS-L1-01",
            "T1,L1,APL-L1-01,PRS-L2-02",
            "no es la que aloja",
        ),
        (
            "TRM-A-1064 / WIR-035,0.800",
            "TRM-A-1064-WIR-035,0.800",
            "combinación inválida",
        ),
        (
            "TRM-A-1064 / WIR-035,0.800",
            "TRM-B-2150 / WIR-035,0.800",
            "crimpa TRM-A-1064",
        ),
        ("0.800,0.770", "abc,0.770", "altura_mm"),
        ("0.770,0.830,OK,62.0", "0.830,0.770,OK,62.0", "no es menor"),
        ("OK,62.0,50.0,OK", "BIEN,62.0,50.0,OK", "resultado de altura desconocido"),
        (
            "0.830,OK,62.0",
            "0.830,NOK,62.0",
            r"resultado de altura \(NOK\) no corresponde",
        ),
        (
            "62.0,50.0,OK",
            "62.0,50.0,NOK",
            r"resultado de tracción \(NOK\) no corresponde",
        ),
        (
            "45.0,50.0,NOK",
            "45.0,50.0,OK",
            r"resultado de tracción \(OK\) no corresponde",
        ),
    ],
)
def test_invalid_measurements_are_rejected_with_row_and_reason(
    estructurados, old, new, message
):
    assert old in CRIMP_OK
    _crimp(estructurados, CRIMP_OK.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "mediciones_crimpado.csv" in str(err.value)


def test_a_repeated_measurement_is_rejected(estructurados):
    first = CRIMP_OK.splitlines(keepends=True)[0]
    _crimp(estructurados, CRIMP_OK + first)
    with pytest.raises(ValueError, match="medición repetida"):
        _read(estructurados)


def test_all_problems_are_reported_together(estructurados):
    body = CRIMP_OK.replace("T1,L1", "T9,L1", 1).replace("T3,L2", "T8,L2", 1)
    _crimp(estructurados, body)
    with pytest.raises(ValueError) as err:
        _read(estructurados)
    assert str(err.value).count("turno desconocido") == 2


def test_the_equipment_fixture_has_the_assumed_presses():
    assert "APL-L1-01,Aplicador,L1,A,TRM-A-1064,PRS-L1-01" in EQUIPMENT_OK
