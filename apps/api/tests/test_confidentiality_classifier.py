"""Clasificador de confidencialidad: reglas puras, sin base de datos."""

from __future__ import annotations

import pytest

from app.confidentiality import ConfidentialityLevel as L
from app.confidentiality.classifier import CatalogTerm, RuleClassifier

CATALOG = (
    CatalogTerm("Norvane Motors", L.CONFIDENCIAL, "cliente"),
    CatalogTerm("Kestrel Modules", L.INTERNO, "cliente"),
    CatalogTerm("A7-DRH-2210-M", L.CONFIDENCIAL, "parte"),
    CatalogTerm("B3-FDH-0451", L.INTERNO, "parte"),
)


@pytest.fixture
def classify():
    return RuleClassifier(CATALOG).classify


def test_plain_operational_text_is_internal_never_public(classify):
    c = classify(
        "Terminal con falso contacto intermitente en el turno nocturno de la linea 2"
    )
    assert (c.level, c.contains_pii, c.reasons) == (
        L.INTERNO,
        False,
        ("sin_hallazgos",),
    )


@pytest.mark.parametrize(
    "text",
    [
        "Reclamo de Norvane Motors por conector incompleto",
        "reclamo de NORVANE MOTORS",
        "El cliente norvane-motors rechazo el lote",
        "Falla en A7-DRH-2210-M",
        "falla en a7 drh 2210 m",
        "Falla en A7DRH2210M",
    ],
)
def test_confidential_customer_or_part_is_confidential(classify, text):
    assert classify(text).level is L.CONFIDENCIAL


def test_internal_customer_and_part_stay_internal(classify):
    c = classify("Kestrel Modules reporta B3-FDH-0451 con cable danado")
    assert c.level is L.INTERNO
    assert set(c.reasons) == {"cliente:interno", "parte:interno"}


def test_highest_level_wins(classify):
    assert (
        classify("Kestrel Modules y Norvane Motors comparten el aplicador").level
        is L.CONFIDENCIAL
    )


def test_part_shaped_but_unknown_is_confidential(classify):
    c = classify("Defecto en Z9-QWE-7788 durante el turno 3")
    assert c.level is L.CONFIDENCIAL
    assert "parte_desconocida" in c.reasons


def test_internal_catalog_codes_are_not_mistaken_for_customer_parts(classify):
    c = classify("Aplicador APL-L1-02 con RC-01 en terminal TRM-A-1064 y cable WIR-050")
    assert c.level is L.INTERNO


@pytest.mark.parametrize(
    "text",
    [
        "Segun el reclamo del cliente hubo rebaba",
        "Reclamo del cliente recibido ayer",
        "Revisar la especificación del cliente para el crimpado",
        "Aplican los CSR vigentes",
        "Falta el plano del cliente",
        "requisitos específicos del cliente",
    ],
)
def test_customer_material_markers_are_confidential(classify, text):
    c = classify(text)
    assert c.level is L.CONFIDENCIAL
    assert any(r.startswith("marcador:") for r in c.reasons)


def test_structured_fields_set_the_level(classify):
    assert (
        classify("Sin mencion en el texto", structured_levels=[L.CONFIDENCIAL]).level
        is L.CONFIDENCIAL
    )
    assert (
        classify("Sin mencion en el texto", structured_levels=[L.INTERNO]).level
        is L.INTERNO
    )


def test_structured_field_with_unknown_level_is_confidential(classify):
    assert classify("texto normal", structured_levels=[None]).level is L.CONFIDENCIAL


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("El operador Juan Perez cambio el aplicador", "pii:persona"),
        ("Lo reviso la supervisora Maria Lopez Ruiz", "pii:persona"),
        ("Empleado 48213 realizo el ajuste", "pii:nomina"),
        ("nomina: 123456", "pii:nomina"),
        ("Avisar a juan.perez@empresa.com", "pii:correo"),
        ("Contacto del reportante: Paola Rios Saucedo", "pii:persona"),
        ("Reportado por Luis Hernandez en el turno 2", "pii:persona"),
        ("Llamar al celular 656 123 4567", "pii:telefono"),
        ("tel: 656-123-4567", "pii:telefono"),
        ("Marcar al 656 123 4567 para confirmar", "pii:telefono"),
    ],
)
def test_pii_is_detected_on_its_own_axis(classify, text, reason):
    c = classify(text)
    assert c.contains_pii is True
    assert reason in c.reasons
    assert c.level is L.INTERNO  # la PII no sube el nivel


def test_pseudonymized_operator_is_not_pii(classify):
    assert classify("El Operador A ajusto la altura de crimpado").contains_pii is False


def test_pii_and_confidential_are_independent(classify):
    c = classify("Reclamo del cliente: el operador Juan Perez omitio el paso")
    assert (c.level, c.contains_pii) == (L.CONFIDENCIAL, True)


def test_reasons_never_contain_the_matched_value(classify):
    c = classify(
        "Norvane Motors, A7-DRH-2210-M, operador Juan Perez, nomina 48213, juan@x.com"
    )
    joined = " ".join(c.reasons).lower()
    for secret in ("norvane", "a7-drh", "juan", "48213", "x.com"):
        assert secret not in joined


def test_short_catalog_terms_are_ignored():
    c = RuleClassifier([CatalogTerm("AB", L.CONFIDENCIAL, "cliente")]).classify(
        "la tabla AB quedo igual"
    )
    assert c.level is L.INTERNO


def test_empty_catalog_still_applies_the_other_rules():
    c = RuleClassifier([]).classify("Reclamo del cliente por B3-FDH-0451")
    assert c.level is L.CONFIDENCIAL


def test_known_limitation_a_name_without_a_role_is_not_detected(classify):
    """Documenta el limite de la heuristica de PII: sin rol delante, un nombre pasa.

    Si esto cambia (p. ej. con Presidio), esta prueba debe actualizarse a proposito.
    """
    assert classify("Juan Perez cambio el aplicador").contains_pii is False


@pytest.mark.parametrize(
    "text",
    [
        "Lote 1234567890 de terminales TRM-A-1064",  # 10 dígitos seguidos sin contexto: un lote, no un teléfono
        "Pedido 20260922 cantidad 3, fecha 2026-09-22",
        "Contacto: Calidad planta 1",  # una etiqueta seguida de un área, no de un nombre
        "Reportó Mantenimiento que la prensa tenía ruido",
        "Responsable: Producción turno 2",
    ],
)
def test_ordinary_numbers_and_departments_after_a_label_are_not_pii(classify, text):
    assert classify(text).contains_pii is False


@pytest.mark.parametrize(
    "text",
    [
        "Nota del SQE: estos arneses comparten circuito con el programa Halcón del OEM.",
        "El OEM pidió contención del lote.",
        "Cambio solicitado en el programa Halcón del cliente",
    ],
)
def test_a_reference_to_the_oem_or_a_customer_program_is_confidential(classify, text):
    assert classify(text).level is L.CONFIDENCIAL


def test_a_maintenance_program_is_not_mistaken_for_a_customer_program(classify):
    assert classify("Programa de mantenimiento preventivo vencido en la prensa").level is L.INTERNO
