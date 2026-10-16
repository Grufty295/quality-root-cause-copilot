"""SqlAuditSink contra Postgres real: cadena de hashes, transaccion propia y gateway de punta a punta."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.agent.llm import (
    CallMeta,
    CatalogInspector,
    Destination,
    Message,
    ModelGateway,
    PolicyViolation,
    RouteContext,
    Stage,
)
from app.agent.llm import ConfidentialityLevel as L
from app.agent.llm.audit import SqlAuditSink

from .fakes import PassthroughRedactor, ScriptedLLMClient

MSGS = (Message(role="user", content="Analiza la NCR de [CLIENTE_1], parte [PARTE_3]"),)
INSPECTOR = CatalogInspector({"cliente": ["Autolux Motors"], "parte": ["AX-4471-B"]})


@pytest.fixture
def ids(catalog_and_users, db_engine):
    """Un usuario y una NCR reales: audit_log tiene FK a los dos."""
    with db_engine.begin() as conn:
        user = conn.execute(
            text("SELECT id FROM app_user WHERE username = 'ing.l1'")
        ).scalar_one()
        ncr = conn.execute(
            text(
                "INSERT INTO ncr (code, plant_id, line_id, shift, description, opened_by) "
                "VALUES ('NCR-AUD-' || substr(gen_random_uuid()::text, 1, 8), 'JRZ1', 'L1', 1, 'prueba de auditoria', :u) "
                "RETURNING id"
            ),
            {"u": user},
        ).scalar_one()
    return user, ncr


def build(settings, db_engine, *, local=None, api=None):
    clients = {Destination.LOCAL: local or ScriptedLLMClient("ok")}
    if settings.api is not None:
        clients[Destination.API] = api or ScriptedLLMClient("ok")
    return ModelGateway(
        settings,
        clients,
        SqlAuditSink(db_engine.begin),
        INSPECTOR,
        PassthroughRedactor(),
    )


def meta(ids, **tags):
    return CallMeta(
        user_id=ids[0],
        ncr_id=ids[1],
        trace_id="trace-aud",
        tags={"plant": "JRZ1", **tags},
    )


def ctx(level=L.INTERNO, stage=Stage.D4):
    return RouteContext(stage=stage, input_level=level, input_contains_pii=False)


def rows(db_engine, ncr_id):
    with db_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT stage, detected_level::text AS level, destination::text AS dest, provider, model, "
                    "redaction_applied, tokens_in, tokens_out, trace_id, tags FROM audit_log "
                    "WHERE ncr_id = :n ORDER BY id"
                ),
                {"n": ncr_id},
            )
            .mappings()
            .all()
        )


def chain_problems(db_engine):
    with db_engine.connect() as conn:
        return [
            r.problem
            for r in conn.execute(text("SELECT * FROM audit_verify()"))
            if r.id is not None
        ]


def test_gateway_call_is_written_and_the_chain_stays_intact(settings, db_engine, ids):
    gw = build(settings, db_engine)
    asyncio.run(gw.complete(meta(ids), ctx(L.CONFIDENCIAL), MSGS))
    asyncio.run(gw.complete(meta(ids), ctx(L.INTERNO, Stage.D2), MSGS))

    first, second = rows(db_engine, ids[1])
    assert (first["stage"], first["level"], first["dest"], first["model"]) == (
        "D4",
        "confidencial",
        "local",
        "local-large",
    )
    assert (second["stage"], second["level"], second["dest"], second["model"]) == (
        "D2",
        "interno",
        "api",
        "api-small",
    )
    assert second["redaction_applied"] is True
    assert (first["tokens_in"], first["tokens_out"], first["trace_id"]) == (
        100,
        20,
        "trace-aud",
    )
    assert first["tags"]["plant"] == "JRZ1" and first["tags"]["outcome"] == "ok"
    assert chain_problems(db_engine) == []


def test_a_blocked_leak_is_still_recorded(settings, db_engine, ids):
    api = ScriptedLLMClient("ok")
    gw = build(settings, db_engine, api=api)
    leaky = (
        Message(role="user", content="Reclamo de AUTOLUX motors sobre la ax 4471 b"),
    )
    with pytest.raises(PolicyViolation):
        asyncio.run(gw.complete(meta(ids), ctx(), leaky))

    assert not api.requests
    (row,) = rows(db_engine, ids[1])
    assert row["tags"]["outcome"] == "blocked"
    assert (row["tokens_in"], row["tokens_out"]) == (0, 0)
    # La fila dice que se bloqueo y por que tipo de dato; no guarda el texto.
    dumped = str(dict(row)).lower()
    assert "autolux" not in dumped and "4471" not in dumped


def test_record_survives_the_rollback_of_the_surrounding_transaction(
    settings, db_engine, ids
):
    """El turno puede fallar y revertirse: la llamada al modelo ya ocurrio y sigue auditada."""
    gw = build(settings, db_engine)
    with db_engine.connect() as outer:
        outer_tx = outer.begin()
        outer.execute(text("SELECT 1"))
        asyncio.run(gw.complete(meta(ids), ctx(L.CONFIDENCIAL), MSGS))
        outer_tx.rollback()
    assert len(rows(db_engine, ids[1])) == 1


def test_audit_content_is_metadata_only(settings, db_engine, ids):
    asyncio.run(build(settings, db_engine).complete(meta(ids), ctx(), MSGS))
    (row,) = rows(db_engine, ids[1])
    assert "Analiza" not in str(dict(row)) and "CLIENTE_1" not in str(dict(row))


def test_the_database_itself_refuses_confidential_to_api(db_engine, ids):
    """El CHECK de la tabla es la segunda barrera, por si el codigo falla."""
    with pytest.raises(IntegrityError), db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log (user_id, ncr_id, stage, detected_level, destination, provider, model, "
                "redaction_applied, pseudonymized) "
                "VALUES (:u, :n, 'D4', 'confidencial', 'api', 'x', 'x', false, false)"
            ),
            {"u": ids[0], "n": ids[1]},
        )


def test_the_log_cannot_be_edited_or_deleted(settings, db_engine, ids):
    asyncio.run(build(settings, db_engine).complete(meta(ids), ctx(), MSGS))
    for statement in (
        "UPDATE audit_log SET model = 'otro' WHERE ncr_id = :n",
        "DELETE FROM audit_log WHERE ncr_id = :n",
    ):
        with (
            pytest.raises(Exception, match="solo insercion"),
            db_engine.begin() as conn,
        ):
            conn.execute(text(statement), {"n": ids[1]})
