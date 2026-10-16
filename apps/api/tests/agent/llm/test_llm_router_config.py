from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agent.llm import (
    ConfidentialityLevel as L,
)
from app.agent.llm import (
    ConfidentialityRouter,
    Destination,
    LLMSettings,
    ModelTier,
    RouteContext,
    RouteDecision,
    Stage,
)
from app.agent.llm.config import is_private_endpoint


def ctx(stage=Stage.D4, input_level=L.INTERNO, frag=(), pii=False, frag_pii=False) -> RouteContext:
    return RouteContext(
        stage=stage,
        input_level=input_level,
        input_contains_pii=pii,
        fragment_ids=tuple(uuid4() for _ in frag),
        fragment_levels=tuple(frag),
        fragment_contains_pii=frag_pii,
    )


# ------------------------------------------------------------------ nivel del contexto


def test_highest_level_wins():
    assert ctx(input_level=L.PUBLICO, frag=(L.INTERNO, L.PUBLICO)).level is L.INTERNO
    assert ctx(input_level=L.PUBLICO, frag=(L.CONFIDENCIAL,)).level is L.CONFIDENCIAL


def test_unclassified_input_is_confidential():
    assert ctx(input_level=None, frag=(L.PUBLICO,)).level is L.CONFIDENCIAL


def test_empty_context_is_confidential():
    assert L.highest([]) is L.CONFIDENCIAL


def test_ids_and_levels_must_align():
    with pytest.raises(ValidationError):
        RouteContext(
            stage=Stage.D2, input_level=L.PUBLICO, input_contains_pii=False, fragment_ids=(uuid4(),), fragment_levels=()
        )


# ------------------------------------------------------------------ decisiones


def test_confidential_fragment_forces_local(settings):
    d = ConfidentialityRouter(settings).decide(ctx(input_level=L.PUBLICO, frag=(L.CONFIDENCIAL,)))
    assert d.destination is Destination.LOCAL
    assert d.model == "local-large"
    assert not d.must_redact


def test_unclassified_goes_local_with_reason(settings):
    d = ConfidentialityRouter(settings).decide(ctx(input_level=None))
    assert d.destination is Destination.LOCAL
    assert "sin clasificar" in d.reason


def test_internal_goes_api_with_redaction(settings):
    d = ConfidentialityRouter(settings).decide(ctx(stage=Stage.D2, input_level=L.INTERNO))
    assert d.destination is Destination.API
    assert d.must_redact
    assert d.tier is ModelTier.SMALL
    assert d.model == "api-small"


def test_without_api_everything_is_local(settings_local_only):
    d = ConfidentialityRouter(settings_local_only).decide(ctx(input_level=L.PUBLICO))
    assert d.destination is Destination.LOCAL


def test_pii_pseudonymized_on_any_destination(settings):
    router = ConfidentialityRouter(settings)
    assert router.decide(ctx(input_level=L.CONFIDENCIAL, frag_pii=True)).must_pseudonymize
    assert router.decide(ctx(input_level=L.PUBLICO, pii=True)).must_pseudonymize
    assert not router.decide(ctx(input_level=L.PUBLICO)).must_pseudonymize


@pytest.mark.parametrize(
    "stage,tier", [(Stage.D2, ModelTier.SMALL), (Stage.D3, ModelTier.SMALL), (Stage.D4, ModelTier.LARGE)]
)
def test_stage_selects_tier(settings, stage, tier):
    assert ConfidentialityRouter(settings).decide(ctx(stage=stage)).tier is tier


def test_decision_cannot_send_confidential_to_api():
    with pytest.raises(ValidationError, match="confidencial hacia destino api"):
        RouteDecision(
            destination=Destination.API,
            level=L.CONFIDENCIAL,
            tier=ModelTier.LARGE,
            model="x",
            simulated=False,
            must_redact=True,
            must_pseudonymize=False,
            reason="",
        )


# ------------------------------------------------------------------ guard de arranque


@pytest.mark.parametrize(
    "url,private",
    [
        ("http://ollama:11434/v1", True),
        ("http://localhost:8000/v1", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://10.20.0.5/v1", True),
        ("http://192.168.1.10/v1", True),
        ("http://vllm.planta.internal/v1", True),
        ("https://openrouter.ai/api/v1", False),
        ("http://8.8.8.8/v1", False),
    ],
)
def test_private_endpoint_detection(url, private):
    assert is_private_endpoint(url) is private


def test_public_local_endpoint_rejected(make_local):
    with pytest.raises(ValidationError, match="host público"):
        LLMSettings(local=make_local(base_url="https://openrouter.ai/api/v1"), _env_file=None)


def test_simulated_local_needs_explicit_switch(make_local):
    sim = make_local(base_url="https://openrouter.ai/api/v1", simulated=True)
    with pytest.raises(ValidationError, match="ALLOW_SIMULATED_LOCAL"):
        LLMSettings(local=sim, _env_file=None)
    s = LLMSettings(local=sim, allow_simulated_local=True, _env_file=None)
    assert s.local.simulated


def test_api_requires_key(make_api, make_local):
    with pytest.raises(ValidationError, match="API_KEY"):
        LLMSettings(local=make_local(), api=make_api(api_key=None), _env_file=None)


def test_api_cannot_be_simulated(make_api, make_local):
    with pytest.raises(ValidationError, match="solo aplica al destino local"):
        LLMSettings(local=make_local(), api=make_api(simulated=True), _env_file=None)


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_LOCAL__BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_LOCAL__API_KEY", "k")
    monkeypatch.setenv("LLM_LOCAL__MODEL_SMALL", "s")
    monkeypatch.setenv("LLM_LOCAL__MODEL_LARGE", "l")
    monkeypatch.setenv("LLM_LOCAL__PROVIDER_LABEL", "openrouter-sim-local")
    monkeypatch.setenv("LLM_LOCAL__SIMULATED", "true")
    monkeypatch.setenv("LLM_LOCAL__EXTRA_BODY", '{"provider": {"data_collection": "deny"}}')
    monkeypatch.setenv("LLM_ALLOW_SIMULATED_LOCAL", "true")
    s = LLMSettings(_env_file=None)  # type: ignore[call-arg]
    assert s.local.simulated and s.api is None
    assert s.local.extra_body == {"provider": {"data_collection": "deny"}}


def test_cost(make_api):
    from decimal import Decimal

    assert make_api().cost_usd(1_000_000, 250_000) == Decimal("2.00")
