"""Eval semántico: cableado de DeepEval y Ragas sobre el gateway, con un LLM falso.

No mide la calidad del juez (eso es la calibración): comprueba que cada métrica corre a
través del `ModelGateway` (router, auditoría con etapa `eval`), que el tope de llamadas corta
y que la agregación y la calibración son correctas. Sin deepeval/ragas instalados, se saltan
las pruebas de los frameworks y corren las puras.
"""

from __future__ import annotations

import asyncio
import json
import re
from uuid import uuid4

import pytest

from app.agent.llm import Destination, LLMResult, LLMSettings, ModelGateway, Usage
from app.evalkit import calibration
from app.evalkit.judge import JudgeBudget, JudgeBudgetExceeded, scope_for
from app.evalkit.semantic import claims_of, summarize, top_cause_text
from tests.agent.llm.conftest import _local

# ------------------------------------------------------------------ datos


def _row(**over):
    ev = {
        "F1": {"tipo": "fragmento", "texto": "8D-2026-011 D4: RC-01 desgaste del aplicador", "nivel": "confidencial", "pii": False, "fragment_id": str(uuid4())},
        "F2": {"tipo": "fragmento", "texto": "AMEF RC-01: aplicador fuera de ciclo de PM", "nivel": "interno", "pii": False, "fragment_id": str(uuid4())},
        "F3": {"tipo": "fragmento", "texto": "WI-CRP-002 altura de crimpado", "nivel": "interno", "pii": False, "fragment_id": str(uuid4())},
        "T1": {"tipo": "herramienta", "texto": "APL-L1-02: 260 000 ciclos, umbral 250 000", "nivel": "interno", "pii": False, "fragment_id": None},
    }  # fmt: skip
    cause = {
        "codigo": "RC-01",
        "explicacion": "Desgaste del aplicador por exceder el ciclo de mantenimiento preventivo.",
        "evidencia": [
            {
                "texto": "El aplicador superó el umbral de ciclos",
                "fuentes": ["T1", "F2"],
            },
            {"texto": "El 8D anterior tuvo la misma causa", "fuentes": ["F1"]},
            {"texto": "Lo dice el reporte", "fuentes": ["NCR"]},
        ],
        "evidencia_contradictoria": [
            {"texto": "La altura está centrada", "fuentes": ["F3"]}
        ],
        "pregunta_confirmacion": "¿Cuántos ciclos tenía?",
    }
    row = {
        "run_id": "a" * 32,
        "caso_id": "EV-01",
        "episodio": "E6",
        "variant": "sin_enlaces",
        "rep": 1,
        "ncr_id": str(uuid4()),
        "user_id": str(uuid4()),
        "content": {
            "estado": "candidato_respaldado",
            "causas_ocurrencia": [cause],
            "causa_no_deteccion": None,
        },
        "evidencia": ev,
        "recuperados": {"search_cases": ["F1", None], "search_controls": ["F2", "F3"]},
        "score": {"generated": True},
        "error": None,
        "llm_errors": [],
        "blocked": {},
    }
    row.update(over)
    return row


CASE = {
    "caso_id": "EV-01",
    "ncr": {"descripcion": "Falso contacto en terminal TRM-A crimpada en L2"},
    "esperado": {"causa_ocurrencia": "RC-01"},
}


# ------------------------------------------------------------------ puras


def test_claims_carry_their_cited_text_and_skip_ncr_only_facts():
    claims = claims_of(_row())
    assert [c.kind for c in claims] == ["a_favor", "a_favor", "contradictoria"]
    assert claims[0].fuentes == ("T1", "F2")
    assert claims[0].contextos[0].startswith("[T1] APL-L1-02")
    assert claims[0].id == "a" * 32 + ":causas_ocurrencia[0]:evidencia[0]"


def test_top_cause_text_uses_only_cited_sources():
    response, contexts, ids = top_cause_text(_row())
    assert response.startswith("RC-01:") and ids == ["T1", "F2", "F1"]
    assert len(contexts) == 3


def test_judge_scope_takes_the_highest_level_of_what_it_reads():
    row = _row()
    assert scope_for(row, ["F2", "T1"]).level.value == "interno"
    assert scope_for(row, ["F2", "F1"]).level.value == "confidencial"
    # Sin dato de nivel: se trata como confidencial (igual que el router).
    assert scope_for(row, ["X9"]).level.value == "confidencial"


def test_summary_is_macro_by_episode():
    judged = [
        {"episodio": "E6", "citation_support": 1.0, "claims": [{"kind": "a_favor", "label": "respaldada"}], "errors": []},
        {"episodio": "E6", "citation_support": 1.0, "claims": [], "errors": []},
        {"episodio": "E8", "citation_support": 0.0, "claims": [{"kind": "a_favor", "label": "sin_respaldo"}], "errors": ["x"]},
    ]  # fmt: skip
    s = summarize(judged, {"calibrated": False})
    assert s["citation_support_rate"] == 0.5  # (1.0 + 0.0) / 2 episodios
    assert s["labels"] == {"respaldada": 1, "sin_respaldo": 1}
    assert s["errors"] == 1 and s["calibrated"] is False


