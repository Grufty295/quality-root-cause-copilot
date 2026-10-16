"""Callbacks del agente sin base: hook de LangGraph, observadores y manifiesto."""

from __future__ import annotations

import asyncio
import inspect
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph

from app.agent.observe import (
    AgentObserver,
    CompositeObserver,
    LangfuseObserver,
    LLMCallEvent,
    NodeCallbacks,
    RecordingObserver,
    RetrievedRef,
    observer_from_env,
)


class _S(TypedDict, total=False):
    x: int


def _graph(fail: bool = False):
    async def a(_s):
        return {"x": 1}

    def b(_s):
        if fail:
            raise ValueError("falla")
        return {"x": 2}

    g = StateGraph(_S)
    g.add_node("a", a)
    g.add_node("b", b)
    g.add_edge(START, "a")
    g.add_conditional_edges("a", lambda s: "b" if s["x"] else END)
    g.add_edge("b", END)
    return g.compile()


def test_langgraph_callbacks_become_stage_times_one_per_node():
    rec = RecordingObserver()
    asyncio.run(_graph().ainvoke({}, config={"callbacks": [NodeCallbacks(rec, "r1")]}))
    r = rec.runs["r1"]
    # Ni el grafo completo ni la función de la arista cuentan como etapa.
    assert set(r.stage_ms) == {"a", "b"}
    assert all(r.stage_ok.values())


def test_node_error_is_reported_as_not_ok():
    rec = RecordingObserver()
    with pytest.raises(ValueError):
        asyncio.run(
            _graph(fail=True).ainvoke(
                {}, config={"callbacks": [NodeCallbacks(rec, "r1")]}
            )
        )
    assert rec.runs["r1"].stage_ok == {"a": True, "b": False}


def test_composite_isolates_failing_observers():
    class Boom(AgentObserver):
        def event(self, *a, **k):
            raise RuntimeError("x")

    rec = RecordingObserver()
    comp = CompositeObserver([Boom(), None, rec])  # type: ignore[list-item]
    comp.event("r", "gather", "tool_rechazada", "d")
    assert rec.runs["r"].events == [("gather", "tool_rechazada", "d")]


def test_recording_observer_keeps_evidence_only_when_asked():
    class Ev:
        id, kind, body, contains_pii = "F1", "fragmento", "texto del caso", False
        document, section, tool, fragment_id = "8D-1", "D4", None, uuid4()

        class level:
            value = "interno"

    class Book:
        def all(self):
            return [Ev()]

    a, b = RecordingObserver(), RecordingObserver(keep_evidence=True)
    for o in (a, b):
        o.run_finished("r", state={"book": Book()}, duration_ms=5, error=None)
    assert a.runs["r"].evidence == {}
    assert b.runs["r"].evidence["F1"]["texto"] == "texto del caso"


# ------------------------------------------------------------------ Langfuse (cliente falso)


class _Obs:
    def __init__(self, log, name, **kw):
        self.log, self.name, self.kw = log, name, kw
        self.id = f"id-{name}"
        log.append(("start", name, kw))

    def start_observation(self, *, name, **kw):
        return _Obs(self.log, name, **kw)

    def create_event(self, *, name, **kw):
        self.log.append(("event", name, kw))

    def update(self, **kw):
        self.log.append(("update", self.name, kw))

    def end(self):
        self.log.append(("end", self.name, {}))


class _FakeLangfuse:
    def __init__(self):
        self.log, self.flushed = [], False

    def start_observation(self, *, trace_context, name, **kw):
        return _Obs(self.log, name, trace_context=trace_context, **kw)

    def flush(self):
        self.flushed = True


