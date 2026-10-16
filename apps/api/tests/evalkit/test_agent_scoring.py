from __future__ import annotations

from app.evalkit.agent import aggregate, paired, render_markdown
from app.evalkit.scoring import score_d4

EXP_REC = {
    "causa_ocurrencia": "RC-01",
    "causa_no_deteccion": "ND-01",
    "no_deteccion_aceptables": ["ND-01", "ND-07"],
    "recurrente": True,
    "ocho_d_relacionado": "8D-1",
}
EXP_NEW = {
    **EXP_REC,
    "causa_ocurrencia": "RC-03",
    "recurrente": False,
    "ocho_d_relacionado": None,
}


def _cause(code, *fuentes, respaldo="caso"):
    return {
        "codigo": code,
        "evidencia": [{"texto": "x", "fuentes": list(fuentes)}],
        "respaldo": respaldo,
    }


def _content(codes, nd="ND-01", top1_sources=("F1",), descartes=()):
    causes = [_cause(codes[0], *top1_sources)] + [_cause(c, "F9") for c in codes[1:]]
    return {
        "causas_ocurrencia": causes,
        "causa_no_deteccion": _cause(nd, "F9"),
        "descartes": [{"codigo": c, "motivo": "m"} for c in descartes],
        "indice_fuentes": {
            "F1": {"tipo": "fragmento", "documento": "8D-1", "seccion": "D4"},
            "F2": {"tipo": "fragmento", "documento": "8D-7", "seccion": "D4"},
            "F9": {
                "tipo": "fragmento",
                "documento": "AMEF-ARN-PD-001",
                "seccion": "RC-02",
            },
        },
    }


def test_pass_needs_expected_cause_first_and_acceptable_nd():
    assert score_d4(_content(["RC-01", "RC-02", "RC-03"]), EXP_REC)["pass"]
    s = score_d4(_content(["RC-02", "RC-01", "RC-03"]), EXP_REC)
    assert not s["pass"] and s["rc_top3"] and s["rc_rank"] == 2
    s = score_d4(_content(["RC-01", "RC-02", "RC-03"], nd="ND-07"), EXP_REC)
    assert s["pass"] and not s["nd_exact"]  # aceptable, no exacta
    assert not score_d4(_content(["RC-01", "RC-02", "RC-03"], nd="ND-04"), EXP_REC)[
        "pass"
    ]


def test_precedent_and_foreign_8d_citations():
    s = score_d4(_content(["RC-01", "RC-02", "RC-03"]), EXP_REC)
    assert s["top1_cites_precedent"] and not s["top1_cites_foreign_8d"]
    s = score_d4(_content(["RC-03", "RC-02", "RC-01"], top1_sources=("F2",)), EXP_NEW)
    assert s["top1_cites_precedent"] is None  # no aplica: no es recurrente
    assert (
        s["top1_cites_foreign_8d"] and s["pass"]
    )  # acertó, pero apoyado en un 8D ajeno


def test_no_content_and_discarded_expected_cause():
    s = score_d4(None, EXP_REC)
    assert not s["generated"] and not s["pass"]
    s = score_d4(_content(["RC-02", "RC-03", "RC-04"], descartes=["RC-01"]), EXP_REC)
    assert s["expected_rc_discarded"] and not s["rc_top3"]


def _row(caso, ep, variant, rep, ok, recurrent=True, calls=(), providers=("p",)):
    return {
        "caso_id": caso,
        "episodio": ep,
        "split": "dev",
        "variant": variant,
        "rep": rep,
        "error": None,
        "blocked": {},
        "score": {
            "pass": ok,
            "rc_top1": ok,
            "rc_top3": True,
            "nd_ok": True,
            "generated": True,
            "recurrent": recurrent,
            "top1_cites_precedent": ok if recurrent else None,
            "top1_cites_foreign_8d": False,
            "expected_rc_discarded": False,
            "codes": ["RC-01"],
            "nd": "ND-01",
            "discarded": [],
        },
        "calls": list(calls),
        "linked_8d": [],
        "providers": list(providers),
        "models": ["m"],
        "tokens_in": 100,
        "tokens_out": 10,
        "reasoning_tokens": 0,
        "cost_est_usd": 0.01,
        "cost_reported_usd": None,
        "wall_ms": 1000,
    }


