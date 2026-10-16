"""Gateway, salida estructurada e inspector, con dobles de cliente y auditoría."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel, Field

from app.agent.llm import (
    CallMeta,
    CatalogInspector,
    Destination,
    LLMResult,
    LLMTransportError,
    Message,
    ModelGateway,
    PolicyViolation,
    RouteContext,
    Stage,
    StructuredOutputError,
    Usage,
)
from app.agent.llm import (
    ConfidentialityLevel as L,
)
from app.agent.llm.structured import parse_structured

from .fakes import MemoryAuditSink, PassthroughRedactor, ScriptedLLMClient


class Causa(BaseModel):
    codigo: str = Field(pattern=r"^C-\d{2}$")
    citas: list[str] = Field(min_length=1)


class D4(BaseModel):
    causas: list[Causa] = Field(min_length=1, max_length=3)


VALID = '{"causas": [{"codigo": "C-01", "citas": ["frag-1"]}]}'
MSGS = (Message(role="user", content="Analiza la NCR de [CLIENTE_1], parte [PARTE_3]"),)
META = CallMeta(
    user_id=uuid4(),
    ncr_id=uuid4(),
    trace_id="t-1",
    tags={"plant": "JRZ1", "line": "L2"},
)
INSPECTOR = CatalogInspector({"cliente": ["Autolux Motors"], "parte": ["AX-4471-B"]})


def run(coro):
    return asyncio.run(coro)


def ctx(level=L.INTERNO, stage=Stage.D4, n_frag=2) -> RouteContext:
    return RouteContext(
        stage=stage,
        input_level=level,
        input_contains_pii=False,
        fragment_ids=tuple(uuid4() for _ in range(n_frag)),
        fragment_levels=(L.PUBLICO,) * n_frag,
    )


def gateway(
    settings,
    local=None,
    api=None,
    audit=None,
    inspector=INSPECTOR,
    redactor=PassthroughRedactor(),
):
    clients = {Destination.LOCAL: local or ScriptedLLMClient()}
    if settings.api is not None:
        clients[Destination.API] = api or ScriptedLLMClient()
    return ModelGateway(
        settings, clients, audit or MemoryAuditSink(), inspector, redactor
    )


# ------------------------------------------------------------------ construcción


def test_api_requires_inspector(settings):
    with pytest.raises(ValueError, match="inspector"):
        gateway(settings, inspector=None)


def test_api_requires_redactor(settings):
    with pytest.raises(ValueError, match="redactor"):
        gateway(settings, redactor=None)


def test_local_only_does_not_need_inspector(settings_local_only):
    gateway(settings_local_only, inspector=None)


# ------------------------------------------------------------------ ruteo y auditoría


def test_confidential_goes_to_local_client_and_is_audited(settings):
    local, api, audit = ScriptedLLMClient("ok"), ScriptedLLMClient(), MemoryAuditSink()
    c = ctx(level=L.CONFIDENCIAL)
    res = run(gateway(settings, local, api, audit).complete(META, c, MSGS))
    assert res.decision.destination is Destination.LOCAL
    assert len(local.requests) == 1 and not api.requests
    assert local.requests[0].model == "local-large"
    rec = audit.records[0]
    assert rec.destination is Destination.LOCAL and rec.detected_level is L.CONFIDENCIAL
    assert rec.fragment_ids == c.fragment_ids
    assert rec.tags["outcome"] == "ok" and rec.tags["plant"] == "JRZ1"
    assert rec.cost_usd == Decimal("0")


def test_internal_goes_to_api_with_cost(settings):
    api, audit = ScriptedLLMClient("ok"), MemoryAuditSink()
    run(
        gateway(settings, api=api, audit=audit).complete(
            META, ctx(stage=Stage.D2), MSGS
        )
    )
    rec = audit.records[0]
    assert (
        rec.destination is Destination.API and rec.model == "api-small" and rec.redacted
    )
    # 100 tokens * $1/M + 20 * $4/M
    assert rec.cost_usd == Decimal("0.00018")


def test_audit_record_never_contains_message_content(settings):
    audit = MemoryAuditSink()
    run(
        gateway(settings, api=ScriptedLLMClient("ok"), audit=audit).complete(
            META, ctx(), MSGS
        )
    )
    dumped = audit.records[0].model_dump_json()
    assert "Analiza" not in dumped and "CLIENTE_1" not in dumped


def test_leak_blocks_call_and_is_audited_as_blocked(settings):
    api, audit = ScriptedLLMClient("ok"), MemoryAuditSink()
    leaky = (
        Message(role="user", content="Reclamo de AUTOLUX motors sobre la ax 4471 b"),
    )
    with pytest.raises(PolicyViolation):
        run(gateway(settings, api=api, audit=audit).complete(META, ctx(), leaky))
    assert not api.requests
    rec = audit.records[0]
    assert rec.tags["outcome"] == "blocked"
    dumped = rec.model_dump_json().lower()
    assert "4471" not in dumped and "autolux" not in dumped  # nunca el valor
    assert "cliente" in rec.tags["error"] and "parte" in rec.tags["error"]


def test_local_destination_is_not_inspected(settings):
    """El inspector protege la salida a internet; hacia el modelo local el dato puede ir."""
    local = ScriptedLLMClient("ok")
    leaky = (Message(role="user", content="Reclamo de Autolux Motors"),)
    run(gateway(settings, local=local).complete(META, ctx(level=L.CONFIDENCIAL), leaky))
    assert len(local.requests) == 1


def test_transport_error_is_audited_and_reraised(settings):
    audit = MemoryAuditSink()
    api = ScriptedLLMClient(LLMTransportError("x", status_code=503, attempts=3))
    with pytest.raises(LLMTransportError):
        run(gateway(settings, api=api, audit=audit).complete(META, ctx(), MSGS))
    assert audit.records[0].tags == audit.records[0].tags | {
        "outcome": "error",
        "error": "LLMTransportError: HTTP 503",
    }


def test_result_not_returned_if_audit_fails(settings):
    with pytest.raises(RuntimeError, match="audit_log"):
        run(
            gateway(
                settings, api=ScriptedLLMClient("ok"), audit=MemoryAuditSink(fail=True)
            ).complete(META, ctx(), MSGS)
        )


# ------------------------------------------------------------------ salida estructurada


def test_structured_first_try(settings):
    api, audit = ScriptedLLMClient(VALID), MemoryAuditSink()
    out = run(
        gateway(settings, api=api, audit=audit).complete_structured(
            META, ctx(), MSGS, D4
        )
    ).output
    assert out.value.causas[0].codigo == "C-01" and out.attempts == 1
    assert api.requests[0].json_mode
    assert (
        api.requests[0].messages[0].role == "system"
        and "JSON Schema" in api.requests[0].messages[0].content
    )


def test_structured_retries_with_validation_error_and_audits_each_attempt(settings):
    api, audit = (
        ScriptedLLMClient(
            '{"causas": [{"codigo": "X1", "citas": []}]}', f"```json\n{VALID}\n```"
        ),
        MemoryAuditSink(),
    )
    out = run(
        gateway(settings, api=api, audit=audit).complete_structured(
            META, ctx(), MSGS, D4
        )
    ).output
    assert out.attempts == 2
    assert out.usage.input_tokens == 200
    assert len(audit.records) == 2
    feedback = api.requests[1].messages[-1].content
    assert "causas.0.codigo" in feedback and "causas.0.citas" in feedback


def test_structured_gives_up(settings):
    api = ScriptedLLMClient("nope", "{}", '{"causas": []}')
    with pytest.raises(StructuredOutputError) as exc:
        run(
            gateway(settings, api=api).complete_structured(
                META, ctx(), MSGS, D4, max_attempts=3
            )
        )
    assert exc.value.attempts == 3


def test_structured_retry_feedback_is_also_inspected(settings):
    """Si el modelo devuelve un identificador real, el reintento hacia la api se bloquea."""
    api = ScriptedLLMClient("La causa es de Autolux Motors")
    with pytest.raises(PolicyViolation):
        run(gateway(settings, api=api).complete_structured(META, ctx(), MSGS, D4))
    assert len(api.requests) == 1


def test_parse_structured_rejects_empty():
    with pytest.raises(ValueError):
        parse_structured("   ", D4)


# ------------------------------------------------------------------ inspector


@pytest.mark.parametrize(
    "text", ["AX-4471-B", "ax 4471 b", "Ax4471B", "parte:AX—4471—B"]
)
def test_inspector_normalizes_separators_and_case(text):
    assert INSPECTOR.findings([Message(role="user", content=text)]) == ["parte"]


def test_inspector_checks_tool_arguments():
    from app.agent.llm import ToolCall

    msg = Message(
        role="assistant",
        tool_calls=(ToolCall(id="1", name="t", arguments={"part": "AX-4471-B"}),),
    )
    assert INSPECTOR.findings([msg]) == ["parte"]


def test_inspector_ignores_placeholders_and_short_terms():
    insp = CatalogInspector({"cliente": ["AB"]})
    assert insp.findings([Message(role="user", content="[CLIENTE_1] y AB")]) == []
    assert INSPECTOR.findings(MSGS) == []


def test_reasoning_tokens_and_reported_cost_go_to_audit_tags(settings):
    reply = LLMResult(
        content="ok",
        usage=Usage(
            input_tokens=10,
            output_tokens=50,
            reasoning_tokens=30,
            reported_cost_usd=Decimal("0.0002"),
        ),
        model="local-large",
        latency_ms=5,
    )
    audit = MemoryAuditSink()
    run(
        gateway(settings, ScriptedLLMClient(reply), audit=audit).complete(
            META, ctx(level=L.CONFIDENCIAL), MSGS
        )
    )
    tags = audit.records[0].tags
    assert tags["reasoning_tokens"] == "30" and tags["reported_cost_usd"] == "0.0002"


def test_finish_reason_goes_to_audit_tags(settings):
    reply = LLMResult(
        content='{"a": ',
        usage=Usage(input_tokens=10, output_tokens=8192),
        model="local-large",
        latency_ms=5,
        finish_reason="length",
    )
    audit = MemoryAuditSink()
    run(
        gateway(settings, ScriptedLLMClient(reply), audit=audit).complete(
            META, ctx(level=L.CONFIDENCIAL), MSGS
        )
    )
    assert audit.records[0].tags["finish_reason"] == "length"
