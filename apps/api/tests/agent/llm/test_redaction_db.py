"""SqlPseudonymStore y el gateway con redactor, contra Postgres real."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from app.agent.llm import (
    CallMeta,
    CatalogInspector,
    Destination,
    Message,
    ModelGateway,
    RouteContext,
    Stage,
)
from app.agent.llm import ConfidentialityLevel as L
from app.agent.llm.audit import SqlAuditSink
from app.confidentiality.classifier import CatalogTerm
from app.confidentiality.levels import ConfidentialityLevel
from app.confidentiality.pseudonyms import SqlPseudonymStore
from app.confidentiality.redactor import RuleRedactor

from .fakes import ScriptedLLMClient


@pytest.fixture
def ids(catalog_and_users, db_engine):
    with db_engine.begin() as conn:
        user = conn.execute(text("SELECT id FROM app_user WHERE username = 'ing.l1'")).scalar_one()
        ncr = conn.execute(
            text(
                "INSERT INTO ncr (code, plant_id, line_id, shift, description, opened_by) "
                "VALUES ('NCR-PSE-' || substr(gen_random_uuid()::text, 1, 8), 'JRZ1', 'L1', 1, 'prueba', :u) "
                "RETURNING id"
            ),
            {"u": user},
        ).scalar_one()
    return user, ncr


@pytest.fixture
def store(db_engine):
    return SqlPseudonymStore(db_engine.begin)


def test_assign_is_idempotent_and_numbers_per_type(store, ids):
    _, ncr = ids
    first = store.assign(ncr, [("persona", "Ana Ruiz"), ("persona", "Luis Soto"), ("parte", "AX-4471-B")])
    again = store.assign(ncr, [("persona", "Luis Soto"), ("persona", "Pedro Díaz")])
    assert first == {
        ("persona", "Ana Ruiz"): "[PERSONA_1]",
        ("persona", "Luis Soto"): "[PERSONA_2]",
        ("parte", "AX-4471-B"): "[PARTE_1]",
    }
    assert again == {("persona", "Luis Soto"): "[PERSONA_2]", ("persona", "Pedro Díaz"): "[PERSONA_3]"}
    assert store.resolve(ncr, ["[PERSONA_2]", "[PARTE_1]", "[PARTE_7]"]) == {
        "[PERSONA_2]": "Luis Soto",
        "[PARTE_1]": "AX-4471-B",
    }


def test_concurrent_turns_never_repeat_a_marker(store, ids):
    _, ncr = ids
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda i: store.assign(ncr, [("persona", f"Persona Numero{i}")]), range(8)))
    markers = [m for r in results for m in r.values()]
    assert len(set(markers)) == 8


def test_expired_rows_are_ignored(store, ids, db_engine):
    _, ncr = ids
    store.assign(ncr, [("persona", "Ana Ruiz")])
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE pseudonym_map SET expires_at = now() - interval '1 day' WHERE ncr_id = :n"), {"n": ncr})
    assert store.mapping(ncr) == []
    assert store.resolve(ncr, ["[PERSONA_1]"]) == {}


def test_reuse_extends_retention(store, ids, db_engine):
    _, ncr = ids
    store.assign(ncr, [("persona", "Ana Ruiz")])
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE pseudonym_map SET expires_at = now() + interval '1 day' WHERE ncr_id = :n"), {"n": ncr})
    store.assign(ncr, [("persona", "Ana Ruiz")])
    with db_engine.connect() as conn:
        days = conn.execute(
            text("SELECT extract(day FROM expires_at - now()) FROM pseudonym_map WHERE ncr_id = :n"), {"n": ncr}
        ).scalar_one()
    assert days >= 89


def test_end_to_end_gateway_with_sql_store_and_audit(settings, store, ids, db_engine):
    user, ncr = ids
    terms = [CatalogTerm("Autolux Motors", ConfidentialityLevel.INTERNO, "cliente")]
    api = ScriptedLLMClient("Avisar a [PERSONA_1] sobre [CLIENTE_1]")
    gw = ModelGateway(
        settings,
        {Destination.LOCAL: ScriptedLLMClient("x"), Destination.API: api},
        SqlAuditSink(db_engine.begin),
        CatalogInspector({"cliente": ["Autolux Motors"]}),
        RuleRedactor(terms, store),
    )
    ctx = RouteContext(
        stage=Stage.D4, input_level=L.INTERNO, input_contains_pii=True, fragment_ids=(), fragment_levels=()
    )
    res = asyncio.run(
        gw.complete(
            CallMeta(user_id=user, ncr_id=ncr),
            ctx,
            (Message(role="user", content="operador Ana Ruiz y Autolux Motors"),),
        )
    )
    assert res.result.content == "Avisar a Ana Ruiz sobre Autolux Motors"
    assert api.requests[0].messages[0].content == "operador [PERSONA_1] y [CLIENTE_1]"
    with db_engine.connect() as conn:
        tags = conn.execute(text("SELECT tags FROM audit_log WHERE ncr_id = :n"), {"n": ncr}).scalar_one()
        audit_dump = str(conn.execute(text("SELECT row_to_json(a) FROM audit_log a WHERE ncr_id = :n"), {"n": ncr}).all())
    assert tags["redactions"] == "cliente=1,persona=1"
    assert "Ana" not in audit_dump and "Autolux" not in audit_dump
