"""Un .env viejo (sin LLM_LOCAL__*) debe decir qué hacer, no solo 'Field required'."""

from __future__ import annotations

import os

import pytest

from app.agent.llm import config


def test_missing_local_destination_points_to_the_env_fix(monkeypatch, tmp_path):
    for key in list(os.environ):
        if key.startswith("LLM_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)  # sin .env que contamine la prueba
    config.get_llm_settings.cache_clear()
    with pytest.raises(RuntimeError, match="LLM_LOCAL__") as err:
        config.get_llm_settings()
    assert "docker compose up -d api" in str(err.value)
    assert "docker compose restart NO" in str(err.value)
    config.get_llm_settings.cache_clear()
