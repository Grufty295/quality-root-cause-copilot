from __future__ import annotations

import math

from app.evalkit import metrics as m

G = {"a": 2, "b": 1, "c": 1}


def test_recall_counts_anchors_not_fragments():
    # a sale dos veces (dos fragmentos de la misma sección): cuenta una vez
    assert m.recall_at_k(["a", "x", "a", "b"], G, 4) == 2 / 3
    assert m.recall_at_k(["x", "y"], G, 2) == 0.0


def test_recall_and_hit_are_none_without_relevant_items():
    assert m.recall_at_k(["a"], {}, 5) is None
    assert m.hit_at_k(["a"], {"a": 1}, 5) is None  # solo hay útiles, ninguna esencial
    assert m.reciprocal_rank(["a"], {"a": 1}) is None
    assert m.ndcg_at_k(["a"], {}, 5) is None


def test_hit_requires_an_essential_anchor():
    assert m.hit_at_k(["b", "a"], G, 1) == 0.0
    assert m.hit_at_k(["b", "a"], G, 2) == 1.0


def test_reciprocal_rank_uses_first_essential():
    assert m.reciprocal_rank(["x", "b", "a"], G) == 1 / 3
    assert m.reciprocal_rank(["x", "y"], G) == 0.0


def test_ndcg_is_one_for_ideal_order_and_lower_otherwise():
    assert math.isclose(m.ndcg_at_k(["a", "b", "c"], G, 3) or 0, 1.0)
    worse = m.ndcg_at_k(["b", "c", "a"], G, 3)
    assert worse is not None and worse < 1.0
    # un duplicado no suma dos veces
    assert m.ndcg_at_k(["a", "a", "a"], G, 3) == m.ndcg_at_k(["a", "x", "x"], G, 3)


def test_precision_measures_noise_in_the_prompt():
    assert m.precision_at_k(["a", "x", "y", "b"], G, 4) == 0.5
    assert m.precision_at_k([], G, 4) is None


def test_mean_skips_none():
    assert m.mean([1.0, None, 0.0]) == 0.5
    assert m.mean([None]) is None
