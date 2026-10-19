"""H1 de la prueba de carga, reproducido en segundos: tantas peticiones /analyze como conexiones tiene el pool.

Antes de la corrección cada petición retenía la conexión de autenticación y pedía otra (como `_replay`); con N peticiones
y un pool de N, todas esperaban a todas hasta el `pool_timeout` y fallaban. Un pool diminuto reproduce lo que en la
prueba de carga necesitó 15 ingenieros y 5 minutos.
"""

from __future__ import annotations

import asyncio
import os
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.agent.routes import get_analysis_service
from app.agent.service import AnalysisResult
from app.main import app

N = 3


class NeedsASecondConnection:
    """Imita `AnalysisService`: pide otra conexión al pool (replay, lectura) y luego "espera al modelo"."""

    def __init__(self, engine):
        self._engine = engine

    async def analyze(self, user, ncr_id, **kw):
        def other_connection():
            with self._engine.connect() as c:
                c.execute(text("select 1"))

        await asyncio.to_thread(other_connection)
        await asyncio.sleep(0.5)
        return AnalysisResult(trace_id="t")


@pytest.fixture
def tiny_pool(monkeypatch):
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, pool_size=N, max_overflow=0, pool_timeout=3)
    import app.core.db as db
    import app.modules.auth.deps as deps

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(deps, "get_engine", lambda: engine)
    app.dependency_overrides[get_analysis_service] = lambda: NeedsASecondConnection(engine)
    yield engine
    app.dependency_overrides.pop(get_analysis_service, None)
    engine.dispose()


def test_n_simultaneous_analyses_do_not_starve_a_pool_of_n(client, tiny_pool):
    import uuid

    assert client.post("/auth/demo-login", json={"username": "ing.l1"}).status_code == 200
    cookies = dict(client.cookies)
    codes: list[int] = []

    def call():
        with TestClient(app, raise_server_exceptions=False, cookies=cookies) as c:
            codes.append(c.post(f"/ncrs/{uuid.uuid4()}/analyze").status_code)

    threads = [threading.Thread(target=call) for _ in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(codes) == [200] * N, codes
