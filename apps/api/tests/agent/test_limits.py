"""Tope de análisis simultáneos: reglas puras, sin base."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.agent.limits import AnalysisLimiter
from app.core.errors import TooManyRequests


def test_a_user_cannot_exceed_their_own_cap_and_the_slot_is_freed_afterwards():
    lim = AnalysisLimiter(max_total=10, max_per_user=2, retry_after_s=7)
    u = uuid4()
    with lim.slot(u), lim.slot(u):
        with pytest.raises(TooManyRequests) as err:
            with lim.slot(u):
                pass
        assert err.value.status_code == 429 and err.value.retry_after_s == 7
        assert lim.in_flight == 2
    assert lim.in_flight == 0
    with lim.slot(u):  # liberado
        assert lim.in_flight == 1


def test_the_global_cap_rejects_other_users_too():
    lim = AnalysisLimiter(max_total=2, max_per_user=2)
    a, b, c = uuid4(), uuid4(), uuid4()
    with lim.slot(a), lim.slot(b):
        with pytest.raises(TooManyRequests, match="ocupado"):
            with lim.slot(c):
                pass
    assert lim.in_flight == 0


def test_a_failed_analysis_still_releases_its_slot():
    lim = AnalysisLimiter(max_total=1, max_per_user=1)
    u = uuid4()
    with pytest.raises(RuntimeError):
        with lim.slot(u):
            raise RuntimeError("el modelo falló")
    assert lim.in_flight == 0
    with lim.slot(u):
        pass


def test_zero_means_unlimited():
    lim = AnalysisLimiter(max_total=0, max_per_user=0)
    u = uuid4()
    slots = [lim.slot(u) for _ in range(50)]
    for s in slots:
        s.__enter__()
    assert lim.in_flight == 50
    for s in slots:
        s.__exit__(None, None, None)
    assert lim.in_flight == 0


def test_defaults_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("ANALYZE_MAX_CONCURRENT", "3")
    monkeypatch.setenv("ANALYZE_MAX_PER_USER", "1")
    monkeypatch.setenv("ANALYZE_RETRY_AFTER_S", "45")
    lim = AnalysisLimiter.from_env()
    assert (lim.max_total, lim.max_per_user, lim.retry_after_s) == (3, 1, 45)
    monkeypatch.delenv("ANALYZE_MAX_CONCURRENT")
    assert AnalysisLimiter.from_env().max_total == 8
