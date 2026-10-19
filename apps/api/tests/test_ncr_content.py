"""Validación del contenido de una sección editada a mano (sin base de datos)."""

from __future__ import annotations

import copy
from uuid import uuid4

import pytest

from app.agent.catalog import CatalogEntry, CauseCatalog
from app.confidentiality import ConfidentialityLevel
from app.core.errors import Invalid
from app.modules.ncr.content import validate_content

SOURCES = {"NCR": {"tipo": "reporte"}, "F1": {"tipo": "fragmento", "fragment_id": "x"}}


def hecho(texto: str = "Terminal con falso contacto", fuentes=("NCR",)) -> dict:
    return {"texto": texto, "fuentes": list(fuentes)}


def d2() -> dict:
    campos = ("que", "por_que", "donde", "cuando", "quien", "como", "cuanto")
    return {**{c: hecho() for c in campos}, "indice_fuentes": copy.deepcopy(SOURCES)}


def causa(codigo: str, **extra) -> dict:
    return {
        "codigo": codigo,
        "explicacion": "Desgaste del punzón del aplicador por encima del umbral de PM.",
        "evidencia": [hecho(fuentes=("NCR", "F1"))],
        "pregunta_confirmacion": "¿Cuántos ciclos lleva el aplicador desde el último PM?",
        "respaldo": "caso",
        **extra,
    }


def d4() -> dict:
    return {
        "estado": "candidato_respaldado",
        "causas_ocurrencia": [causa("RC-01"), causa("RC-02"), causa("RC-03")],
        "causa_no_deteccion": causa("ND-01"),
        "descartes": [],
        "indice_fuentes": copy.deepcopy(SOURCES),
    }


def entry(code: str) -> CatalogEntry:
    return CatalogEntry(code, "fila", uuid4(), ConfidentialityLevel.INTERNO, False)


CATALOG = CauseCatalog(
    occurrence={c: entry(c) for c in ("RC-01", "RC-02", "RC-03")},
    non_detection={"ND-01": entry("ND-01")},
)


def test_valid_content_passes():
    validate_content("D2", d2())
    validate_content("D4", d4(), CATALOG)


def test_an_agent_style_d4_with_fewer_causes_passes():
    content = d4()
    content["causas_ocurrencia"] = content["causas_ocurrencia"][:2]
    validate_content("D4", content, CATALOG)


@pytest.mark.parametrize("content", [{}, None])
def test_empty_content_is_invalid(content):
    with pytest.raises(Invalid, match="vacio"):
        validate_content("D2", content or {})


def test_oversized_content_is_invalid():
    content = d2()
    content["que"]["texto"] = "x" * 70_000
    with pytest.raises(Invalid, match="grande"):
        validate_content("D2", content)


def test_d2_field_without_sources_is_invalid():
    content = d2()
    content["que"] = {"texto": "Terminal con falso contacto", "citas": []}
    with pytest.raises(Invalid, match="no cumple el formato"):
        validate_content("D2", content)


def test_d2_citing_a_source_missing_from_the_index_is_invalid():
    content = d2()
    content["donde"]["fuentes"] = ["F9"]
    with pytest.raises(Invalid, match="F9"):
        validate_content("D2", content)


def test_d4_legacy_free_text_keys_are_rejected():
    content = d4()
    content["causas_ocurrencia"][0]["descripcion"] = "texto libre"
    with pytest.raises(Invalid, match="descripcion"):
        validate_content("D4", content, CATALOG)


def test_d4_needs_at_least_one_cause():
    content = d4()
    content["causas_ocurrencia"] = []
    with pytest.raises(Invalid, match="al menos una"):
        validate_content("D4", content, CATALOG)


def test_d4_duplicate_codes_are_invalid():
    content = d4()
    content["causas_ocurrencia"][1]["codigo"] = "RC-01"
    with pytest.raises(Invalid, match="distintos"):
        validate_content("D4", content, CATALOG)


def test_d4_wrong_code_family_is_invalid():
    content = d4()
    content["causas_ocurrencia"][0]["codigo"] = "ND-01"
    with pytest.raises(Invalid, match="RC-xx"):
        validate_content("D4", content, CATALOG)
    content = d4()
    content["causa_no_deteccion"]["codigo"] = "RC-01"
    with pytest.raises(Invalid, match="ND-xx"):
        validate_content("D4", content, CATALOG)


def test_d4_code_outside_the_catalog_is_invalid():
    content = d4()
    content["causas_ocurrencia"][0]["codigo"] = "RC-19"
    with pytest.raises(Invalid, match="RC-19"):
        validate_content("D4", content, CATALOG)


def test_d4_code_check_is_skipped_when_the_catalog_is_incomplete():
    content = d4()
    content["causas_ocurrencia"][0]["codigo"] = "RC-19"
    validate_content("D4", content, CauseCatalog(occurrence={}, non_detection={}))


def test_d4_citing_a_source_missing_from_the_index_is_invalid():
    content = d4()
    content["causa_no_deteccion"]["evidencia"] = [hecho(fuentes=("T7",))]
    with pytest.raises(Invalid, match="T7"):
        validate_content("D4", content, CATALOG)


def test_many_errors_are_summarised():
    content = d2()
    for campo in ("que", "donde", "cuando", "quien", "como"):
        content[campo] = {"texto": ""}
    with pytest.raises(Invalid, match=r"y \d+ más"):
        validate_content("D2", content)
