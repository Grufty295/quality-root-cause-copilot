"""El gateway redacta antes de enviar a api, restaura lo que vuelve y falla cerrado."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.agent.llm import (
    CallMeta,
    CatalogInspector,
    Destination,
    LLMResult,
    Message,
    ModelGateway,
    ModelTier,
    RedactionFailed,
    RouteContext,
    Stage,
    ToolCall,
    Usage,
)
from app.agent.llm import ConfidentialityLevel as L
from app.confidentiality.classifier import CatalogTerm
from app.confidentiality.levels import ConfidentialityLevel
from app.confidentiality.pseudonyms import InMemoryPseudonymStore
from app.confidentiality.redactor import RuleRedactor

from .fakes import MemoryAuditSink, ScriptedLLMClient

TERMS = [
    CatalogTerm("Autolux Motors", ConfidentialityLevel.INTERNO, "cliente"),
    CatalogTerm("AX-4471-B", ConfidentialityLevel.INTERNO, "parte"),
]
INSPECTOR = CatalogInspector({"cliente": ["Autolux Motors"], "parte": ["AX-4471-B"]})
TEXT = "El operador Juan Pérez reportó rebaba en AX-4471-B de Autolux Motors (nómina 123456)."


def run(coro):
    return asyncio.run(coro)


def meta():
    return CallMeta(user_id=uuid4(), ncr_id=uuid4(), tags={"plant": "JRZ1"})


def ctx(level=L.INTERNO):
    return RouteContext(
        stage=Stage.D4,
        input_level=level,
        input_contains_pii=True,
        fragment_ids=(),
        fragment_levels=(),
    )


def build(settings, api, local=None, audit=None, redactor=None):
    return ModelGateway(
        settings,
        {Destination.LOCAL: local or ScriptedLLMClient("local"), Destination.API: api},
        audit or MemoryAuditSink(),
        INSPECTOR,
        redactor or RuleRedactor(TERMS, InMemoryPseudonymStore()),
    )


def sent(client: ScriptedLLMClient) -> str:
    return json.dumps([m.to_openai() for m in client.requests[0].messages], ensure_ascii=False)


def test_api_payload_has_no_real_values_and_reply_is_restored(settings):
    api = ScriptedLLMClient("Revisar a [PERSONA_1]: la parte [PARTE_1] de [CLIENTE_1].")
    m = meta()
    res = run(build(settings, api).complete(m, ctx(), (Message(role="user", content=TEXT),)))

    payload = sent(api)
    for secret in ("Juan", "Pérez", "AX-4471-B", "Autolux", "123456"):
        assert secret not in payload
    assert "[PERSONA_1]" in payload and "[PARTE_1]" in payload and "[CLIENTE_1]" in payload
    assert res.result.content == "Revisar a Juan Pérez: la parte AX-4471-B de Autolux Motors."


def test_all_messages_share_markers_and_system_prompt_is_redacted_too(settings):
    api = ScriptedLLMClient("ok")
    msgs = (
        Message(role="system", content="Catálogo: Autolux Motors"),
        Message(role="user", content="Autolux Motors, parte AX-4471-B"),
        Message(role="user", content="otra vez AX 4471 B"),
    )
    run(build(settings, api).complete(meta(), ctx(), msgs))
    out = [m.content for m in api.requests[0].messages]
    assert out == ["Catálogo: [CLIENTE_1]", "[CLIENTE_1], parte [PARTE_1]", "otra vez [PARTE_1]"]


def test_audit_records_counts_by_type_never_values(settings):
    audit = MemoryAuditSink()
    run(build(settings, ScriptedLLMClient("ok"), audit=audit).complete(meta(), ctx(), (Message(role="user", content=TEXT),)))
    rec = audit.records[0]
    assert rec.redacted and rec.tags["redactions"] == "cliente=1,nomina=1,parte=1,persona=1"
    dumped = rec.model_dump_json()
    assert "Juan" not in dumped and "Autolux" not in dumped and "123456" not in dumped


def test_local_destination_is_not_redacted(settings):
    """Lo confidencial va al modelo local en claro: la seudonimización es para lo que sale de la planta."""
    local, api = ScriptedLLMClient("ok"), ScriptedLLMClient()
    run(build(settings, api, local=local).complete(meta(), ctx(L.CONFIDENCIAL), (Message(role="user", content=TEXT),)))
    assert not api.requests
    assert "Autolux Motors" in sent(local)


def test_tool_call_arguments_are_redacted_and_restored(settings):
    call = ToolCall(id="c1", name="buscar", arguments={"parte": "[PARTE_1]", "n": 3})
    api = ScriptedLLMClient(
        LLMResult(content=None, tool_calls=(call,), usage=Usage(input_tokens=1, output_tokens=1), model="m", latency_ms=1)
    )
    history = (
        Message(role="user", content="Parte AX-4471-B"),
        Message(
            role="assistant",
            tool_calls=(ToolCall(id="c0", name="buscar", arguments={"parte": "AX-4471-B"}),),
        ),
        Message(role="tool", tool_call_id="c0", content="Autolux Motors"),
    )
    res = run(build(settings, api).complete(meta(), ctx(), history))
    assert "AX-4471-B" not in sent(api) and "Autolux" not in sent(api)
    assert res.result.tool_calls[0].arguments == {"parte": "AX-4471-B", "n": 3}


def test_structured_output_with_restored_value_stays_valid_json(settings):
    class Out(BaseModel):
        responsable: str

    store = InMemoryPseudonymStore()
    red = RuleRedactor(TERMS, store)
    m = meta()
    api = ScriptedLLMClient('{"responsable": "[PERSONA_1]"}')
    gw = build(settings, api, redactor=red)
    store.assign(m.ncr_id, [("persona", 'Ana "La Jefa" Ruiz')])
    res = run(gw.complete_structured(m, ctx(), (Message(role="user", content="quién"),), Out))
    assert res.output.value.responsable == 'Ana "La Jefa" Ruiz'


def test_redactor_failure_blocks_the_call_and_is_audited(settings):
    class Broken:
        def redact(self, ncr_id, texts, *, only=None):
            raise RuntimeError("Juan Pérez no debe aparecer en el error")

        def restore(self, ncr_id, texts, *, json_escaped=False):
            return list(texts)

    api, audit = ScriptedLLMClient("no debe llamarse"), MemoryAuditSink()
    gw = build(settings, api, audit=audit, redactor=Broken())
    with pytest.raises(RedactionFailed) as exc:
        run(gw.complete(meta(), ctx(), (Message(role="user", content=TEXT),)))
    assert not api.requests
    assert "Juan" not in str(exc.value)
    assert audit.records[0].tags["outcome"] == "blocked"
    assert "Juan" not in audit.records[0].model_dump_json()


def test_local_destination_pseudonymizes_pii_but_keeps_customer_data(settings):
    """must_pseudonymize aplica también al modelo local: personas, nómina y correos, no clientes ni partes."""
    local, api = ScriptedLLMClient("Revisar a [PERSONA_1]"), ScriptedLLMClient()
    c = RouteContext(
        stage=Stage.D4, input_level=L.CONFIDENCIAL, input_contains_pii=True, fragment_ids=(), fragment_levels=()
    )
    audit = MemoryAuditSink()
    res = run(build(settings, api, local=local, audit=audit).complete(meta(), c, (Message(role="user", content=TEXT),)))
    payload = sent(local)
    assert "Juan" not in payload and "123456" not in payload
    assert "AX-4471-B" in payload and "Autolux Motors" in payload  # lo confidencial se queda en la planta
    assert res.result.content == "Revisar a Juan Pérez"
    assert audit.records[0].pseudonymized and audit.records[0].tags["redactions"] == "nomina=1,persona=1"


def test_local_with_pii_and_no_redactor_fails_closed(settings_local_only):
    c = RouteContext(
        stage=Stage.D2, input_level=L.CONFIDENCIAL, input_contains_pii=True, fragment_ids=(), fragment_levels=()
    )
    local, audit = ScriptedLLMClient("no debe llamarse"), MemoryAuditSink()
    gw = ModelGateway(settings_local_only, {Destination.LOCAL: local}, audit, None)
    with pytest.raises(RedactionFailed):
        run(gw.complete(meta(), c, (Message(role="user", content=TEXT),)))
    assert not local.requests


def test_ctx_tier_overrides_stage_tier_but_not_destination(settings):
    c = RouteContext(
        stage=Stage.D4,
        input_level=L.INTERNO,
        input_contains_pii=False,
        fragment_ids=(),
        fragment_levels=(),
        tier=ModelTier.SMALL,
    )
    d = build(settings, ScriptedLLMClient("x")).route(c)
    assert d.model == "api-small" and d.destination is Destination.API
