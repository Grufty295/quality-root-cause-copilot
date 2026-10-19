"""La traza de Langfuse: duración real de cada llamada al modelo, atributos de la traza y scores en línea."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar
from uuid import uuid4

import pytest

from app.agent import observe
from app.agent.observe import LangfuseObserver, LLMCallEvent, http_score_sender


class _Obs:
    def __init__(self, tree, name, parent, kw):
        self.tree, self.name, self.parent, self.kw = tree, name, parent, kw
        self.open = True
        self.updates: list[dict] = []
        self.scores: list[tuple[str, float]] = []
        tree.append(self)

    def start_observation(self, *, name, **kw):
        return _Obs(self.tree, name, self.name, kw)

    def create_event(self, **kw):
        pass

    def update(self, **kw):
        self.updates.append(kw)

    def score_trace(self, *, name, value, data_type=None, **kw):
        self.scores.append((name, value))

    def end(self):
        self.open = False


class _Lf:
    def __init__(self):
        self.tree: list[_Obs] = []

    def start_observation(self, *, trace_context, name, **kw):
        return _Obs(self.tree, name, None, kw)

    def flush(self):
        pass

    def by_name(self, name):
        return [o for o in self.tree if o.name == name]


CALL = LLMCallEvent("D4", "small", "m", "local", "confidencial", 100, 20, 1, latency_ms=5)


def test_the_generation_opens_before_the_call_under_its_stage_and_closes_with_the_usage():
    lf, rid = _Lf(), uuid4().hex
    obs = LangfuseObserver(lf)
    obs.run_started(rid, ncr_id=uuid4(), disciplines=("D4",))
    obs.stage_started(rid, "d4_small")
    obs.llm_call_started(rid, "D4")
    (gen,) = lf.by_name("llm:D4")
    assert gen.open and gen.parent == "d4_small"  # abierta mientras el modelo trabaja
    obs.llm_call(rid, CALL)
    assert not gen.open
    assert gen.updates[0]["usage_details"] == {"input": 100, "output": 20}
    assert len(lf.by_name("llm:D4")) == 1  # no se creó una segunda
    obs.stage_finished(rid, "d4_small", 10, True)
    obs.run_finished(rid, state=None, duration_ms=10, error=None)


def test_a_failed_run_still_closes_an_open_generation():
    lf, rid = _Lf(), uuid4().hex
    obs = LangfuseObserver(lf)
    obs.run_started(rid, ncr_id=uuid4(), disciplines=("D4",))
    obs.llm_call_started(rid, "D4")
    obs.run_finished(rid, state=None, duration_ms=1, error="CancelledError")
    assert all(not o.open for o in lf.tree)


def test_llm_call_without_a_started_generation_still_records_it():
    lf, rid = _Lf(), uuid4().hex
    obs = LangfuseObserver(lf)
    obs.run_started(rid, ncr_id=uuid4(), disciplines=("D4",))
    obs.llm_call(rid, CALL)
    (gen,) = lf.by_name("llm:D4")
    assert gen.kw["usage_details"] == {"input": 100, "output": 20} and not gen.open


def test_trace_attributes_are_applied_when_the_root_is_created(monkeypatch):
    seen: list[tuple[str, object]] = []

    @contextlib.contextmanager
    def fake_propagate(ctx):
        seen.append(("enter", ctx))
        yield
        seen.append(("exit", None))

    monkeypatch.setattr(observe, "_propagate_attributes", fake_propagate)

    class Lf(_Lf):
        def start_observation(self, **kw):
            seen.append(("root", kw["name"]))
            return super().start_observation(**kw)

    rid, user, ncr = uuid4().hex, uuid4(), uuid4()
    obs = LangfuseObserver(Lf())
    obs.run_context(
        rid, user_id=str(user), session_id=str(ncr), tags=["nivel:confidencial"], version="p1"
    )
    obs.run_started(rid, ncr_id=ncr, disciplines=("D4",))
    assert [k for k, _ in seen] == ["enter", "root", "exit"]
    assert seen[0][1] == {
        "user_id": str(user),
        "session_id": str(ncr),
        "tags": ["nivel:confidencial"],
        "version": "p1",
    }


class _Sink:
    """Recoge `(trace_id, nombre, valor)` en lugar de hablar con Langfuse."""

    def __init__(self):
        self.sent: list[tuple[str, str, float]] = []

    def __call__(self, trace_id, name, value):
        self.sent.append((trace_id, name, value))


def test_online_scores_count_guardrail_work_and_never_carry_text():
    lf, rid, sink = _Lf(), uuid4().hex, _Sink()
    obs = LangfuseObserver(lf, score_sender=sink)
    obs.run_started(rid, ncr_id=uuid4(), disciplines=("D4",))
    state = {
        "events": [
            {"stage": "d4", "event": "violaciones", "detail": "TEXTO QUE NO DEBE SALIR"},
            {"stage": "d4", "event": "escala_al_modelo_grande", "detail": ""},
            {"stage": "gather", "event": "fragmento_en_cuarentena", "detail": "x"},
        ],
        "blocked": {"D2": "motivo"},
    }
    obs.run_finished(rid, state=state, duration_ms=1, error=None)
    obs.close()
    assert {t for t, _, _ in sink.sent} == {rid}  # cuelgan de la traza del análisis
    assert {n: v for _, n, v in sink.sent} == {
        "escalo_a_modelo_grande": 1.0,
        "violaciones_guardrail": 1.0,
        "errores_llm": 0.0,
        "fragmentos_en_cuarentena": 1.0,
        "disciplinas_bloqueadas": 1.0,
    }
    assert "TEXTO QUE NO DEBE SALIR" not in repr(sink.sent)


def test_no_scores_when_the_graph_raised():
    lf, rid, sink = _Lf(), uuid4().hex, _Sink()
    obs = LangfuseObserver(lf, score_sender=sink)
    obs.run_started(rid, ncr_id=uuid4(), disciplines=("D4",))
    obs.run_finished(rid, state=None, duration_ms=1, error="Boom")
    obs.close()
    assert sink.sent == []


def test_a_rejected_score_is_logged_and_does_not_break_the_trace(caplog):
    def reject(trace_id, name, value):
        raise RuntimeError("HTTP 400: expected object, received array")

    lf, rid = _Lf(), uuid4().hex
    obs = LangfuseObserver(lf, score_sender=reject)
    obs.run_started(rid, ncr_id=uuid4(), disciplines=("D4",))
    with caplog.at_level(logging.WARNING, logger="app.agent.observe"):
        obs.run_finished(rid, state={"events": [], "blocked": {}}, duration_ms=1, error=None)
        obs.close()
    assert not lf.tree[0].open  # el span raíz se cerró de todos modos
    assert "rechazó el score" in caplog.text and "HTTP 400" in caplog.text  # y no pasó en silencio


class _Langfuse(BaseHTTPRequestHandler):
    """Se comporta como el Langfuse 3.162 del proyecto: acepta un objeto y rechaza un arreglo."""

    received: ClassVar[list[dict]] = []
    reject_all: ClassVar[bool] = False

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        ok = isinstance(body, dict) and not type(self).reject_all
        if ok:
            type(self).received.append({"path": self.path, "auth": self.headers["authorization"], **body})
        self.send_response(200 if ok else 400)
        self.end_headers()
        self.wfile.write(b'{"id":"x"}' if ok else b'{"message":"Invalid request data"}')

    def log_message(self, *a):
        pass


@pytest.fixture()
def langfuse_server():
    _Langfuse.received, _Langfuse.reject_all = [], False
    srv = HTTPServer(("127.0.0.1", 0), _Langfuse)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", _Langfuse
    srv.shutdown()


def test_http_sender_posts_one_object_per_score_with_a_stable_id(langfuse_server):
    host, srv = langfuse_server
    send = http_score_sender(host, "pk", "sk", environment="dev")
    send("t" * 32, "errores_llm", 2.0)
    send("t" * 32, "errores_llm", 2.0)
    (a, b) = srv.received
    assert a["path"] == "/api/public/scores" and a["auth"].startswith("Basic ")
    assert a["traceId"] == "t" * 32 and a["name"] == "errores_llm" and a["value"] == 2.0
    assert a["dataType"] == "NUMERIC" and a["id"] == b["id"] == "t" * 32 + "-errores_llm"
    assert a["environment"] == "dev"  # el mismo entorno que la traza, no `default`


def test_http_sender_raises_with_the_server_reason(langfuse_server):
    host, srv = langfuse_server
    srv.reject_all = True
    with pytest.raises(RuntimeError, match="HTTP 400.*Invalid request data"):
        http_score_sender(host, "pk", "sk")("t" * 32, "x", 1.0)


def test_the_observer_delivers_scores_end_to_end_over_http(langfuse_server):
    host, srv = langfuse_server
    lf, rid = _Lf(), uuid4().hex
    obs = LangfuseObserver(lf, score_sender=http_score_sender(host, "pk", "sk"))
    obs.run_started(rid, ncr_id=uuid4(), disciplines=("D4",))
    obs.run_finished(rid, state={"events": [], "blocked": {}}, duration_ms=1, error=None)
    obs.close()
    assert sorted(r["name"] for r in srv.received) == [
        "disciplinas_bloqueadas",
        "errores_llm",
        "escalo_a_modelo_grande",
        "fragmentos_en_cuarentena",
        "violaciones_guardrail",
    ]
