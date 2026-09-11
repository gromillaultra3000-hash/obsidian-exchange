import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest


spec = importlib.util.spec_from_file_location(
    "website_swap_review", Path(__file__).resolve().parents[1] / "relay-fastapi/swap_review.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SwapReviewCache = module.SwapReviewCache

FIELDS = {"coin_from": "BTC", "coin_to": "LTC", "amount": 1.0, "address": "recipient"}
QUOTE = {"estimated_receive": "100", "rate": "100", "min_amount": "0.1",
         "max_amount": "2", "withdraw_fee": "0.01"}
OWNER = "user:3:session:one"


@pytest.mark.parametrize("key", ["estimated_receive", "rate"])
@pytest.mark.parametrize("value", [None, "nan", "Infinity", "-Infinity", "oops", "", 0, -1, True])
def test_required_quote_numbers(key, value):
    with pytest.raises(ValueError):
        SwapReviewCache().issue(OWNER, FIELDS, {**QUOTE, key: value})


@pytest.mark.parametrize("key", ["min_amount", "max_amount", "withdraw_fee"])
@pytest.mark.parametrize("value", ["nan", "Infinity", "oops", -1, True])
def test_optional_quote_numbers(key, value):
    with pytest.raises(ValueError):
        SwapReviewCache().issue(OWNER, FIELDS, {**QUOTE, key: value})


@pytest.mark.parametrize("amount", ["0.01", "3", "nan", "Infinity", 0, -1])
def test_amount_bounds(amount):
    with pytest.raises(ValueError):
        SwapReviewCache().issue(OWNER, {**FIELDS, "amount": amount}, QUOTE)


@pytest.mark.parametrize("amount", ["0.1", "2"])
def test_bounds_are_inclusive(amount):
    assert SwapReviewCache().issue(OWNER, {**FIELDS, "amount": amount}, QUOTE)["token"]


@pytest.mark.parametrize("changed", [{"coin_from": "ETH"}, {"coin_to": "ETH"},
                                    {"amount": 1.1}, {"address": "attacker"}])
def test_changed_fields_cannot_redeem(changed):
    cache = SwapReviewCache()
    review = cache.issue(OWNER, FIELDS, QUOTE)
    with pytest.raises(ValueError):
        cache.consume(review["token"], OWNER, {**FIELDS, **changed})
    assert cache.consume(review["token"], OWNER, FIELDS) == QUOTE


@pytest.mark.parametrize("owner", ["user:3:session:two", "user:4:session:one"])
def test_session_and_user_binding(owner):
    cache = SwapReviewCache()
    review = cache.issue(OWNER, FIELDS, QUOTE)
    with pytest.raises(ValueError):
        cache.consume(review["token"], owner, FIELDS)
    assert cache.consume(review["token"], OWNER, FIELDS) == QUOTE


def test_expiry_capacity_replay_and_restart():
    now = [100.0]
    cache = SwapReviewCache(clock=lambda: now[0], max_entries=1)
    review = cache.issue(OWNER, FIELDS, QUOTE)
    with pytest.raises(ValueError):
        cache.issue(OWNER, FIELDS, QUOTE)
    with pytest.raises(ValueError):
        SwapReviewCache().consume(review["token"], OWNER, FIELDS)
    now[0] += 120
    with pytest.raises(ValueError):
        cache.consume(review["token"], OWNER, FIELDS)
    fresh = cache.issue(OWNER, FIELDS, QUOTE)
    assert fresh["token"] != review["token"]
    assert cache.consume(fresh["token"], OWNER, FIELDS) == QUOTE
    with pytest.raises(ValueError):
        cache.consume(fresh["token"], OWNER, FIELDS)


def test_returned_quote_cannot_mutate_approval():
    cache = SwapReviewCache()
    review = cache.issue(OWNER, FIELDS, {"estimated_receive": 100, "rate": 100})
    review["quote"]["estimated_receive"] = "999"
    quote = cache.consume(review["token"], OWNER, FIELDS)
    assert quote["estimated_receive"] == "100"
    assert quote["withdraw_fee"] is None


def test_concurrent_consume_only_one_wins():
    cache = SwapReviewCache()
    review = cache.issue(OWNER, FIELDS, QUOTE)
    barrier = threading.Barrier(8)

    def redeem(_):
        barrier.wait()
        try:
            cache.consume(review["token"], OWNER, FIELDS)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(redeem, range(8))) == 1
