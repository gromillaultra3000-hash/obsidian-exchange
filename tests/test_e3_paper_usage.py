import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_market_contracts import build_market_snapshot
from app.e3_paper_admission import assess_paper_admission, create_admission_control
from app.e3_paper_intents import (open_paper_intent, project_paper_fill,
                                  reconcile_paper_fill)
from app.e3_paper_ledger import create_paper_ledger
from app.e3_paper_risk import DAY_MS, build_paper_risk_policy, evaluate_paper_risk
from app.e3_paper_usage import (append_reconciled_usage, create_daily_usage,
                                evaluate_paper_risk_from_usage,
                                validate_daily_usage)

NOW = 1786420801000
DAY = NOW // DAY_MS


def market():
    return build_market_snapshot(
        source="bybit", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=1786420800123,
        bids=[["99", "5"]], asks=[["101", "5"]])


def ledger(account="sandbox_1"):
    return create_paper_ledger(account_id=account,
                               balances={"BTC": "2", "USDT": "1000"})


def policy(*, max_trades=5, account="sandbox_1"):
    return build_paper_risk_policy(
        account_id=account, allowed_symbols=["BTCUSDT"],
        max_order_notional_quote="500", max_daily_notional_quote="1000",
        max_trades_per_day=max_trades, max_drawdown_quote="100")


def reconciled(*, key="paper_1", amount="202", account="sandbox_1"):
    before = ledger(account)
    decision = evaluate_paper_risk(
        before, market(), policy(account=account), side="BUY", input_amount=amount,
        fee_bps=10, idempotency_key=key, evaluated_at_epoch_ms=NOW,
        usage_day_epoch=DAY, daily_trade_count=0, daily_notional_quote="0",
        current_drawdown_quote="0")
    admission = assess_paper_admission(
        create_admission_control(account_id=account), decision)
    opened = open_paper_intent(decision, admission, recorded_at_epoch_ms=NOW + 1)
    filled, after = project_paper_fill(
        opened, before, market(), idempotency_key=key,
        recorded_at_epoch_ms=NOW + 2)
    return reconcile_paper_fill(filled, after, recorded_at_epoch_ms=NOW + 3), decision


def test_genesis_is_canonical_json_stable_and_non_executing():
    first = create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY)
    fixture = json.loads((ROOT / "contracts/e3-market/paper-daily-usage.v1.json").read_text())
    assert first == fixture
    second = create_daily_usage(account_id=" sandbox_1 ", usage_day_epoch=DAY)
    assert first == second
    assert first["tradeCount"] == 0
    assert first["notionalQuote"] == "0"
    assert first["paperOnly"] is True
    assert first["actionAllowed"] is False
    assert validate_daily_usage(json.loads(json.dumps(first))) == first


def test_only_reconciled_intent_appends_and_exact_retry_is_idempotent():
    usage = create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY)
    state, decision = reconciled()
    updated = append_reconciled_usage(usage, state, decision)
    assert updated["tradeCount"] == 1
    assert updated["notionalQuote"] == "202"
    assert updated["entries"][0]["intentStateHash"] == state["stateHash"]
    assert append_reconciled_usage(updated, state, decision) == updated
    assert validate_daily_usage(json.loads(json.dumps(updated))) == updated


def test_multiple_reconciled_intents_accumulate_in_hash_chain():
    usage = create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY)
    one, first_decision = reconciled(key="paper_1", amount="202")
    two, second_decision = reconciled(key="paper_2", amount="101")
    usage = append_reconciled_usage(usage, one, first_decision)
    usage = append_reconciled_usage(usage, two, second_decision)
    assert usage["tradeCount"] == 2
    assert usage["notionalQuote"] == "303"
    assert usage["entries"][1]["previousHash"] == usage["entries"][0]["entryHash"]


def test_review_hold_wrong_account_or_day_cannot_increment_usage():
    usage = create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY)
    state, decision = reconciled()
    review = copy.deepcopy(state)
    review["status"] = "REVIEW"
    with pytest.raises(ValueError):
        append_reconciled_usage(usage, review, decision)
    with pytest.raises(ValueError):
        append_reconciled_usage(
            create_daily_usage(account_id="other", usage_day_epoch=DAY), state, decision)
    with pytest.raises(ValueError):
        append_reconciled_usage(
            create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY + 1),
            state, decision)


@pytest.mark.parametrize("field,value", [
    ("tradeCount", 9), ("notionalQuote", "999"),
    ("headHash", "0" * 64), ("actionAllowed", True),
])
def test_usage_tamper_fails_closed(field, value):
    state, decision = reconciled()
    usage = append_reconciled_usage(
        create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY),
        state, decision)
    changed = copy.deepcopy(usage)
    changed[field] = value
    with pytest.raises(ValueError):
        validate_daily_usage(changed)


def test_risk_wrapper_uses_derived_count_and_notional_not_caller_values():
    state, decision = reconciled()
    usage = append_reconciled_usage(
        create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY),
        state, decision)
    result = evaluate_paper_risk_from_usage(
        ledger(), market(), policy(max_trades=1), usage, side="BUY",
        input_amount="101", fee_bps=10, idempotency_key="paper_2",
        evaluated_at_epoch_ms=NOW, current_drawdown_quote="0")
    assert result["dailyTradeCountBefore"] == 1
    assert result["dailyNotionalBefore"] == "202"
    assert result["verdict"] == "HOLD"
    assert "DAILY_TRADE_COUNT" in result["blockers"]
    assert result["actionAllowed"] is False


def test_risk_wrapper_rejects_usage_from_another_utc_day():
    usage = create_daily_usage(account_id="sandbox_1", usage_day_epoch=DAY - 1)
    with pytest.raises(ValueError, match="UTC day"):
        evaluate_paper_risk_from_usage(
            ledger(), market(), policy(), usage, side="BUY", input_amount="101",
            fee_bps=10, idempotency_key="paper_2", evaluated_at_epoch_ms=NOW,
            current_drawdown_quote="0")
