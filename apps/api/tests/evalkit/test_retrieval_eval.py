from __future__ import annotations

from app.evalkit.qrels import Anchor, Qrel
from app.evalkit.retrieval import (
    CaseRow,
    Ranked,
    aggregate,
    build_report,
    render_markdown,
    score,
)


def _qrel(**kw):
    base = {
        "caso_id": "EV-01",
        "episodio": "E6",
        "search": "cases",
        "grades": {Anchor("8D-1", "D4"): 2, Anchor("8D-1"): 1},
        "precedent": "8D-1",
    }
    return Qrel(**{**base, **kw})


def test_symptom_query_finds_the_precedent_but_not_the_cause_section():
    ranked = [Ranked("NCR-9", "Resumen", "ncr"), Ranked("8D-1", "D2", "8d")]
    out, missing = score(ranked, _qrel())
    assert out["precedent@5"] == 1.0
    assert out["hit@5"] == 0.0
    assert missing == ("8D-1#D4",)


def test_precedent_reachable_through_an_ncr_that_cites_it():
    q = _qrel(precedent_links=frozenset({"NCR-H1"}))
    out, _ = score([Ranked("NCR-H1", "Resumen", "ncr")], q)
    assert out["precedent@5"] == 0.0
    assert out["precedent_link@5"] == 1.0


def test_new_cause_case_penalizes_an_8d_in_top5():
    q = _qrel(grades={}, precedent=None, distractor_kinds=("8d",))
    out, _ = score([Ranked("8D-7", "D4", "8d")], q)
    assert out["distractor@5"] == 1.0 and out["precedent@5"] is None
    out, _ = score([Ranked("NCR-1", "x", "ncr")], q)
    assert out["distractor@5"] == 0.0


def _row(caso, epi, split, hit):
    return CaseRow(caso, epi, split, "cases", "hybrid", {"hit@5": hit}, (), ())


def test_aggregate_weights_episodes_equally():
    rows = [_row(f"EV-0{i}", "E6", "dev", 1.0) for i in range(4)] + [
        _row("EV-09", "E8", "dev", 0.0)
    ]
    dev = next(a for a in aggregate(rows) if a["split"] == "dev")
    assert dev["por_caso"]["hit@5"] == 0.8  # 4 de 5 casos
    assert dev["por_episodio"]["hit@5"] == 0.5  # 1 de 2 episodios: el número honesto
    assert (dev["n_cases"], dev["n_episodes"]) == (5, 2)


def test_report_marks_the_sealed_split_and_lists_misses():
    rows = [
        CaseRow(
            "EV-13", "E9", "test", "cases", "hybrid", {"hit@5": 0.0}, (), ("8D-2@D4",)
        )
    ]
    md = render_markdown(
        build_report(
            rows,
            index_version="v",
            embedder="e",
            dataset_sha="x",
            splits=["dev", "test"],
        )
    )
    assert "No se ajusta nada" in md and "EV-13" in md


def test_wrong_8d_reachable_through_a_cited_ncr_is_flagged():
    q = _qrel(cites={"NCR-H1": "8D-1", "NCR-X": "8D-9"})
    out, _ = score([Ranked("NCR-H1", "Resumen", "ncr")], q)
    assert out["wrong_8d_link@5"] == 0.0  # lleva al 8D correcto
    out, _ = score([Ranked("NCR-X", "Resumen", "ncr")], q)
    assert out["wrong_8d_link@5"] == 1.0