def test_langfuse_observer_builds_a_content_free_trace_with_the_run_id():
    lf = _FakeLangfuse()
    obs = LangfuseObserver(lf)
    run_id = uuid4().hex
    obs.run_started(run_id, ncr_id=uuid4(), disciplines=("D2", "D4"))
    obs.stage_started(run_id, "gather")
    obs.retrieved(
        run_id, "search_cases", [RetrievedRef(uuid4(), "8D-2026-011", "D2", 1)]
    )
    obs.event(run_id, "gather", "fragmento_en_cuarentena", "NCR-9:ignore_previous")
    obs.event(run_id, "d4", "escala_al_modelo_grande", "sin_cita")
    obs.stage_finished(run_id, "gather", 12, True)
    obs.llm_call(
        run_id,
        LLMCallEvent("D4", "large", "m", "local", "confidencial", 100, 20, 1),
    )
    obs.run_finished(
        run_id, state={"book": "NO DEBE LEERSE"}, duration_ms=50, error=None
    )
    obs.close()

    root = lf.log[0]
    assert root[1] == "analisis_8d" and root[2]["trace_context"] == {"trace_id": run_id}
    # Ningún objeto lleva input ni output.
    assert not any("input" in kw or "output" in kw for _, _, kw in lf.log)
    events = {name: kw for kind, name, kw in lf.log if kind == "event"}
    assert "detalle" not in events["fragmento_en_cuarentena"]["metadata"]
    assert events["escala_al_modelo_grande"]["metadata"]["detalle"] == "sin_cita"
    gen = next(kw for kind, name, kw in lf.log if name == "llm:D4" and kind == "start")
    assert gen["as_type"] == "generation" and gen["usage_details"] == {
        "input": 100,
        "output": 20,
    }
    assert ("end", "analisis_8d", {}) in lf.log and lf.flushed
    assert "NO DEBE LEERSE" not in repr(lf.log)


def test_trace_exporter_env_selects_langfuse(monkeypatch):
    monkeypatch.delenv("TRACE_EXPORTER", raising=False)
    assert observer_from_env() is None
    monkeypatch.setenv("TRACE_EXPORTER", "json")
    assert observer_from_env() is None


def test_langfuse_refuses_the_default_cloud_host(monkeypatch):
    monkeypatch.setenv("TRACE_EXPORTER", "langfuse")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="cloud.langfuse.com"):
        observer_from_env()


# ------------------------------------------------------------------ manifiesto


def test_manifest_defaults_match_the_code_they_describe():
    from app.agent.llm.gateway import ModelGateway
    from app.agent.manifest import DECODING, RETRIEVAL_TOP_K
    from app.agent.tools import QualityTools

    for name, k in RETRIEVAL_TOP_K.items():
        assert (
            inspect.signature(getattr(QualityTools, name)).parameters["top_k"].default
            == k
        )
    params = inspect.signature(ModelGateway.complete_structured).parameters
    for key in ("temperature", "max_tokens", "max_attempts"):
        assert params[key].default == DECODING[key]


def test_config_id_changes_with_configuration_but_not_with_build(monkeypatch):
    from types import SimpleNamespace

    from app.agent.llm import LLMSettings
    from app.agent.manifest import build_manifest
    from tests.agent.llm.conftest import _local

    settings = LLMSettings(local=_local(), api=None, _env_file=None)  # type: ignore[call-arg]
    deps = SimpleNamespace(
        gateway=SimpleNamespace(settings=settings),
        tool_budget=14,
        d4_max_rounds=2,
        expand_case_links=False,
        max_linked_8d=2,
    )
    monkeypatch.setenv("GIT_SHA", "abc123")
    a = build_manifest(deps, index_version="struct-v1+e5", catalog=None)
    monkeypatch.setenv("GIT_SHA", "def456")
    b = build_manifest(deps, index_version="struct-v1+e5", catalog=None)
    deps.expand_case_links = True
    c = build_manifest(deps, index_version="struct-v1+e5", catalog=None)
    assert a["config_id"] == b["config_id"] != c["config_id"]
    assert a["code_revision"] == "abc123"
    assert "api_key" not in repr(a)
