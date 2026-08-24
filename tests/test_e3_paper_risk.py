import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_market_contracts import build_market_snapshot
from app.e3_paper_ledger import create_paper_ledger
from app.e3_paper_risk import (DAY_MS, build_paper_risk_policy,
                               evaluate_paper_risk,
                               validate_paper_risk_decision,
                               validate_paper_risk_policy)

NOW = 1786420801000


def book(*, observed=1786420800123, symbol="BTCUSDT"):
    base = "BTC" if symbol == "BTCUSDT" else "ETH"
    return build_market_snapshot(
        source="bybit", symbol=symbol, base_asset=base, quote_asset="USDT",
        observed_at_epoch_ms=observed,
        bids=[["99", "5"]], asks=[["101", "5"]])


def ledger(account="sandbox_1", balances=None):
    return create_paper_ledger(
        account_id=account, balances=balances or {"BTC": "2", "USDT": "1000"})


def policy(**changes):
    values = dict(account_id="sandbox_1", allowed_symbols=["BTCUSDT"],
                  max_order_notional_quote="300", max_daily_notional_quote="1000",
                  max_trades_per_day=5, max_drawdown_quote="100")
    values.update(changes)
    return build_paper_risk_policy(**values)


def decide(state=None, market=None, limits=None, **changes):
    values = dict(side="BUY", input_amount="202", fee_bps=10,
                  idempotency_key="paper_1", evaluated_at_epoch_ms=NOW,
                  usage_day_epoch=NOW // DAY_MS, daily_trade_count=1,
                  daily_notional_quote="200", current_drawdown_quote="10")
    values.update(changes)
    return evaluate_paper_risk(state or ledger(), market or book(),
                               limits or policy(), **values)


def test_policy_is_canonical_content_addressed_and_fail_closed():
    first = policy()
    fixture = json.loads((ROOT / "contracts/e3-market/paper-risk-policy.v1.json").read_text())
    assert first == fixture
    second = policy(account_id=" sandbox_1 ", allowed_symbols=["btcusdt"],
                    max_order_notional_quote="300.0",
                    max_daily_notional_quote="1000.00",
                    max_drawdown_quote="100.0")
    assert first == second
    assert validate_paper_risk_policy(json.loads(json.dumps(first))) == first
    assert first["paperOnly"] is True
    assert first["actionAllowed"] is False


def test_allow_decision_is_still_paper_only_and_non_executing():
    result = decide()
    assert result["verdict"] == "PAPER_ALLOW"
    assert result["blockers"] == []
    assert all(item["passed"] for item in result["checks"])
    assert result["orderNotionalQuote"] == "202"
    assert result["dailyNotionalProjected"] == "402"
    assert result["paperOnly"] is True
    assert result["executionEffect"] == "NONE"
    assert result["actionAllowed"] is False
    assert result == decide()
    assert validate_paper_risk_decision(result) == result


@pytest.mark.parametrize("expected,kwargs", [
    ("ACCOUNT_MATCH", {"limits": policy(account_id="other")}),
    ("SYMBOL_ALLOWED", {"limits": policy(allowed_symbols=["ETHUSDT"])}),
    ("MARKET_FRESH", {"market": book(observed=NOW - 5001)}),
    ("MARKET_FRESH", {"market": book(observed=NOW + 1001)}),
    ("ORDER_NOTIONAL", {"limits": policy(max_order_notional_quote="201")}),
    ("DAILY_NOTIONAL", {"daily_notional_quote": "799"}),
    ("DAILY_TRADE_COUNT", {"daily_trade_count": 5}),
    ("DRAWDOWN", {"current_drawdown_quote": "100.01"}),
    ("PAPER_BALANCE", {"state": ledger(balances={"BTC": "2", "USDT": "100"})}),
])
def test_each_hard_limit_produces_hold(expected, kwargs):
    result = decide(**kwargs)
    assert result["verdict"] == "HOLD"
    assert expected in result["blockers"]
    assert result["actionAllowed"] is False


def test_sell_notional_uses_quote_value_and_boundaries_are_inclusive():
    result = decide(side="SELL", input_amount="2", daily_trade_count=4,
                    daily_notional_quote="802", current_drawdown_quote="100")
    assert result["orderNotionalQuote"] == "198"
    assert result["dailyNotionalProjected"] == "1000"
    assert result["verdict"] == "PAPER_ALLOW"


@pytest.mark.parametrize("field,value", [
    ("policyId", "prp_" + "0" * 64), ("paperOnly", False),
    ("actionAllowed", True), ("marketMaxAgeMs", 999999),
])
def test_policy_tamper_fails_closed(field, value):
    changed = copy.deepcopy(policy())
    changed[field] = value
    with pytest.raises(ValueError):
        validate_paper_risk_policy(changed)


@pytest.mark.parametrize("changes", [
    {"usage_day_epoch": NOW // DAY_MS - 1}, {"daily_trade_count": -1},
    {"daily_notional_quote": "-1"}, {"current_drawdown_quote": "NaN"},
    {"idempotency_key": "bad key"},
])
def test_invalid_usage_or_intent_fails_before_decision(changes):
    with pytest.raises(ValueError):
        decide(**changes)
