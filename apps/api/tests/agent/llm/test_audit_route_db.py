"""GET /ncrs/{id}/audit: metadatos de cada llamada, alcance y estado de la cadena."""

from __future__ import annotations

import asyncio

from app.agent.llm import ConfidentialityLevel as L
from app.agent.llm import Stage
from tests.conftest import login

from .test_audit_db import MSGS, build, ctx, ids, meta  # noqa: F401  (ids es fixture)


def test_audit_lists_calls_without_content_and_checks_the_chain(
    client,
    settings,
    db_engine,
    ids,  # noqa: F811
):
    gw = build(settings, db_engine)
    asyncio.run(gw.complete(meta(ids), ctx(L.CONFIDENCIAL), MSGS))
    asyncio.run(gw.complete(meta(ids), ctx(L.INTERNO, Stage.D2), MSGS))

    login(client, "auditor.jrz1")
    r = client.get(f"/ncrs/{ids[1]}/audit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chain_ok"] is True and body["chain_checked"] >= 2
    newest, oldest = body["entries"][:2]
    assert (oldest["stage"], oldest["detected_level"], oldest["destination"]) == (
        "D4",
        "confidencial",
        "local",
    )
    assert (newest["stage"], newest["destination"], newest["redaction_applied"]) == (
        "D2",
        "api",
        True,
    )
    assert oldest["outcome"] == "ok" and len(oldest["hash"]) == 12
    # Nunca contenido: ni el texto del prompt ni el de la respuesta.
    assert "Analiza la NCR" not in r.text and "CLIENTE_1" not in r.text


def test_audit_respects_scope(client, settings, db_engine, ids):  # noqa: F811
    login(client, "ing.l2")  # alcance solo en L2; la NCR es de L1
    assert client.get(f"/ncrs/{ids[1]}/audit").status_code == 404
