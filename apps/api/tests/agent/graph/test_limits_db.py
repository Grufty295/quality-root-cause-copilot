"""El tope de análisis simultáneos en el servicio y en HTTP."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from app.agent.limits import AnalysisLimiter
from app.agent.routes import get_analysis_service
from app.agent.service import AnalysisService
from app.core.errors import TooManyRequests
from app.main import app
from app.modules.ncr.models import NcrDraft
from app.modules.ncr.service import NcrService
from tests.agent.graph.conftest import FakeAgentLLM, make_deps
from tests.conftest import login


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def ncr(env, user_of):
    return NcrService(env.conn).open(
        user_of("ing.l1"),
        NcrDraft(
            plant_id="JRZ1",
            line_id="L1",
            shift=2,
            description="Falso contacto intermitente en terminales crimpadas de la línea 1, turno 2, aplicador con desgaste.",
            part_number="A7-DRH-2210-M",
        ),
    )


def _runs(env, ncr_id):
    return env.conn.execute(
        text("SELECT count(*) FROM analysis_run WHERE ncr_id = :n"), {"n": ncr_id}
    ).scalar_one()


def test_when_the_agent_is_full_nothing_is_started_and_the_model_is_not_called(env, user_of, ncr):
    user, llm = user_of("ing.l1"), FakeAgentLLM()
    limiter = AnalysisLimiter(max_total=1, max_per_user=1, retry_after_s=9)
    svc = AnalysisService(make_deps(env, local=llm), limiter=limiter)
    with limiter.slot(uuid.uuid4()):  # otro usuario ocupa el único cupo
        with pytest.raises(TooManyRequests) as err:
            run(svc.analyze(user, ncr.id))
    assert err.value.retry_after_s == 9
    assert _runs(env, ncr.id) == 0 and llm.requests == []
    assert limiter.in_flight == 0


def test_the_slot_is_released_after_a_normal_analysis(env, user_of, ncr):
    limiter = AnalysisLimiter(max_total=1, max_per_user=1)
    svc = AnalysisService(make_deps(env, local=FakeAgentLLM()), limiter=limiter)
    res = run(svc.analyze(user_of("ing.l1"), ncr.id))
    assert res.status == "completada" and limiter.in_flight == 0


def test_replaying_an_idempotency_key_does_not_need_a_slot(env, user_of, ncr):
    user, key = user_of("ing.l1"), "carga-clave-0001"
    limiter = AnalysisLimiter(max_total=1, max_per_user=1)
    svc = AnalysisService(make_deps(env, local=FakeAgentLLM()), limiter=limiter)
    first = run(svc.analyze(user, ncr.id, idempotency_key=key))
    with limiter.slot(uuid.uuid4()):  # el agente está lleno
        again = run(svc.analyze(user, ncr.id, idempotency_key=key))
    assert again.replayed is True and again.run_id == first.run_id


def test_http_returns_429_with_retry_after(client):
    class Full:
        async def analyze(self, *a, **k):
            raise TooManyRequests("El agente está ocupado", retry_after_s=30)

    app.dependency_overrides[get_analysis_service] = lambda: Full()
    try:
        login(client, "ing.l1")
        r = client.post(f"/ncrs/{uuid.uuid4()}/analyze")
    finally:
        app.dependency_overrides.pop(get_analysis_service, None)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "30"
    assert "ocupado" in r.json()["detail"]


def test_analyze_does_not_hold_a_pool_connection_while_it_runs(client):
    """H1 de la prueba de carga: la autenticación devuelve su conexión antes de entrar al análisis."""
    from app.core.db import get_engine

    seen: list[int] = []

    class Probe:
        async def analyze(self, *a, **k):
            seen.append(get_engine().pool.checkedout())
            raise TooManyRequests("ocupado", retry_after_s=1)

    app.dependency_overrides[get_analysis_service] = lambda: Probe()
    try:
        login(client, "ing.l1")
        baseline = get_engine().pool.checkedout()  # lo que otras fixtures tengan abierto
        assert client.post(f"/ncrs/{uuid.uuid4()}/analyze").status_code == 429
    finally:
        app.dependency_overrides.pop(get_analysis_service, None)
    assert seen == [baseline]


def test_analyze_without_session_is_401_and_wrong_role_is_403(client):
    assert client.post(f"/ncrs/{uuid.uuid4()}/analyze").status_code == 401
    login(client, "insp.l1")
    assert client.post(f"/ncrs/{uuid.uuid4()}/analyze").status_code == 403
