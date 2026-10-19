"""El servidor falso de carga habla el protocolo y produce borradores que pasan el guardrail real.

Si esto falla, una prueba de carga con el stub mediría errores del stub, no de la aplicación.
"""

from __future__ import annotations

import asyncio

import httpx

from app.agent.llm.openai_compat import OpenAICompatibleClient
from app.agent.service import AnalysisService
from app.evalkit.stub_llm import StubConfig, make_app
from app.modules.ncr.models import NcrDraft
from app.modules.ncr.service import NcrService
from tests.agent.graph.conftest import make_deps
from tests.agent.llm.conftest import _local


def _client(app):
    return OpenAICompatibleClient(
        _local(), transport=httpx.ASGITransport(app=app), sleep=_no_sleep
    )


async def _no_sleep(_s: float) -> None:
    return None


def test_a_full_analysis_through_the_http_stub_persists_both_sections(env, user_of):
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
    stub = make_app(StubConfig(d2_s=0, d4_s=0, jitter=0))
    res = asyncio.run(
        AnalysisService(make_deps(env, local=_client(stub))).analyze(user, ncr.id)
    )
    assert res.status == "completada", (res.blocked, res.events)
    assert set(res.sections) == {"D2", "D4"}
    stats = stub.state.stats
    assert stats.by_stage["D4"] >= 1 and stats.by_stage["D2"] == 1


def test_injected_errors_surface_as_provider_errors_not_as_a_hang():
    stub = make_app(StubConfig(d2_s=0, d4_s=0, jitter=0, error_rate=1.0, error_status=503))

    async def go():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=stub), base_url="http://stub"
        ) as c:
            return await c.post("/chat/completions", json={"model": "m", "messages": []})

    r = asyncio.run(go())
    assert r.status_code == 503 and r.headers["retry-after"] == "1"
    assert stub.state.stats.injected_errors == 1
