"""El grafo avisa al observador antes de cada llamada al modelo y le pasa el contexto de la traza."""

from __future__ import annotations

import asyncio

from app.agent.observe import AgentObserver
from app.agent.service import AnalysisService
from app.modules.ncr.models import NcrDraft
from app.modules.ncr.service import NcrService
from tests.agent.graph.conftest import FakeAgentLLM, make_deps


class Spy(AgentObserver):
    def __init__(self):
        self.log: list[tuple] = []

    def run_context(self, run_id, *, user_id, session_id, tags, version):
        self.log.append(("context", user_id, session_id, tuple(tags), version))

    def run_started(self, run_id, *, ncr_id, disciplines):
        self.log.append(("started",))

    def llm_call_started(self, run_id, stage):
        self.log.append(("llm_started", stage))

    def llm_call(self, run_id, call):
        self.log.append(("llm_done", call.stage))


def test_every_model_call_is_announced_before_it_finishes_and_the_context_comes_first(env, user_of):
    user = user_of("ing.l1")
    ncr = NcrService(env.conn).open(
        user,
        NcrDraft(
            plant_id="JRZ1",
            line_id="L1",
            shift=2,
            description="Falso contacto intermitente en terminales crimpadas de la línea 1, turno 2, aplicador con desgaste.",
            part_number="A7-DRH-2210-M",
        ),
    )
    spy = Spy()
    deps = make_deps(env, local=FakeAgentLLM())
    asyncio.run(AnalysisService(deps).analyze(user, ncr.id, observer=spy))

    kinds = [e[0] for e in spy.log]
    assert kinds[:2] == ["context", "started"]
    _, uid, sid, tags, version = spy.log[0]
    assert uid == str(user.id) and sid == str(ncr.id) and version
    assert "nivel:confidencial" in tags and "planta:JRZ1" in tags and "linea:L1" in tags
    assert {"disciplina:D2", "disciplina:D4"} <= set(tags)
    # Cada llamada: primero "started", luego "done", sin traslapes.
    calls = [e for e in spy.log if e[0] in ("llm_started", "llm_done")]
    assert len(calls) >= 4 and len(calls) % 2 == 0
    for opened, closed in zip(calls[0::2], calls[1::2], strict=True):
        assert opened[0] == "llm_started" and closed[0] == "llm_done"
        assert opened[1] == closed[1]
