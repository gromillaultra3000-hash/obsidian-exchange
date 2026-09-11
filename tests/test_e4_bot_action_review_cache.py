"""Approval invariants without Telegram, persistence, or provider calls."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "bot_action_review", Path(__file__).resolve().parents[1] / "bot/action_review.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ActionReviewCache = module.ActionReviewCache


def test_single_use_and_restart():
    cache = ActionReviewCache()
    fields = {"action": "buy", "amount": "10", "recipient": "wallet"}
    token = cache.issue("tg:1", fields)
    with pytest.raises(ValueError):
        ActionReviewCache().consume(token, "tg:1", fields)
    assert cache.consume(token, "tg:1", fields)
    with pytest.raises(ValueError):
        cache.consume(token, "tg:1", fields)


def test_exact_deep_snapshot_owner_and_canonical_key_order():
    cache = ActionReviewCache()
    fields = {"amount": 10, "nested": {"recipients": ["one"]}, "extra": "shown"}
    token = cache.issue("tg:1", fields)
    with pytest.raises(ValueError):
        cache.consume(token, "tg:2", fields)
    fields["nested"]["recipients"].append("two")
    with pytest.raises(ValueError):
        cache.consume(token, "tg:1", fields)
    fields["nested"]["recipients"].pop()
    for changed in (dict(fields, amount="10"), dict(fields, extra="changed"), {"amount": 10}):
        with pytest.raises(ValueError):
            cache.consume(token, "tg:1", changed)
    assert cache.consume(token, "tg:1", dict(reversed(list(fields.items()))))


def test_expiry_boundary_and_capacity_cleanup():
    now = [0]
    cache = ActionReviewCache(max_entries=2, clock=lambda: now[0])
    first = cache.issue("u", {})
    second = cache.issue("u", {})
    assert first != second
    with pytest.raises(ValueError):
        cache.issue("u", {})
    now[0] = 120
    with pytest.raises(ValueError):
        cache.consume(first, "u", {})
    assert cache.consume(cache.issue("u", {}), "u", {})
    assert not cache._entries


@pytest.mark.parametrize("fields", [
    {"value": float("nan")}, {"value": float("inf")},
    {"value": "x" * 8192}, {1: "ambiguous"}, {"value": (1, 2)},
    {"value": object()}, {"value": "\ud800"},
])
def test_invalid_snapshot(fields):
    with pytest.raises(ValueError):
        ActionReviewCache().issue("u", fields)


def test_concurrent_redemption_has_one_winner():
    cache = ActionReviewCache()
    token = cache.issue("u", {"action": "sell"})
    def redeem(_):
        try:
            return cache.consume(token, "u", {"action": "sell"})
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(redeem, range(32))) == 1


def test_cyclic_snapshot_and_invalid_limits():
    fields = {}
    fields["self"] = fields
    with pytest.raises(ValueError):
        ActionReviewCache().issue("u", fields)
    for limits in ({"ttl": 121}, {"ttl": 0}, {"max_entries": 257}, {"max_entries": 0}):
        with pytest.raises(ValueError):
            ActionReviewCache(**limits)
