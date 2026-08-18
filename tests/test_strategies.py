"""Testes de lógica pura pro routing/strategies.py — sem LLM, sem rede."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vincent.routing import strategies


def test_priority_no_reorder():
    models = ["a", "b", "c"]
    assert strategies.strategy_priority(models) == ["a", "b", "c"]


def test_round_robin_rotates_each_call():
    models = ["a", "b", "c"]
    key = "test_rr_1"
    assert strategies.strategy_round_robin(models, key=key) == ["a", "b", "c"]
    assert strategies.strategy_round_robin(models, key=key) == ["b", "c", "a"]
    assert strategies.strategy_round_robin(models, key=key) == ["c", "a", "b"]
    assert strategies.strategy_round_robin(models, key=key) == ["a", "b", "c"]


def test_cost_optimized_orders_free_then_local_then_pro():
    catalog = [
        {"id": "pro-model", "is_free": False, "is_local": False},
        {"id": "free-model", "is_free": True, "is_local": False},
        {"id": "local-model", "is_free": False, "is_local": True},
    ]
    models = ["pro-model", "free-model", "local-model"]
    result = strategies.strategy_cost_optimized(models, model_catalog=catalog)
    assert result == ["free-model", "local-model", "pro-model"]


def test_cost_optimized_without_catalog_is_noop():
    models = ["a", "b"]
    assert strategies.strategy_cost_optimized(models, model_catalog=None) == ["a", "b"]


def test_lkgp_sticks_to_last_success():
    key = "test_lkgp_1"
    models = ["a", "b", "c"]
    assert strategies.strategy_lkgp(models, key=key) == ["a", "b", "c"]  # sem histórico

    strategies.record_success("c", key=key)
    assert strategies.strategy_lkgp(models, key=key) == ["c", "a", "b"]


def test_lkgp_ignores_stale_success_not_in_cascade():
    key = "test_lkgp_2"
    strategies.record_success("removed-model", key=key)
    models = ["a", "b"]
    assert strategies.strategy_lkgp(models, key=key) == ["a", "b"]


def test_apply_strategy_dispatch():
    models = ["a", "b"]
    assert strategies.apply_strategy("priority", models) == ["a", "b"]
    assert strategies.apply_strategy("unknown_name", models) == ["a", "b"]  # cai pra priority