def test_kappa_and_calibration_criteria():
    judge = {f"c{i}": "respaldada" for i in range(40)}
    human = {f"c{i}": {"ana": "respaldada"} for i in range(36)}
    human |= {f"c{i}": {"ana": "sin_respaldo"} for i in range(36, 40)}
    cal = calibration.calibrate(judge, human)
    assert cal["n"] == 40 and cal["accuracy"] == 0.9
    # El juez siempre dice "respaldada": acierta 90 % pero no discrimina nada.
    assert cal["kappa"] == 0.0 and not cal["calibrated"]
    assert cal["false_support_rate"] == 0.1


def test_good_judge_with_enough_labels_is_calibrated_and_inter_rater_is_measured():
    labels = ["respaldada", "sin_respaldo", "parcial", "contradice"] * 10
    judge = {f"c{i}": lab for i, lab in enumerate(labels)}
    human = {f"c{i}": {"ana": lab, "beto": lab} for i, lab in enumerate(labels)}
    cal = calibration.calibrate(judge, human)
    assert cal["calibrated"] and cal["kappa"] == 1.0
    assert cal["inter_rater_n"] == 40 and cal["inter_rater_kappa"] == 1.0


def test_label_export_hides_the_judge_and_load_ignores_blanks(tmp_path):
    path = calibration.export_sample(claims_of(_row()), 2, tmp_path / "x.jsonl")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2 and all(r["etiqueta_humana"] is None for r in rows)
    assert "label" not in rows[0] and "score" not in rows[0]
    rows[0]["etiqueta_humana"], rows[0]["revisor"] = "parcial", "ana"
    rows[1]["etiqueta_humana"] = "inventada"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    assert calibration.load_labels(path) == {rows[0]["id"]: {"ana": "parcial"}}


def test_budget_stops_the_judge():
    b = JudgeBudget(max_calls=1)
    asyncio.run(b.take())
    with pytest.raises(JudgeBudgetExceeded):
        asyncio.run(b.take())


# ------------------------------------------------------------------ frameworks (LLM falso)


def _instance(schema: dict, defs: dict | None = None):
    """Un valor mínimo válido para un JSON Schema: lo justo para que la métrica corra."""
    defs = defs or schema.get("$defs", {})
    if "$ref" in schema:
        return _instance(defs[schema["$ref"].split("/")[-1]], defs)
    if "anyOf" in schema:
        return _instance(
            next(s for s in schema["anyOf"] if s.get("type") != "null"), defs
        )
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    t = schema.get("type")
    if t == "object":
        return {k: _instance(v, defs) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [_instance(schema.get("items", {}), defs)]
    if t == "integer":
        return max(1, schema.get("minimum", 1)) if schema.get("maximum", 10) >= 1 else 0
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    return "respuesta del juez"


class SchemaLLM:
    """Lee el JSON Schema que el gateway pone en el prompt y devuelve una instancia válida."""

    def __init__(self):
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        system = request.messages[0].content or ""
        m = re.search(r"JSON Schema:\n(\{.*\})\s*$", system, re.DOTALL)
        body = _instance(json.loads(m.group(1))) if m else "texto libre"
        return LLMResult(
            content=json.dumps(body, ensure_ascii=False) if m else body,
            usage=Usage(input_tokens=10, output_tokens=5),
            model=request.model,
            latency_ms=1,
        )

    async def aclose(self):
        return None


class MemoryAudit:
    def __init__(self):
        self.rows = []

    async def record(self, entry):
        self.rows.append(entry)


def _gateway():
    llm, audit = SchemaLLM(), MemoryAudit()
    settings = LLMSettings(local=_local(), api=None, _env_file=None)  # type: ignore[call-arg]
    return ModelGateway(settings, {Destination.LOCAL: llm}, audit, None), llm, audit


def test_deepeval_and_ragas_metrics_run_through_the_gateway():
    pytest.importorskip("deepeval")
    pytest.importorskip("ragas")
    from app.evalkit.semantic import judge_run

    gw, llm, audit = _gateway()
    budget = JudgeBudget(max_calls=200)
    out = asyncio.run(
        judge_run(
            _row(),
            CASE,
            gw,
            budget,
            ["citas", "causal", "faithfulness", "contexto"],
            {"RC-01": "AMEF RC-01: aplicador fuera de ciclo de PM"},
        )
    )
    assert out["errors"] == [], out["errors"]
    assert [c["label"] for c in out["claims"]] == ["respaldada"] * 3
    assert out["citation_support"] == 1.0
    for key in ("causal_relevance", "faithfulness", "context_precision_controls"):
        assert out[key] is not None, key
    # Todas las llamadas del juez quedan auditadas con etapa `eval` y su nivel.
    assert audit.rows and {r.stage.value for r in audit.rows} == {"eval"}
    assert {r.detected_level.value for r in audit.rows} >= {"confidencial", "interno"}
    assert budget.calls == len(llm.requests) == len(audit.rows)


def test_the_judge_budget_cuts_a_run():
    pytest.importorskip("deepeval")
    from app.evalkit.semantic import judge_run

    gw, _, _ = _gateway()
    with pytest.raises(JudgeBudgetExceeded):
        asyncio.run(
            judge_run(_row(), CASE, gw, JudgeBudget(max_calls=2), ["citas"], {})
        )
