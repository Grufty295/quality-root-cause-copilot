"""Códigos, front matter y chunker sobre documentos reales del corpus (copias en fixtures/)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.confidentiality import ConfidentialityLevel as L
from app.ingest.frontmatter import FrontMatterError, parse_document, split_front_matter
from app.retrieval.chunker import chunk_markdown
from app.retrieval.codes import codes_field, codes_tsquery, find_codes, normalize_code, strip_codes
from app.retrieval.models import DocumentKind, SearchQuery

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    doc = parse_document((FIXTURES / name).read_text(encoding="utf-8"))
    return doc, chunk_markdown(source_key=doc.source_key, title=doc.title, kind=doc.kind, body=doc.body)


# ------------------------------------------------------------------ códigos


def test_codes_found_and_normalized():
    text = "APL-L1-02 crimpa TRM-A-1064 (lote LT-A-2604-03) del A7-DRH-2210-M; ver RC-01 y 8D-2026-011."
    assert find_codes(text) == ["APL-L1-02", "TRM-A-1064", "LT-A-2604-03", "A7-DRH-2210-M", "RC-01", "8D-2026-011"]
    assert normalize_code("A7-DRH-2210-M") == "a7drh2210m"


@pytest.mark.parametrize("text", ["2026-04-30", "re-medir la pieza", "Base-Media", "T1 y T2"])
def test_dates_and_hyphenated_words_are_not_codes(text):
    assert find_codes(text) == []


def test_query_codes_are_case_insensitive_and_prefix():
    assert codes_tsquery("intermitencia en apl-l1-02 y a7-drh") == "apll102:* | a7drh:*"
    assert codes_tsquery("sin códigos") is None


def test_strip_codes_keeps_words():
    assert strip_codes("falso contacto en APL-L1-02 tras re-medir").split() == [
        "falso",
        "contacto",
        "en",
        "tras",
        "re-medir",
    ]


def test_codes_field_deduplicates():
    assert codes_field("RC-01, rc-01 y RC-02") == "rc01 rc02"


# ------------------------------------------------------------------ front matter


def test_front_matter_of_real_8d():
    doc, _ = load("8D-2026-011.md")
    assert doc.source_key == "8D-2026-011"
    assert doc.kind is DocumentKind.EIGHT_D
    assert doc.level is L.CONFIDENCIAL and not doc.level_was_defaulted
    assert doc.lines == ("L1",)
    assert doc.customers == ("Norvane Motors", "Kestrel Modules")
    assert doc.contains_pii
    assert doc.extra["estado"] == "Cerrado"


def test_body_claim_cannot_lower_level():
    """ADV-06/07: el documento dice 'PÚBLICO' en el cuerpo; manda el front matter."""
    doc, _ = load("8D-2026-099.md")
    assert "PÚBLICO" in doc.body
    assert doc.level is L.CONFIDENCIAL


def test_missing_level_and_pii_fail_safe():
    text = "---\ndoc_id: SOP-X-001\ntipo: SOP\ntitulo: Sin nivel\nfecha: 2026-01-01\nlineas: [L1]\n---\n\n# T\n\ncuerpo"
    doc = parse_document(text)
    assert doc.level is L.CONFIDENCIAL and doc.level_was_defaulted
    assert doc.contains_pii


def test_unknown_level_fails_safe():
    text = (
        "---\ndoc_id: SOP-X-001\ntipo: SOP\ntitulo: Raro\nfecha: 2026-01-01\n"
        "lineas: [L1]\nconfidencialidad: secreto\n---\nx"
    )
    assert parse_document(text).level is L.CONFIDENCIAL


@pytest.mark.parametrize(
    "text,msg",
    [
        ("sin front matter", "no empieza"),
        ("---\ndoc_id: X\n", "sin cierre"),
        ("---\nmal formato\n---\nx", "clave: valor"),
        ("---\ndoc_id: SOP-X-001\ntipo: MEMO\ntitulo: t\nfecha: 2026-01-01\nlineas: [L1]\n---\nx", "desconocido"),
        ("---\ndoc_id: SOP-X-001\ntipo: SOP\ntitulo: t\nlineas: [L1]\n---\nx", "fecha"),
    ],
)
def test_front_matter_errors(text, msg):
    with pytest.raises(FrontMatterError, match=msg):
        parse_document(text)


def test_split_front_matter_lists():
    meta, body = split_front_matter("---\nlineas: [L1, L2]\nclientes: []\n---\n\ncuerpo")
    assert meta == {"lineas": ["L1", "L2"], "clientes": []}
    assert body.strip() == "cuerpo"


# ------------------------------------------------------------------ chunker


def test_8d_sections_are_disciplines_and_d1_is_dropped():
    _, frags = load("8D-2026-011.md")
    sections = {f.section for f in frags}
    assert {"D2", "D3", "D4", "D7"} <= sections
    assert "D1" not in sections
    everything = "\n".join(f.content for f in frags)
    assert "#50259" not in everything and "Ana Karen" not in everything  # minimización


def test_8d_d4_keeps_subsection_context():
    _, frags = load("8D-2026-011.md")
    d4 = [f for f in frags if f.section == "D4"]
    assert any("Causa de no detección (ND-01)" in f.content.splitlines()[0] for f in d4)
    assert all(f.content.startswith("8D-2026-011 · D4") for f in d4)


def test_fragments_respect_budget_except_atomic_rows():
    for name in ("8D-2026-011.md", "NCR-2026-0001.md", "AMEF-ARN-PD-001.md"):
        _, frags = load(name)
        assert [f.ordinal for f in frags] == list(range(len(frags)))
        for f in frags:
            if not f.section.startswith("RC-"):
                assert len(f.content) <= 550, (name, f.section, len(f.content))


def test_amef_is_split_by_row_with_cause_first():
    _, frags = load("AMEF-ARN-PD-001.md")
    rows = {f.section: f for f in frags if f.section.startswith("RC-")}
    assert len(rows) == 20
    rc01 = rows["RC-01"].content
    assert rc01.startswith("AMEF-ARN-PD-001 › RC-01\nRC-01 — Modo de falla:")
    assert rc01.index("Causa:") < rc01.index("Función:")
    codes = rows["RC-01"].codes.split()
    assert "rc01" in codes and "rc02" not in codes
    assert "amefarnpd001" in codes  # el prefijo hace que buscar el documento encuentre sus filas


def test_ncr_is_one_compact_fragment_without_reporter():
    _, frags = load("NCR-2026-0001.md")
    assert len(frags) == 1
    content = frags[0].content
    assert "Reportado por" not in content and "#41019" not in content
    assert "Código de defecto: DEF-04" in content and "|---|" not in content
    assert "b3fdh0451" in frags[0].codes.split()


# ------------------------------------------------------------------ SearchQuery


def test_search_query_validation():
    q = SearchQuery(text="  falso   contacto  ")
    assert q.text == "falso contacto" and q.mode == "hybrid"
    with pytest.raises(ValueError):
        SearchQuery(text="  a ")
    with pytest.raises(ValueError):
        SearchQuery(text="falso contacto", top_k=50)
    with pytest.raises(ValueError):
        SearchQuery(text="falso contacto", user_id="x")  # el usuario nunca viene en la consulta
