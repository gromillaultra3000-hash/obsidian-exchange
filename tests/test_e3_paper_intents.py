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
                                  reconcile_paper_fill,
                                  validate_paper_intent_state)
from app.e3_paper_ledger import create_paper_ledger
from app.e3_paper_risk import (DAY_MS, build_paper_risk_policy,
                               evaluate_paper_risk,
                               validate_paper_risk_decision)

NOW = 1786420801000


def market():
    return build_market_snapshot(
        source="bybit", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=1786420800123,
        bids=[["99", "5"]], asks=[["101", "5"]])


def ledger():
    return create_paper_ledger(account_id="sandbox_1",
                               balances={"BTC": "2", "USDT": "1000"})


def decision(**changes):
    values = dict(side="BUY", input_amount="202", fee_bps=10,
                  idempotency_key="paper_1", evaluated_at_epoch_ms=NOW,
                  usage_day_epoch=NOW // DAY_MS, daily_trade_count=1,
                  daily_notional_quote="200", current_drawdown_quote="10")
    values.update(changes)
    policy = build_paper_risk_policy(
        account_id="sandbox_1", allowed_symbols=["BTCUSDT"],
        max_order_notional_quote="300", max_daily_notional_quote="1000",
        max_trades_per_day=5, max_drawdown_quote="100")
    return evaluate_paper_risk(ledger(), market(), policy, **values)


def open_state(risk, at=NOW + 1):
    admission = assess_paper_admission(
        create_admission_control(account_id="sandbox_1"), risk)
    return open_paper_intent(risk, admission, recorded_at_epoch_ms=at)


def test_decision_validation_and_ready_open_are_content_bound_non_executing():
    risk = decision()
    assert validate_paper_risk_decision(json.loads(json.dumps(risk))) == risk
    state = open_state(risk)
    assert state["status"] == "READY"
    assert state["sequence"] == 1
    assert state["expectedLedgerHash"] is None
    assert state["simulationOnly"] is True
    assert state["executionEffect"] == "NONE"
    assert state["actionAllowed"] is False
    assert validate_paper_intent_state(json.loads(json.dumps(state))) == state


def test_hold_decision_opens_terminal_hold_and_cannot_fill():
    state = open_state(decision(daily_trade_count=5))
    assert state["status"] == "HOLD"
    with pytest.raises(ValueError):
        project_paper_fill(state, ledger(), market(), idempotency_key="paper_1",
                           recorded_at_epoch_ms=NOW + 2)


def test_fill_then_reconcile_survives_json_restart_and_is_idempotent():
    opened = open_state(decision())
    filled, result_ledger = project_paper_fill(
        json.loads(json.dumps(opened)), ledger(), market(),
        idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 2)
    assert filled["status"] == "FILLED"
    assert filled["expectedLedgerHash"] == result_ledger["ledgerHash"]
    terminal = reconcile_paper_fill(
        json.loads(json.dumps(filled)), json.loads(json.dumps(result_ledger)),
        recorded_at_epoch_ms=NOW + 3)
    assert terminal["status"] == "RECONCILED"
    assert terminal["sequence"] == 3
    assert terminal["observedLedgerHash"] == result_ledger["ledgerHash"]
    assert reconcile_paper_fill(terminal, result_ledger,
                                recorded_at_epoch_ms=NOW + 4) == terminal


def test_mismatched_observation_goes_to_terminal_review_without_retry():
    opened = open_state(decision())
    filled, result_ledger = project_paper_fill(
        opened, ledger(), market(), idempotency_key="paper_1",
        recorded_at_epoch_ms=NOW + 2)
    terminal = reconcile_paper_fill(filled, ledger(), recorded_at_epoch_ms=NOW + 3)
    assert terminal["status"] == "REVIEW"
    assert terminal["expectedLedgerHash"] == result_ledger["ledgerHash"]
    assert terminal["observedLedgerHash"] == ledger()["ledgerHash"]
    assert terminal["actionAllowed"] is False
    with pytest.raises(ValueError, match="drift"):
        reconcile_paper_fill(terminal, result_ledger, recorded_at_epoch_ms=NOW + 4)


@pytest.mark.parametrize("mutation", [
    lambda state: state.update(status="RECONCILED"),
    lambda state: state.update(actionAllowed=True),
    lambda state: state["events"][0].update(toStatus="FILLED"),
    lambda state: state.update(headHash="0" * 64),
])
def test_state_or_event_tamper_fails_closed(mutation):
    state = copy.deepcopy(open_state(decision()))
    mutation(state)
    with pytest.raises(ValueError):
        validate_paper_intent_state(state)


def test_fill_rejects_wrong_key_snapshot_or_ledger_binding():
    state = open_state(decision())
    with pytest.raises(ValueError):
        project_paper_fill(state, ledger(), market(), idempotency_key="other",
                           recorded_at_epoch_ms=NOW + 2)
    changed_market = build_market_snapshot(
        source="okx", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=1786420800123,
        bids=[["99", "5"]], asks=[["101", "5"]])
    with pytest.raises(ValueError):
        project_paper_fill(state, ledger(), changed_market,
                           idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 2)