def test_pass_hat_k_requires_every_repetition_and_episodes_weigh_equally():
    rows = [
        _row("EV-01", "E6", "base", 1, True),
        _row("EV-01", "E6", "base", 2, True),
        _row("EV-02", "E6", "base", 1, True),
        _row("EV-02", "E6", "base", 2, False),
        _row("EV-09", "E8", "base", 1, False, recurrent=False),
        _row("EV-09", "E8", "base", 2, False, recurrent=False),
    ]
    a = next(x for x in aggregate(rows) if x["split"] == "all")
    assert a["pass@1"] == (0.75 + 0.0) / 2  # E6: (1 + 0.5)/2; E8: 0
    assert a["pass^k"] == (0.5 + 0.0) / 2 and a["k"] == 2  # EV-02 falla una vez
    assert a["rc_top1_new_cause"] == 0.0


def test_escalation_and_mixed_providers_are_reported():
    big = [{"stage": "D4", "tier": "small"}, {"stage": "D4", "tier": "large"}]
    rows = [
        _row("EV-01", "E6", "base", 1, True, calls=big, providers=("or:A",)),
        _row("EV-01", "E6", "base", 2, True, providers=("or:B",)),
    ]
    a = next(x for x in aggregate(rows) if x["split"] == "all")
    assert a["escalated_to_large"] == 0.5
    report = {
        "meta": {
            "local": {
                "model_small": "s",
                "model_large": "l",
                "simulated": True,
                "extra_body": {},
            },
            "index_version": "v",
            "dataset_sha": "x",
            "splits": ["dev"],
            "runs": 2,
            "generated_at": "t",
        },
        "aggregates": aggregate(rows),
        "paired": paired(rows),
        "runs": rows,
    }
    assert "más de un proveedor" in render_markdown(report)


def test_paired_comparison_lists_cases_that_change():
    rows = [
        _row("EV-01", "E6", "base", 1, False),
        _row("EV-01", "E6", "enlace", 1, True),
        _row("EV-09", "E8", "base", 1, True, recurrent=False),
        _row("EV-09", "E8", "enlace", 1, False, recurrent=False),
        _row("EV-05", "E7", "base", 1, True),
        _row("EV-05", "E7", "enlace", 1, True),
    ]
    p = paired(rows)
    assert (
        p["mejora"] == ["EV-01"]
        and p["empeora"] == ["EV-09"]
        and p["igual"] == ["EV-05"]
    )


def _invalid(caso, ep, variant, rep):
    row = _row(caso, ep, variant, rep, False)
    row["score"] = {**row["score"], "generated": False, "pass": False}
    row["llm_errors"] = ["LLMRequestError: HTTP 404"]
    return row


def test_invalid_runs_are_counted_but_do_not_enter_the_rates():
    from app.evalkit.agent import is_invalid

    bad = _invalid("EV-01", "E6", "base", 1)
    assert is_invalid(bad)
    rows = [bad, _row("EV-01", "E6", "base", 2, True)]
    a = next(x for x in aggregate(rows) if x["split"] == "all")
    assert a["runs"] == 2 and a["errors"] == 1 and a["pass@1"] == 1.0
    only_bad = next(x for x in aggregate([bad]) if x["split"] == "all")
    assert only_bad["pass@1"] is None  # sin corridas válidas no hay tasa, no un 0


def test_a_bad_answer_is_not_invalid():
    from app.evalkit.agent import is_invalid

    row = _row("EV-01", "E6", "base", 1, False)
    assert not is_invalid(row)


def test_resume_keeps_the_latest_line_per_run(tmp_path):
    import json

    from app.evalkit.agent import _load_runs

    p = tmp_path / "x.runs.jsonl"
    first = _invalid("EV-01", "E6", "base", 1)
    second = _row("EV-01", "E6", "base", 1, True)
    p.write_text(json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    rows = _load_runs(p)
    assert len(rows) == 1 and rows[0]["score"]["pass"]


def test_runs_saved_before_llm_errors_existed_are_still_invalid():
    from app.evalkit.agent import is_invalid

    old = _row("EV-01", "E6", "base", 1, False)
    old["score"] = {**old["score"], "generated": False}
    old.pop("llm_errors", None)
    old["blocked"] = {
        "D4": "- No se pudo obtener una respuesta del modelo (LLMRequestError)."
    }
    assert is_invalid(old)
