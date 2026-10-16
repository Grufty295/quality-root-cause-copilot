"""Lectura y validación de los CSV del seed. Sin base de datos."""

from __future__ import annotations

import pytest

from app.modules.auth.demo_users import OTHER_PLANT_USER, read_roster, scopes_for
from app.seed.service import build_roster
from app.seed.sources import read_catalogs


def test_roles_map_to_enum_including_inspector(estructurados):
    roles = {
        u.username: u.role for u in read_roster(estructurados / "usuarios_demo.csv")
    }
    assert roles == {
        "u-insp-l1": "inspector",
        "u-insp-l2": "inspector",
        "u-ingcal-1": "ingeniero",
        "u-gercal": "gerente",
        "u-auditor": "auditor",
    }


def test_unknown_role_is_an_error(estructurados):
    path = estructurados / "usuarios_demo.csv"
    path.write_text("usuario_id,rol,lineas\nx,superadmin,L1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="rol desconocido"):
        read_roster(path)


def test_missing_column_is_an_error(estructurados):
    path = estructurados / "usuarios_demo.csv"
    path.write_text("usuario_id,rol\nx,auditor\n", encoding="utf-8")
    with pytest.raises(ValueError, match="faltan columnas"):
        read_roster(path)


def test_scopes_all_lines_is_plant_wide_else_per_line(estructurados):
    users = {u.username: u for u in read_roster(estructurados / "usuarios_demo.csv")}
    lines = {"L1", "L2"}
    assert scopes_for(users["u-gercal"], plant_id="JRZ1", plant_lines=lines) == [
        ("JRZ1", None)
    ]
    assert scopes_for(users["u-insp-l1"], plant_id="JRZ1", plant_lines=lines) == [
        ("JRZ1", "L1")
    ]


def test_unknown_line_is_an_error(estructurados):
    users = {u.username: u for u in read_roster(estructurados / "usuarios_demo.csv")}
    with pytest.raises(ValueError, match="no existen"):
        scopes_for(users["u-insp-l2"], plant_id="JRZ1", plant_lines={"L1"})


def test_roster_adds_other_plant_user(estructurados):
    assert OTHER_PLANT_USER in build_roster(estructurados)


def test_catalogs_confidentiality_and_skipped_parts(estructurados):
    c = read_catalogs(estructurados)
    assert {x.id: x.is_confidential for x in c.customers} == {"NOR": True, "KES": False}
    assert {p.part_number: p.customer_id for p in c.parts} == {
        "B3-FDH-0451": "KES",
        "A7-DRH-2210-M": "NOR",
    }
    assert c.skipped_parts == ("TRM-A-1064",)
    assert [f.id for f in c.defect_families] == ["DEF-01", "DEF-02"]


def test_unknown_confidentiality_is_confidential(estructurados):
    path = estructurados / "catalogo_clientes.csv"
    path.write_text(
        "cliente_id,nombre,tipo,confidencialidad\nKES,Kestrel Modules,Tier 1,raro\n",
        encoding="utf-8",
    )
    (estructurados / "catalogo_numeros_parte.csv").write_text(
        "numero_parte,tipo,descripcion,variante,cliente,confidencialidad\n",
        encoding="utf-8",
    )
    assert read_catalogs(estructurados).customers[0].is_confidential is True


def test_part_with_unknown_customer_is_an_error(estructurados):
    path = estructurados / "catalogo_numeros_parte.csv"
    path.write_text(
        "numero_parte,tipo,descripcion,variante,cliente,confidencialidad\nP1,Arnés,x,,Nadie SA,interno\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cliente desconocido"):
        read_catalogs(estructurados)
