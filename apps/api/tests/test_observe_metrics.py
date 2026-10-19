"""Métricas de tiempo y costo que el observador recibe y exporta (sin contenido)."""

from __future__ import annotations

from types import SimpleNamespace

from app.agent.observe import LLMCallEvent, LangfuseObserver, RecordingObserver


class _Obs:
    def __init__(self, name=None, **kw):
        self.name, self.kw, self.children = name, kw, []

    def start_observation(self, **kw):
        child = _Obs(**kw)
        self.children.append(child)
        return child

    def create_event(self, **kw):
        pass

    def update(self, **kw):
        pass

    def end(self):
        pass


class _Client:
    def __init__(self):
        self.root = _Obs()

    def start_observation(self, **kw):
        self.root = _Obs(**kw)
        return self.root

    def flush(self):
        pass


def test_recording_suma_herramientas_y_cuenta_llamadas():
    rec = RecordingObserver()
    rec.tool_call("r1", "defect_summary", 120, True)
    rec.tool_call("r1", "defect_summary", 80, True)
    rec.tool_call("r1", "search_cases", 900, True)
    r = rec.runs["r1"]
    assert r.tool_ms == {"defect_summary": 200, "search_cases": 900}
    assert r.tool_count == {"defect_summary": 2, "search_cases": 1}


def test_langfuse_manda_costo_y_no_duplica_razonamiento_en_usage():
    client = _Client()
    obs = LangfuseObserver(client)
    obs.run_started("t1", ncr_id=SimpleNamespace(), disciplines=["D4"])
    obs.llm_call(
        "t1",
        LLMCallEvent(
            "d4", "small", "m", "local", "interno", 1000, 500, 1,
            latency_ms=42_000, reasoning_tokens=300, cost_usd=0.0123, finish_reason="stop",
        ),
    )
    gen = client.root.children[0]
    assert gen.kw["cost_details"] == {"total": 0.0123}
    assert gen.kw["usage_details"] == {"input": 1000, "output": 500}
    assert gen.kw["metadata"]["latencia_ms"] == 42_000
    assert gen.kw["metadata"]["salida_visible_tokens"] == 200
    assert "input" not in gen.kw and "output" not in gen.kw


def test_langfuse_sin_costo_reportado_no_inventa_uno():
    client = _Client()
    obs = LangfuseObserver(client)
    obs.run_started("t1", ncr_id=SimpleNamespace(), disciplines=["D4"])
    obs.llm_call("t1", LLMCallEvent("d4", "small", "m", "local", "interno", 1, 1, 1))
    assert "cost_details" not in client.root.children[0].kw


def test_langfuse_herramienta_como_span_tipo_tool():
    client = _Client()
    obs = LangfuseObserver(client)
    obs.run_started("t1", ncr_id=SimpleNamespace(), disciplines=["D4"])
    obs.tool_call("t1", "search_cases", 900, True)
    span = client.root.children[0]
    assert span.kw["as_type"] == "tool" and span.kw["metadata"] == {"duracion_ms": 900}


def _dest():
    from decimal import Decimal

    return SimpleNamespace(
        base_url=SimpleNamespace(host="x"), json_mode=True, model_small="m", model_large="m", provider_label="p",
        simulated=True, extra_body={}, price_in_per_mtok=Decimal(0), price_out_per_mtok=Decimal(0),
        api_key=None, timeout_s=1, max_retries=1,
    )
