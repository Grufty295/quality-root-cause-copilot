from __future__ import annotations

from datetime import date

import pytest

from app.evalkit.qrels import Anchor, anchor_of, build_qrels, split_of


def _case(
    caso,
    epi,
    *,
    recurrente,
    ocho_d,
    as_of="2026-09-24",
    nd="ND-01",
    aceptables=("ND-01", "ND-07"),
):
    return {
        "caso_id": caso,
        "episodio": epi,
        "as_of": as_of,
        "esperado": {
            "causa_ocurrencia": "RC-01",
            "causa_no_deteccion": nd,
            "no_deteccion_aceptables": list(aceptables),
            "recurrente": recurrente,
            "ocho_d_relacionado": ocho_d,
        },
    }


EPIS = {
    "H1": {"ocho_d": "8D-1", "ncrs_historicas": ["NCR-H1", "NCR-H2"]},
    "E6": {"ncrs_historicas": ["NCR-1", "NCR-2"]},
    "E8": {"ncrs_historicas": []},
}
DATES = {
    "NCR-1": date(2026, 9, 1),
    "NCR-2": date(2026, 10, 1),
    "NCR-H1": date(2026, 5, 1),
    "NCR-H2": date(2026, 5, 2),
}
LINKS = {"RC-01": ("SOP-MNT-008", "WI-CRP-002")}


def _by(qrels, search):
    return next(q for q in qrels if q.search == search)


def test_recurrent_case_expects_the_cause_section_of_the_8d():
    qs = build_qrels(
        [_case("EV-01", "E6", recurrente=True, ocho_d="8D-1")], EPIS, DATES
    )
    cases = _by(qs, "cases")
    assert cases.grades[Anchor("8D-1", "D4")] == 2
    assert cases.grades[Anchor("8D-1")] == 1  # el precedente en otra sección
    assert cases.precedent == "8D-1" and not cases.distractor_kinds


def test_ncr_not_yet_written_at_the_cutoff_is_not_required():
    qs = build_qrels(
        [_case("EV-01", "E6", recurrente=True, ocho_d="8D-1")], EPIS, DATES
    )
    grades = _by(qs, "cases").grades
    assert Anchor("NCR-1") in grades
    assert Anchor("NCR-2") not in grades  # es posterior al corte (2026-09-24)


def test_new_cause_case_has_no_essential_anchor_and_flags_8d_as_distractor():
    qs = build_qrels([_case("EV-09", "E8", recurrente=False, ocho_d=None)], EPIS, DATES)
    cases = _by(qs, "cases")
    assert not any(g >= 2 for g in cases.grades.values())
    assert cases.precedent is None and cases.distractor_kinds == ("8d",)


def test_historical_ncrs_of_the_precedent_are_one_hop_links():
    qs = build_qrels(
        [_case("EV-01", "E6", recurrente=True, ocho_d="8D-1")], EPIS, DATES
    )
    cases = _by(qs, "cases")
    assert cases.precedent_links == frozenset({"NCR-H1", "NCR-H2"})
    assert cases.grades[Anchor("NCR-H1")] == 1


def test_controls_expect_the_linked_control_docs_not_the_catalog_rows():
    qs = build_qrels(
        [_case("EV-01", "E6", recurrente=True, ocho_d="8D-1")], EPIS, DATES, LINKS
    )
    g = _by(qs, "controls").grades
    assert g[Anchor("SOP-MNT-008")] == 2 and g[Anchor("WI-CRP-002")] == 2
    # el agente ya recibe RC y ND completos por el catálogo: útiles, no esenciales
    assert g[Anchor("AMEF-ARN-PD-001", "RC-01")] == 1
    assert (
        g[Anchor("SOP-QA-011", "ND-01")] == 1 and g[Anchor("SOP-QA-011", "ND-07")] == 1
    )


def test_split_is_fixed_by_episode():
    assert [split_of(e) for e in ("E6", "E7", "E8")] == ["dev"] * 3
    assert [split_of(e) for e in ("E9", "E10")] == ["test"] * 2
    with pytest.raises(ValueError):
        split_of("E1")


def test_anchor_of_prefers_exact_then_whole_document():
    grades = {Anchor("8D-1", "D4"): 2, Anchor("8D-1"): 1}
    assert anchor_of("8D-1", "D4", grades) == Anchor("8D-1", "D4")
    assert anchor_of("8D-1", "D2", grades) == Anchor("8D-1")
    assert anchor_of("8D-9", "D2", grades) == Anchor("8D-9", "D2")
