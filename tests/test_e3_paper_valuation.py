import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_market_contracts import build_market_snapshot
from app.e3_paper_ledger import create_paper_ledger
from app.e3_paper_risk import DAY_MS, build_paper_risk_policy
from app.e3_paper_usage import create_daily_usage
from app.e3_paper_valuation import (build_equity_valuation,
                                    calculate_paper_drawdown,
                                    create_equity_baseline,
                                    evaluate_paper_risk_from_derived_state,
                                    validate_equity_baseline,
                                    validate_equity_valuation,
                                    validate_paper_drawdown)

NOW = 1786420801000


def ledger(balances=None):
    return create_paper_ledger(
        account_id="sandbox_1", balances=balances or {"BTC": "2", "USDT": "1000"})


def book(midpoint=100, *, observed=1786420800123, source="bybit"):
    return build_market_snapshot(
        source=source, symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=observed,
        bids=[[str(midpoint - 1), "5"]], asks=[[str(midpoint + 1), "5"]])


def baseline():
    value = build_equity_valuation(
        ledger(), [book(100)], quote_asset="USDT", assessed_at_epoch_ms=NOW)
    return create_equity_baseline(value)


def test_valuation_is_deterministic_complete_and_non_executing():
    value = build_equity_valuation(
        ledger(), [book(100)], quote_asset="USDT", assessed_at_epoch_ms=NOW)
    assert value["equityQuote"] == "1200"
    assert value["components"] == [
        {"asset": "BTC", "amount": "2", "priceQuote": "100",
         "valueQuote": "200", "snapshotId": book(100)["snapshotId"], "ageMs": 877},
        {"asset": "USDT", "amount": "1000", "priceQuote": "1",
         "valueQuote": "1000", "snapshotId": None, "ageMs": None},
    ]
    assert value["paperOnly"] is True
    assert value["actionAllowed"] is False
    assert validate_equity_valuation(json.loads(json.dumps(value))) == value


def test_baseline_and_drawdown_are_content_addressed_and_gain_floors_at_zero():
    origin = baseline()
    fixture = json.loads((ROOT / "contracts/e3-market/paper-equity-baseline.v1.json").read_text())
    assert origin == fixture
    assert validate_equity_baseline(json.loads(json.dumps(origin))) == origin
    lower = build_equity_valuation(
        ledger(), [book(40)], quote_asset="USDT", assessed_at_epoch_ms=NOW)
    loss = calculate_paper_drawdown(origin, lower)
    assert loss["baselineEquityQuote"] == "1200"
    assert loss["currentEquityQuote"] == "1080"
    assert loss["drawdownQuote"] == "120"
    assert loss["drawdownBps"] == "1000"
    assert validate_paper_drawdown(json.loads(json.dumps(loss))) == loss
    gain = calculate_paper_drawdown(
        origin, build_equity_valuation(
            ledger(), [book(120)], quote_asset="USDT", assessed_at_epoch_ms=NOW))
    assert gain["drawdownQuote"] == "0"
    assert gain["drawdownBps"] == "0"


@pytest.mark.parametrize("snapshots", [
    [], [book(100), book(100, source="okx")],
    [book(100, observed=NOW - 5001)], [book(100, observed=NOW + 1001)],
])
def test_missing_duplicate_stale_or_future_prices_fail_closed(snapshots):
    with pytest.raises(ValueError):
        build_equity_valuation(
            ledger(), snapshots, quote_asset="USDT", assessed_at_epoch_ms=NOW)


def test_extra_unpriced_asset_requires_exact_market_snapshot():
    state = ledger({"BTC": "1", "ETH": "2", "USDT": "1000"})
    with pytest.raises(ValueError):
        build_equity_valuation(
            state, [book(100)], quote_asset="USDT", assessed_at_epoch_ms=NOW)


@pytest.mark.parametrize("field,value", [
    ("equityQuote", "999"), ("valuationId", "pev_" + "0" * 64),
    ("marketMaxAgeMs", 999999), ("actionAllowed", True),
])
def test_valuation_tamper_fails_closed(field, value):
    valuation = build_equity_valuation(
        ledger(), [book(100)], quote_asset="USDT", assessed_at_epoch_ms=NOW)
    changed = copy.deepcopy(valuation)
    changed[field] = value
    with pytest.raises(ValueError):
        validate_equity_valuation(changed)


def test_risk_gate_uses_derived_drawdown_and_blocks_breach():
    low_market = book(40)
    policy = build_paper_risk_policy(
        account_id="sandbox_1", allowed_symbols=["BTCUSDT"],
        max_order_notional_quote="300", max_daily_notional_quote="1000",
        max_trades_per_day=5, max_drawdown_quote="100")
    usage = create_daily_usage(account_id="sandbox_1",
                               usage_day_epoch=NOW // DAY_MS)
    result = evaluate_paper_risk_from_derived_state(
        ledger(), low_market, policy, usage, baseline(), [low_market],
        quote_asset="USDT", side="BUY", input_amount="82", fee_bps=10,
        idempotency_key="paper_1", evaluated_at_epoch_ms=NOW)
    assert result["valuation"]["equityQuote"] == "1080"
    assert result["drawdown"]["drawdownQuote"] == "120"
    assert result["decision"]["currentDrawdownQuote"] == "120"
    assert result["decision"]["verdict"] == "HOLD"
    assert "DRAWDOWN" in result["decision"]["blockers"]
    assert result["decision"]["actionAllowed"] is False


def test_valuation_scope_mismatch_fails_closed():
    other = create_paper_ledger(account_id="other",
                                balances={"BTC": "2", "USDT": "1000"})
    current = build_equity_valuation(
        other, [book(100)], quote_asset="USDT", assessed_at_epoch_ms=NOW)
    with pytest.raises(ValueError, match="scope mismatch"):
        calculate_paper_drawdown(baseline(), current)
