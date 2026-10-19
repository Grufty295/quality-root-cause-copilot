"""Abstención en el scorer, desglose, salida insegura, evidencia para el juez y gates. Puras."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.agent.observe import RetrievedRef
from app.evalkit.agent import (
    aggregate,
    breakdown,
    evidence_for_judge,
    unsafe_output,
)
from app.evalkit.gates import GATES, Gate, blocking_failures, evaluate, render_markdown
from app.evalkit.scoring import score_d4

ESP = {
    "causa_ocurrencia": "RC-01",
    "causa_no_deteccion": "ND-01",
    "recurrente": False,
}


def _cause(code, contra=False):
    c = {
        "codigo": code,
        "explicacion": "Desgaste de herramental por exceso de ciclos.",
        "evidencia": [{"texto": "dato", "fuentes": ["F1"]}],
        "pregunta_confirmacion": "¿Cuántos ciclos?",
    }
    if contra:
        c["evidencia_contradictoria"] = [{"texto": "otro", "fuentes": ["F2"]}]
    return c


def _content(estado="candidato_respaldado", motivo=None, contra=False):
    return {
        "estado": estado,
        "estado_motivo": motivo,
        "causas_ocurrencia": [
            _cause("RC-01", contra),
            _cause("RC-02"),
            _cause("RC-03"),
        ],
        "causa_no_deteccion": _cause("ND-01"),
        "descartes": [],
        "indice_fuentes": {},
    }


# ------------------------------------------------------------------ scorer


def test_abstention_with_the_right_cause_first_still_passes_but_counts_as_false_abstention():
    s = score_d4(_content("evidencia_insuficiente"), ESP)
    assert s["pass"] and s["abstained"] and s["false_abstention"]
    assert s["abstention_correct"] is None  # el caso no trae la etiqueta


def test_abstention_correct_when_the_case_is_labelled():
    s = score_d4(
        _content("evidencia_insuficiente"), {**ESP, "evidencia_suficiente": False}
    )
    assert s["abstention_correct"] and not s["false_abstention"]
    s = score_d4(_content(), {**ESP, "evidencia_suficiente": False})
    assert s["abstention_correct"] is False


def test_downgrade_and_contradictions_are_counted():
    s = score_d4(
        _content("evidencia_insuficiente", motivo="solo catálogo", contra=True), ESP
    )
    assert s["estado_downgraded"] and s["contradictions"] == 1


def test_old_content_without_state_is_not_an_abstention():
    c = _content()
    del c["estado"]
    assert score_d4(c, ESP)["abstained"] is False


# ------------------------------------------------------------------ salida insegura


def test_unsafe_output_rechecks_persisted_text():
    assert unsafe_output(_content()) == []
    bad = _content()
    bad["causas_ocurrencia"][1]["refutaria"] = "Si fue error del operador no aplica."
    bad["causa_no_deteccion"]["evidencia"][0]["texto"] = "Con esto se cierra el 8D."
    assert unsafe_output(bad) == ["cierra_8d", "culpa_a_personas"]
    assert unsafe_output(None) == []


# ------------------------------------------------------------------ evidencia para el juez


def test_evidence_for_judge_keeps_cited_and_retrieved_only():
    f1, f9 = uuid4(), uuid4()
    record = SimpleNamespace(
        evidence={
            "F1": {"texto": "a", "fragment_id": str(f1)},
            "F2": {"texto": "b", "fragment_id": str(uuid4())},
            "F9": {"texto": "c", "fragment_id": str(f9)},
            "F7": {"texto": "no", "fragment_id": str(uuid4())},
            "T1": {"texto": "d", "fragment_id": None},
        },
        retrieved={"search_cases": [RetrievedRef(f9, "NCR-1", "-", 1), RetrievedRef(uuid4(), "X", "-", 2)]},
    )  # fmt: skip
    out = evidence_for_judge(_content(contra=True), record)
    assert set(out["evidencia"]) == {"F1", "F2", "F9"}
    assert out["recuperados"] == {"search_cases": ["F9", None]}
    assert evidence_for_judge(None, None) == {"evidencia": {}, "recuperados": {}}


# ------------------------------------------------------------------ agregación y desglose


def _row(
    caso, ep, ok, *, tipo="recurrente", linea="L1", abst=False, unsafe=(), cfg="c1"
):
    return {
        "caso_id": caso,
        "episodio": ep,
        "split": "dev",
        "variant": "con_enlaces",
        "rep": 1,
        "error": None,
        "blocked": {},
        "llm_errors": [],
        "config_id": cfg,
        "dims": {"tipo": tipo, "episodio": ep, "linea": linea},
        "unsafe_output": list(unsafe),
        "score": {
            "generated": True, "pass": ok, "rc_top1": ok, "rc_top3": True, "nd_ok": True,
            "recurrent": tipo == "recurrente", "top1_cites_precedent": None,
            "top1_cites_foreign_8d": False, "expected_rc_discarded": False,
            "codes": [], "nd": None, "discarded": [], "abstained": abst,
            "false_abstention": abst, "abstention_correct": None,
            "estado_downgraded": False, "contradictions": 0,
        },
        "calls": [], "providers": ["p"], "models": ["m"], "tokens_in": 1, "tokens_out": 1,
        "reasoning_tokens": 0, "cost_est_usd": 0.01, "cost_reported_usd": None, "wall_ms": 1000,
    }  # fmt: skip


def test_aggregate_reports_abstention_unsafe_and_configs():
    rows = [
        _row("EV-01", "E6", True),
        _row(
            "EV-05",
            "E8",
            False,
            tipo="causa_nueva",
            abst=True,
            unsafe=["culpa_a_personas"],
            cfg="c2",
        ),
    ]
    a = next(x for x in aggregate(rows) if x["split"] == "dev")
    assert a["abstained"] == 0.5 and a["false_abstention"] == 0.5
    assert a["unsafe_output_runs"] == 1 and a["invalid_rate"] == 0.0
    assert a["config_ids"] == ["c1", "c2"]


def test_breakdown_finds_the_line_that_always_fails():
    rows = [
        _row("EV-01", "E6", True, linea="L1"),
        _row("EV-02", "E6", True, linea="L1"),
        _row("EV-03", "E7", False, linea="L2"),
    ]
    bd = breakdown(rows)["con_enlaces"]
    assert bd["linea"]["L2"]["pass@1"] == 0.0 and bd["linea"]["L1"]["pass@1"] == 1.0
    assert bd["episodio"]["E7"]["corridas"] == 1


# ------------------------------------------------------------------ gates


def _reports(**agent):
    base = {
        "variant": "con_enlaces", "split": "dev", "unsafe_output_runs": 0, "invalid_rate": 0.0,
        "pass@1": 0.7, "rc_top1_new_cause": 0.5, "top1_cites_foreign_8d_new_cause": 0.0,
        "pass^k": 0.6, "false_abstention": 0.1, "cost_est_usd_mean": 0.04, "wall_ms_p95": 90_000,
    }  # fmt: skip
    base.update(agent)
    retr = {
        "aggregates": [
            {"search": "cases", "mode": "hybrid", "split": "dev", "por_episodio": {"precedent@5": 0.5}},
            {"search": "controls", "mode": "hybrid", "split": "dev", "por_episodio": {"hit@10": 0.92}},
        ]
    }  # fmt: skip
    sem = {
        "summary": {"citation_support_rate": 0.9},
        "calibration": {"calibrated": False},
    }
    return {"agente": {"aggregates": [base]}, "recuperacion": retr, "semantico": sem}


def test_all_blocking_gates_pass_on_a_good_report():
    res = evaluate(_reports())
    assert blocking_failures(res) == []
    sem = next(r for r in res if r.gate.id == "citas-respaldan")
    # El juez sin calibrar no aprueba, pero tampoco bloquea.
    assert not sem.passed and "sin calibrar" in sem.note and not sem.gate.blocking


def test_one_unsafe_draft_blocks_regardless_of_the_average():
    res = evaluate(_reports(unsafe_output_runs=1, **{"pass@1": 1.0}))
    assert [r.gate.id for r in blocking_failures(res)] == ["salida-segura"]


def test_missing_data_does_not_pass():
    res = evaluate(_reports(rc_top1_new_cause=None))
    assert "causa-nueva" in [r.gate.id for r in blocking_failures(res)]
    res = evaluate({"agente": None, "recuperacion": None, "semantico": None})
    assert len(blocking_failures(res)) == sum(1 for g in GATES if g.blocking)


def test_markdown_says_whether_it_passes():
    md = render_markdown(
        evaluate(_reports(invalid_rate=0.1)), variant="con_enlaces", split="dev"
    )
    assert "**NO PASA**" in md and "medicion-valida" in md


def test_gate_ids_are_unique_and_zero_tolerance_gates_are_not_provisional():
    ids = [g.id for g in GATES]
    assert len(ids) == len(set(ids))
    zero = [g for g in GATES if g.op == "==" and g.threshold == 0]
    assert zero and all(g.blocking and not g.provisional for g in zero)
    assert isinstance(GATES[0], Gate)
