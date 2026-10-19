"""Redactor de clientes, partes y PII, sin base (almacén en memoria)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.agent.llm import CatalogInspector, Message
from app.confidentiality.classifier import CatalogTerm, RuleClassifier
from app.confidentiality.levels import ConfidentialityLevel as L
from app.confidentiality.pii import find_pii
from app.confidentiality.pseudonyms import InMemoryPseudonymStore
from app.confidentiality.redactor import RuleRedactor
from app.confidentiality.text import squash, squash_with_map

TERMS = [
    CatalogTerm("Autolux Motors", L.INTERNO, "cliente"),
    CatalogTerm("Nordic Rail", L.CONFIDENCIAL, "cliente"),
    CatalogTerm("Publicor", L.PUBLICO, "cliente"),
    CatalogTerm("AX-4471-B", L.INTERNO, "parte"),
    CatalogTerm("A7-DRH-2210-M", L.CONFIDENCIAL, "parte"),
]


@pytest.fixture
def ncr():
    return uuid4()


@pytest.fixture
def redactor():
    return RuleRedactor(TERMS, InMemoryPseudonymStore())


def one(redactor, ncr, text):
    return redactor.redact(ncr, [text]).texts[0]


# ------------------------------------------------------------------ texto normalizado


@pytest.mark.parametrize(
    "text",
    [
        "AX-4471-B",
        "Ñandú Ünico — café",
        "Straße ﬁn",
        "é (e + acento combinado) 123",
        "",
    ],
)
def test_squash_with_map_matches_squash(text):
    squashed, index = squash_with_map(text)
    assert squashed == squash(text)
    assert len(index) == len(squashed) and index == sorted(index)


# ------------------------------------------------------------------ catálogo


def test_catalog_terms_are_replaced_whatever_the_spelling(redactor, ncr):
    out = one(redactor, ncr, "Falla en ax 4471 b, tambien AX4471B, de AUTOLUX motors.")
    assert out == "Falla en [PARTE_1], tambien [PARTE_1], de [CLIENTE_1]."


def test_confidential_terms_are_replaced_too(redactor, ncr):
    out = one(redactor, ncr, "nordic rail pidio la parte a7-drh-2210-m")
    assert "nordic" not in out.lower() and "drh" not in out.lower()


def test_public_terms_are_left_alone(redactor, ncr):
    assert (
        one(redactor, ncr, "Publicor reporta lo mismo") == "Publicor reporta lo mismo"
    )


def test_unknown_part_shaped_code_is_replaced(redactor, ncr):
    out = one(redactor, ncr, "Llego B3-FDH-0451 sin etiqueta")
    assert out == "Llego [PARTE_1] sin etiqueta"


def test_inspector_finds_nothing_after_redaction(redactor, ncr):
    inspector = CatalogInspector(
        {
            "cliente": ["Autolux Motors", "Nordic Rail"],
            "parte": ["AX-4471-B", "A7-DRH-2210-M"],
        }
    )
    text = "Autolux Motors y Nordic Rail: ax 4471 b, A7DRH2210M, autoluxmotors"
    out = one(redactor, ncr, text)
    assert inspector.findings(
        [Message(role="user", content=text)]
    )  # sin redactar, sí hay fuga
    assert inspector.findings([Message(role="user", content=out)]) == []


# ------------------------------------------------------------------ PII


def test_person_payroll_and_email_are_replaced(redactor, ncr):
    out = one(
        redactor,
        ncr,
        "El operador Juan Pérez (nómina 123456) escribió a jperez@cablenova.com",
    )
    assert out == "El operador [PERSONA_1] (nómina [NOMINA_1]) escribió a [CORREO_1]"


def test_same_person_same_marker_across_spellings_and_texts(redactor, ncr):
    first = one(redactor, ncr, "El técnico Juan Pérez ajustó la prensa")
    later = one(
        redactor, ncr, "Luego JUAN PEREZ volvió a ajustar; supervisor Ana Ruiz avisó"
    )
    assert first == "El técnico [PERSONA_1] ajustó la prensa"
    assert later == "Luego [PERSONA_1] volvió a ajustar; supervisor [PERSONA_2] avisó"


def test_bare_mention_is_redacted_when_role_appears_later_in_the_same_batch(
    redactor, ncr
):
    out = redactor.redact(
        ncr, ["Juan Pérez insistió", "El operador Juan Pérez paró la línea"]
    ).texts
    assert out == ("[PERSONA_1] insistió", "El operador [PERSONA_1] paró la línea")


def test_bare_name_never_seen_before_is_not_detected(redactor, ncr):
    """Limitación declarada: sin rol delante y sin verse antes, no hay forma de saber que es un nombre."""
    assert one(redactor, ncr, "Juan Pérez paró la línea") == "Juan Pérez paró la línea"


def test_markers_are_per_ncr(redactor):
    a, b = uuid4(), uuid4()
    assert one(redactor, a, "operador Luis Soto") == "operador [PERSONA_1]"
    assert one(redactor, b, "operador Pedro Díaz") == "operador [PERSONA_1]"
    assert redactor.restore(a, ["[PERSONA_1]"]) == ["Luis Soto"]
    assert redactor.restore(b, ["[PERSONA_1]"]) == ["Pedro Díaz"]


@pytest.mark.parametrize(
    "text",
    [
        "El operador Juan Pérez paró la línea",
        "nómina 123456 sin firma",
        "gafete: 98765",
        "contacto jperez@cablenova.com",
    ],
)
def test_whatever_the_classifier_flags_as_pii_the_redactor_replaces(
    text, redactor, ncr
):
    assert RuleClassifier(TERMS).classify(text).contains_pii
    assert find_pii(text)
    assert one(redactor, ncr, text) != text


def test_already_redacted_text_is_unchanged(redactor, ncr):
    once = one(
        redactor, ncr, "operador Juan Pérez, ax-4471-b, Autolux Motors, nómina 123456"
    )
    assert one(redactor, ncr, once) == once


# ------------------------------------------------------------------ restore


def test_restore_roundtrip_returns_canonical_values(redactor, ncr):
    out = one(redactor, ncr, "operador Juan Pérez revisó ax 4471 b de autolux motors")
    back = redactor.restore(ncr, [out])[0]
    assert back == "operador Juan Pérez revisó AX-4471-B de Autolux Motors"


def test_restore_leaves_unknown_markers(redactor, ncr):
    assert redactor.restore(ncr, ["ver [PARTE_9] y [FOO_1]"]) == [
        "ver [PARTE_9] y [FOO_1]"
    ]


def test_restore_in_json_keeps_it_parseable(ncr):
    import json

    store = InMemoryPseudonymStore()
    store.assign(ncr, [("persona", 'O"Brien\nJr')])
    red = RuleRedactor([], store)
    raw = '{"responsable": "[PERSONA_1]"}'
    restored = red.restore(ncr, [raw], json_escaped=True)[0]
    assert json.loads(restored) == {"responsable": 'O"Brien\nJr'}


# ------------------------------------------------------------------ lo que nunca debe salir


def test_result_and_markers_never_carry_values(redactor, ncr):
    res = redactor.redact(ncr, ["operador Juan Pérez, nómina 123456, Autolux Motors"])
    assert res.counts == {"persona": 1, "nomina": 1, "cliente": 1}
    assert "Juan" not in repr(res.counts)
    row = redactor._store.mapping(ncr)[0]
    assert row.real_value not in repr(row)


def test_store_failure_propagates_so_nothing_is_sent(ncr):
    class Broken(InMemoryPseudonymStore):
        def mapping(self, ncr_id):
            raise RuntimeError("base caída")

    with pytest.raises(RuntimeError):
        RuleRedactor(TERMS, Broken()).redact(ncr, ["algo"])


def test_empty_catalog_and_text(ncr):
    red = RuleRedactor([], InMemoryPseudonymStore())
    assert red.redact(ncr, [""]).texts == ("",)
    assert red.redact(ncr, []).texts == ()


def test_role_at_end_of_line_does_not_swallow_the_next_heading():
    """Regresión: "operador⏎Crimpado" se tomaba como nombre y se tachaba "crimpado" en todo el texto."""
    from app.confidentiality.pii import find_pii

    assert find_pii("4. Verificaciones del operador\nCrimpado de terminal") == []
    assert (
        find_pii("Operador Crimpado de terminal") == []
    )  # palabra de proceso, no nombre
    spans = find_pii("el operador Luis Hernández ajustó")
    assert [("persona", "Luis Hernández")] == [
        ("persona", "el operador Luis Hernández ajustó"[x.start : x.end]) for x in spans
    ]


def test_abbreviated_titles_between_role_and_name_are_covered():
    """Regresión: "supervisor Ing. Luis Hernández Pérez" solo pseudonimizaba "Ing"."""
    from app.confidentiality.pii import find_pii

    def names(text):
        return [text[s.start : s.end] for s in find_pii(text) if s.kind == "persona"]

    assert names("Reportó el supervisor Ing. Luis Hernández Pérez, nómina 1") == [
        "Luis Hernández Pérez"
    ]
    assert names("Lo revisó el Ing. Luis Hernández en el turno 2") == ["Luis Hernández"]
    assert names("la Lic. Ana Ruiz firmó") == ["Ana Ruiz"]
    assert (
        names("Ing. de procesos revisó") == []
    )  # minúscula después del título: no es un nombre


def test_phone_numbers_and_labeled_names_are_pseudonymized(redactor, ncr):
    out = one(
        redactor,
        ncr,
        "Contacto del reportante: Paola Ríos Saucedo, celular 656 123 4567. Paola Ríos Saucedo confirma.",
    )
    for secret in ("Paola", "Ríos", "Saucedo", "656 123 4567"):
        assert secret not in out
    assert "[TELEFONO_1]" in out and out.count("[PERSONA_1]") == 2
