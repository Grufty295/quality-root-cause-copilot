"""cambios.csv y lotes_material.csv: lectura y validación cruzada (sin base de datos)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.seed.test_seed_equipment import _equipment, _read
from tests.seed.test_seed_operational import EVENT_OK, ORDER_OK, _write

CHANGE_HEADER = (
    "cambio_id,fecha,tipo,equipo_id,numero_parte,variante,linea,revision_anterior,revision_nueva,"
    "descripcion,tablero_actualizado,programa_prueba_actualizado,aprobado_por_rol\n"
)
CHANGE_OK = (
    "CHG-1,2026-04-08,Cambio de herramienta,APL-L1-01,TRM-A-1064,,L1,,,Reemplazo de yunque,,,Mantenimiento\n"
    'CHG-2,2026-04-20,ECN,,B3-FDH-0451,Base,"L1, L2",C,D,ECN-1: cambio de cinta,Sí,No aplica,Ingeniería de producto\n'
    'CHG-3,2026-09-11,ECN,"PRS-L1-01, PRS-L2-02",A7-DRH-2210-H,Alta,"L1, L2",H,J,ECN-2 plantillas,No,No,Planeación\n'
)
LOT_HEADER = (
    "lote_id,numero_parte,familia,proveedor_id,proveedor,fecha_recepcion,cantidad,tipo_inspeccion,"
    "resultado_inspeccion,consumo_desde,consumo_hasta,estado\n"
)
LOT_OK = (
    "LT-A-2603-01,TRM-A-1064,A,PRV-01,Vértice Conectores,2026-03-23,150000,Certificado (skip-lot),Liberado,"
    "2026-03-27,2026-04-10,Consumido\n"
    "LT-B-2603-01,TRM-B-2150,B,PRV-02,Conexa Terminales,2026-03-24,40000,Certificado (skip-lot),Liberado,"
    "2026-03-27,2026-04-05,Consumido\n"
)


def _changes(est: Path, body: str = CHANGE_OK, *, catalog: bool = True) -> None:
    if catalog:
        _equipment(est, cycles=None)
    (est / "cambios.csv").write_text(CHANGE_HEADER + body, encoding="utf-8")


SUPPLIER_HEADER = "proveedor_id,nombre,categoria,suministra\n"
SUPPLIER_OK = (
    'PRV-01,Vértice Conectores,A,"TRM-A-1064, TRM-B-2150"\n'
    "PRV-02,Conexa Terminales,A,TRM-B-2150\n"
)


def _suppliers(est: Path, body: str = SUPPLIER_OK) -> None:
    (est / "catalogo_proveedores.csv").write_text(
        SUPPLIER_HEADER + body, encoding="utf-8"
    )


def _lots(est: Path, body: str = LOT_OK, *, catalog: bool = True) -> None:
    if catalog:
        _equipment(est, cycles=None)
    _suppliers(est)
    (est / "lotes_material.csv").write_text(LOT_HEADER + body, encoding="utf-8")


def test_changes_are_mapped_with_multiple_lines_and_equipment(estructurados):
    _changes(estructurados)
    rows = {c.id: c for c in _read(estructurados).changes}
    assert rows["CHG-1"].equipment_ids == ("APL-L1-01",)
    assert rows["CHG-2"].equipment_ids == () and rows["CHG-2"].line_ids == ("L1", "L2")
    assert (rows["CHG-2"].previous_revision, rows["CHG-2"].new_revision) == ("C", "D")
    assert rows["CHG-3"].equipment_ids == ("PRS-L1-01", "PRS-L2-02")
    # "No" y vacío son distintos: la planta no actualizó el tablero vs. el cambio no lo aplica.
    assert rows["CHG-3"].board_updated == "No" and rows["CHG-1"].board_updated is None


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("CHG-2,2026-04-20", "CHG-1,2026-04-20", "cambio_id repetido"),
        ("Cambio de herramienta", "Ajuste", "tipo desconocido"),
        (",L1,,,Reemplazo", ",L9,,,Reemplazo", "línea desconocida"),
        (',"L1, L2",C', ',"L1, L1",C', "repetidos"),
        ("APL-L1-01,TRM", "APL-L9-99,TRM", "equipo desconocido"),
        (
            "APL-L1-01,TRM-A-1064,,L1",
            "APL-L1-01,TRM-A-1064,,L2",
            "que el cambio no declara",
        ),
        (",C,D,", ",C,,", "van juntas o ninguna"),
        (",C,D,", ",D,D,", "igual a la anterior"),
        ("2026-04-08", "08/04/2026", "Invalid isoformat"),
        ("Reemplazo de yunque", "", "descripcion vacía"),
        ("Mantenimiento\n", "\n", "aprobado_por_rol vacío"),
    ],
)
def test_invalid_changes_are_rejected(estructurados, old, new, message):
    assert old in CHANGE_OK
    _changes(estructurados, CHANGE_OK.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "cambios.csv" in str(err.value)


def test_changes_are_not_cross_checked_without_the_catalog(estructurados):
    _changes(
        estructurados, CHANGE_OK.replace("APL-L1-01,TRM", "APL-X-99,TRM"), catalog=False
    )
    assert _read(estructurados).changes[0].equipment_ids == ("APL-X-99",)


def test_lots_are_mapped(estructurados):
    _lots(estructurados)
    lots = _read(estructurados).material_lots
    assert [(x.id, x.quantity, x.supplier_id) for x in lots] == [
        ("LT-A-2603-01", 150000, "PRV-01"),
        ("LT-B-2603-01", 40000, "PRV-02"),
    ]
    assert lots[0].consumed_to.isoformat() == "2026-04-10"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("LT-B-2603-01,TRM", "LT-A-2603-01,TRM", "lote_id repetido"),
        ("TRM-B-2150,B,PRV-02", "TRM-B-2150,A,PRV-02", "ningún aplicador crimpa"),
        ("TRM-A-1064,A,PRV-01", "TRM-Z-0000,A,PRV-01", "no suministra TRM-Z-0000"),
        ("150000", "0", "greater than 0"),
        (
            "2026-03-27,2026-04-10",
            "2026-04-11,2026-04-10",
            "recepción <= consumo_desde",
        ),
        ("2026-03-23", "2026-03-30", "recepción <= consumo_desde"),
        (
            "Liberado,2026-03-27",
            ",2026-03-27",
            "resultado de inspección|inspection_result vacío",
        ),
    ],
)
def test_invalid_lots_are_rejected(estructurados, old, new, message):
    assert old in LOT_OK
    _lots(estructurados, LOT_OK.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "lotes_material.csv" in str(err.value)


def test_events_must_match_their_lot(estructurados):
    _lots(estructurados)
    # EV-2: TRM-A-1064, lote LT-A-2603-01, fabricado el 2026-04-01 (dentro de la ventana).
    _write(estructurados, EVENT_OK, ORDER_OK.replace("APL-L1-02", "APL-L1-01"))
    assert len(_read(estructurados).defect_events) == 2

    def with_events(old, new):
        _write(estructurados, EVENT_OK.replace(old, new, 1))
        return _read(estructurados)

    with pytest.raises(ValueError, match="'LT-A-9999' no está en lotes_material"):
        with_events("LT-A-2603-01", "LT-A-9999")
    with pytest.raises(ValueError, match="es de TRM-B-2150, no de TRM-A-1064"):
        with_events("LT-A-2603-01", "LT-B-2603-01")
    with pytest.raises(ValueError, match="fuera de la ventana de consumo"):
        with_events("EV-00002,2026-04-01,2026-04-09", "EV-00002,2026-05-01,2026-05-09")


def test_without_lots_event_lots_are_not_checked(estructurados):
    _write(estructurados, EVENT_OK.replace("LT-A-2603-01", "LT-XX"), ORDER_OK)
    assert _read(estructurados).material_lots is None


def test_suppliers_are_mapped(estructurados):
    _suppliers(estructurados)
    from app.seed.sources import read_suppliers

    rows = read_suppliers(estructurados / "catalogo_proveedores.csv")
    assert [(s.id, s.supplies) for s in rows] == [
        ("PRV-01", ("TRM-A-1064", "TRM-B-2150")),
        ("PRV-02", ("TRM-B-2150",)),
    ]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("PRV-02,Conexa", "PRV-01,Conexa", "proveedor_id repetido"),
        ("Conexa Terminales", "Vértice Conectores", "nombre repetido"),
        ("TRM-B-2150\n", '""\n', "al menos un número de parte"),
    ],
)
def test_invalid_suppliers_are_rejected(estructurados, old, new, message):
    from app.seed.sources import read_suppliers

    _suppliers(estructurados, SUPPLIER_OK.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        read_suppliers(estructurados / "catalogo_proveedores.csv")
    assert "catalogo_proveedores.csv" in str(err.value)


def test_lots_need_the_supplier_catalog_and_must_agree_with_it(estructurados):
    _lots(estructurados)
    (estructurados / "catalogo_proveedores.csv").unlink()
    with pytest.raises(ValueError, match="necesita catalogo_proveedores"):
        _read(estructurados)
    for body, message in (
        (SUPPLIER_OK.replace("PRV-01", "PRV-07"), "proveedor desconocido 'PRV-01'"),
        (
            SUPPLIER_OK.replace("Vértice Conectores", "Otro Nombre"),
            "se llama 'Otro Nombre'",
        ),
        (
            SUPPLIER_OK.replace('"TRM-A-1064, TRM-B-2150"', "TRM-B-2150"),
            "no suministra TRM-A-1064",
        ),
    ):
        _suppliers(estructurados, body)
        with pytest.raises(ValueError, match=message):
            _read(estructurados)


PRODUCTION_HEADER = "fecha,turno,linea,numero_parte,variante,cliente,unidades\n"
PRODUCTION_OK = (
    "2026-04-01,T1,L1,B3-FDH-0451,Base,Kestrel Modules,158\n"
    "2026-04-01,T3,L2,A7-DRH-2210-M,Media,Norvane Motors,139\n"
)


def _production(est: Path, body: str = PRODUCTION_OK) -> None:
    (est / "produccion.csv").write_text(PRODUCTION_HEADER + body, encoding="utf-8")


def test_production_is_mapped(estructurados):
    _production(estructurados)
    rows = _read(estructurados).production
    assert [(r.line_id, r.shift, r.part_number, r.units) for r in rows] == [
        ("L1", 1, "B3-FDH-0451", 158),
        ("L2", 3, "A7-DRH-2210-M", 139),
    ]


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("2026-04-01,T1", "2026-04-01,T7", "turno desconocido"),
        ("T1,L1", "T1,L9", "línea desconocida"),
        ("B3-FDH-0451,Base", "B3-XXX-0000,Base", "número de parte desconocido"),
        (
            "Kestrel Modules",
            "Norvane Motors",
            "es de Kestrel Modules, no de 'Norvane Motors'",
        ),
        ("158", "0", "greater than 0"),
        ("158", "mucho", "invalid literal"),
        ("2026-04-01", "01/04/2026", "Invalid isoformat"),
    ],
)
def test_invalid_production_is_rejected(estructurados, old, new, message):
    assert old in PRODUCTION_OK
    _production(estructurados, PRODUCTION_OK.replace(old, new, 1))
    with pytest.raises(ValueError, match=message) as err:
        _read(estructurados)
    assert "produccion.csv" in str(err.value)


def test_repeated_production_and_conflicting_variants_are_rejected(estructurados):
    first = PRODUCTION_OK.splitlines(keepends=True)[0]
    _production(estructurados, PRODUCTION_OK + first)
    with pytest.raises(ValueError, match="producción repetida"):
        _read(estructurados)
    _production(
        estructurados,
        PRODUCTION_OK
        + first.replace("2026-04-01", "2026-04-02").replace("Base", "Alta"),
    )
    with pytest.raises(ValueError, match="dos variantes"):
        _read(estructurados)


def test_events_need_production_and_cannot_exceed_it(estructurados):
    # EV-1: 2026-04-01 T1 L1 B3-FDH-0451 x1; EV-2: 2026-04-01 T3 L2 A7-DRH-2210-M x2.
    _write(estructurados, EVENT_OK)
    _production(estructurados)
    assert len(_read(estructurados).defect_events) == 2
    _production(estructurados, PRODUCTION_OK.splitlines(keepends=True)[0])
    with pytest.raises(ValueError, match="no hay producción registrada"):
        _read(estructurados)
    _production(estructurados, PRODUCTION_OK.replace("139", "1"))
    with pytest.raises(ValueError, match="2 piezas defectuosas de 1 producidas"):
        _read(estructurados)
