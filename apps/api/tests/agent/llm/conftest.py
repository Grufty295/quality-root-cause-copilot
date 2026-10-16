from __future__ import annotations

from decimal import Decimal

import pytest

from app.agent.llm import DestinationSettings, LLMSettings


def _local(**overrides: object) -> DestinationSettings:
    data: dict[str, object] = {
        "base_url": "http://ollama:11434/v1",
        "model_small": "local-small",
        "model_large": "local-large",
        "provider_label": "ollama-planta",
        "max_retries": 2,
    }
    data.update(overrides)
    return DestinationSettings.model_validate(data)


def _api(**overrides: object) -> DestinationSettings:
    data: dict[str, object] = {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-test",
        "model_small": "api-small",
        "model_large": "api-large",
        "provider_label": "openrouter",
        "price_in_per_mtok": Decimal("1.00"),
        "price_out_per_mtok": Decimal("4.00"),
        "max_retries": 2,
    }
    data.update(overrides)
    return DestinationSettings.model_validate(data)


@pytest.fixture
def make_local():
    return _local


@pytest.fixture
def make_api():
    return _api


@pytest.fixture
def settings() -> LLMSettings:
    return LLMSettings(local=_local(), api=_api(), _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def settings_local_only() -> LLMSettings:
    return LLMSettings(local=_local(), api=None, _env_file=None)  # type: ignore[call-arg]
