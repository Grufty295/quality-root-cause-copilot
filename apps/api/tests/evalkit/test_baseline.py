import pytest

from app.evalkit import baseline
from tests.paths import SEED_DIR

EVALS = SEED_DIR.parent.parent / "evals"
if not EVALS.is_dir():
    EVALS = baseline.DEFAULT_EVALS


def test_tfidf_matches_sklearn_defaults():
    vecs = baseline._tfidf(
        ["terminal retraida conector", "terminal con lanza deformada", "a"]
    )
    assert vecs[2] == {}  # tokens de una letra no cuentan
    assert abs(sum(v * v for v in vecs[0].values()) - 1) < 1e-9
    assert baseline._cos(vecs[0], vecs[0]) == pytest.approx(1.0)
    assert 0 < baseline._cos(vecs[0], vecs[1]) < 1


@pytest.mark.skipif(
    not (EVALS / "casos_calidad.jsonl").exists()
    or not (SEED_DIR / "estructurados").exists(),
    reason="no está el dataset real",
)
def test_baseline_numbers_used_by_the_gate():
    s = baseline.run(SEED_DIR, EVALS)["summary"]
    assert (s["all"]["pass"], s["all"]["casos"]) == (11, 20)
    assert (s["dev"]["pass"], s["dev"]["casos"]) == (7, 12)
    assert s["dev"]["rc_top1_new_cause"] == "0/4"
    from app.evalkit.gates import GATES

    gate = next(g for g in GATES if g.id == "pass-linea-base")
    assert gate.threshold > s["dev"]["pass@1"]
