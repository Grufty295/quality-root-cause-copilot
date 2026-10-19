"""Capa HTTP del agente: roles, traducción de errores y forma de la respuesta."""

from __future__ import annotations

import uuid

import pytest

from app.agent.graph import CallInfo
from app.agent.routes import get_analysis_service
from app.agent.service import AnalysisResult
from app.core.errors import Conflict, NotFound
from app.main import app
from tests.conftest import login

NCR = uuid.uuid4()


class StubService:
    def __init__(self, outcome):
        self.outcome, self.seen = outcome, []

    async def analyze(
        self,
        user,
        ncr_id,
        *,
        disciplines=None,
        as_of=None,
        idempotency_key=None,
        agent_instructions=None,
    ):
        self.seen.append((user.role, ncr_id, disciplines))
        self.instructions = agent_instructions
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def stub():
    holder = {}

    def install(outcome):
        holder["svc"] = StubService(outcome)
        app.dependency_overrides[get_analysis_service] = lambda: holder["svc"]
        return holder["svc"]

    yield install
    app.dependency_overrides.pop(get_analysis_service, None)


def test_requires_login(client, stub):
    stub(AnalysisResult(trace_id="t"))
    assert client.post(f"/ncrs/{NCR}/analyze").status_code == 401


@pytest.mark.parametrize("username", ["insp.l1", "gerente.jrz1", "auditor.jrz1"])
def test_only_engineers_may_run_it(client, stub, username):
    svc = stub(AnalysisResult(trace_id="t"))
    login(client, username)
    assert client.post(f"/ncrs/{NCR}/analyze").status_code == 403
    assert svc.seen == []


def test_response_shape_and_disciplines_are_passed_through(client, stub):
    svc = stub(
        AnalysisResult(
            trace_id="abc",
            sections={"D4": {"version_no": 1, "model": "m", "content": {}}},
            blocked={"D2": "motivo"},
            skipped={},
            events=[{"stage": "D4", "event": "violaciones", "detail": "x"}],
            calls=[
                CallInfo(
                    stage="D4",
                    tier="small",
                    model="local-small",
                    destination="local",
                    level="confidencial",
                    input_tokens=10,
                    output_tokens=5,
                    attempts=1,
                )
            ],
        )
    )
    login(client, "ing.l1")
    r = client.post(f"/ncrs/{NCR}/analyze", json={"disciplines": ["D4"]})
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"] == "abc" and body["blocked"] == {"D2": "motivo"}
    assert body["calls"][0]["destination"] == "local"
    assert svc.seen == [("ingeniero", NCR, ("D4",))]


def test_unknown_discipline_and_extra_fields_are_422(client, stub):
    stub(AnalysisResult(trace_id="t"))
    login(client, "ing.l1")
    assert (
        client.post(f"/ncrs/{NCR}/analyze", json={"disciplines": ["D9"]}).status_code
        == 422
    )
    assert client.post(f"/ncrs/{NCR}/analyze", json={"foo": 1}).status_code == 422


@pytest.mark.parametrize(
    ("error", "status"), [(Conflict("ya hay borrador"), 409), (NotFound(), 404)]
)
def test_domain_errors_become_http_status(client, stub, error, status):
    stub(error)
    login(client, "ing.l1")
    assert client.post(f"/ncrs/{NCR}/analyze").status_code == status


def test_agent_not_configured_is_503_not_500(client, monkeypatch):
    from app.agent import runtime

    def boom(_engine):
        raise ValueError("LLM_LOCAL__BASE_URL no definido")

    monkeypatch.setattr(runtime, "build_deps", boom)
    app.state.analysis = None
    login(client, "ing.l1")
    r = client.post(f"/ncrs/{NCR}/analyze")
    assert r.status_code == 503 and "ValueError" in r.json()["detail"]
    assert "BASE_URL" not in r.text  # no se filtra el detalle de configuración


def test_agent_instructions_reach_the_service(client, stub):
    svc = stub(AnalysisResult(trace_id="t"))
    login(client, "ing.l1")
    r = client.post(
        f"/ncrs/{NCR}/analyze",
        json={"disciplines": ["D4"], "agent_instructions": "Revisa el lote de terminal"},
    )
    assert r.status_code == 200, r.text
    assert svc.instructions == "Revisa el lote de terminal"
