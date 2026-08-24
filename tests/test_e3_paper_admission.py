import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_market_contracts import build_market_snapshot
from app.e3_paper_admission import (assess_paper_admission,
                                    create_admission_control,
                                    engage_emergency_stop, trip_circuit,
                                    validate_admission_control,
                                    validate_paper_admission)
from app.e3_paper_intents import open_paper_intent
from app.e3_paper_ledger import create_paper_ledger
from app.e3_paper_risk import DAY_MS, build_paper_risk_policy, evaluate_paper_risk

NOW = 1786420801000


def risk(*, count=0, account="sandbox_1"):
    ledger = create_paper_ledger(account_id=account,
                                 balances={"BTC": "2", "USDT": "1000"})
    market = build_market_snapshot(
        source="bybit", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=1786420800123,
        bids=[["99", "5"]], asks=[["101", "5"]])
    policy = build_paper_risk_policy(
        account_id=account, allowed_symbols=["BTCUSDT"],
        max_order_notional_quote="300", max_daily_notional_quote="1000",
        max_trades_per_day=1, max_drawdown_quote="100")
    return evaluate_paper_risk(
        ledger, market, policy, side="BUY", input_amount="202", fee_bps=10,
        idempotency_key="paper_1", evaluated_at_epoch_ms=NOW,
        usage_day_epoch=NOW // DAY_MS, daily_trade_count=count,
        daily_notional_quote="0", current_drawdown_quote="0")


def test_open_control_and_admission_are_canonical_but_never_live_authority():
    control = create_admission_control(account_id="sandbox_1")
    fixture = json.loads((ROOT / "contracts/e3-market/paper-admission-control.v1.json").read_text())
    assert control == fixture
    assert validate_admission_control(json.loads(json.dumps(control))) == control
    admission = assess_paper_admission(control, risk())
    assert admission["verdict"] == "ADMIT_PAPER"
    assert admission["blockers"] == []
    assert admission["paperOnly"] is True
    assert admission["actionAllowed"] is False
    assert validate_paper_admission(admission) == admission
    intent = open_paper_intent(risk(), admission, recorded_at_epoch_ms=NOW + 1)
    assert intent["status"] == "READY"
    assert intent["controlHash"] == control["controlHash"]


def test_emergency_stop_is_terminal_idempotent_and_blocks_new_ready_intent():
    control = create_admission_control(account_id="sandbox_1")
    stopped = engage_emergency_stop(
        control, reason="OPERATOR", command_id="stop_1",
        recorded_at_epoch_ms=NOW + 1)
    assert stopped["status"] == "STOPPED"
    assert engage_emergency_stop(
        stopped, reason="OPERATOR", command_id="stop_1",
        recorded_at_epoch_ms=NOW + 99) == stopped
    admission = assess_paper_admission(stopped, risk())
    assert admission["verdict"] == "HOLD"
    assert admission["blockers"] == ["EMERGENCY_STOP"]
    assert open_paper_intent(risk(), admission,
                             recorded_at_epoch_ms=NOW + 2)["status"] == "HOLD"
    with pytest.raises(ValueError, match="terminal"):
        engage_emergency_stop(stopped, reason="INCIDENT", command_id="stop_2",
                              recorded_at_epoch_ms=NOW + 2)


def test_circuit_trip_is_terminal_and_carries_exact_evidence():
    control = create_admission_control(account_id="sandbox_1")
    tripped = trip_circuit(
        control, signal="RECONCILIATION_MISMATCH", evidence_hash="a" * 64,
        recorded_at_epoch_ms=NOW + 1)
    assert tripped["status"] == "TRIPPED"
    assert tripped["terminalEvidenceHash"] == "a" * 64
    admission = assess_paper_admission(tripped, risk())
    assert admission["blockers"] == ["CIRCUIT_TRIPPED"]
    assert admission["actionAllowed"] is False
    assert trip_circuit(
        tripped, signal="RECONCILIATION_MISMATCH", evidence_hash="a" * 64,
        recorded_at_epoch_ms=NOW + 2) == tripped


def test_risk_hold_and_stop_blockers_compose_monotonically():
    stopped = engage_emergency_stop(
        create_admission_control(account_id="sandbox_1"), reason="INCIDENT",
        command_id="stop_1", recorded_at_epoch_ms=NOW + 1)
    admission = assess_paper_admission(stopped, risk(count=1))
    assert admission["verdict"] == "HOLD"
    assert admission["blockers"] == ["RISK_DAILY_TRADE_COUNT", "EMERGENCY_STOP"]


@pytest.mark.parametrize("field,value", [
    ("status", "OPEN"), ("headHash", "0" * 64),
    ("terminalReason", "MAINTENANCE"), ("actionAllowed", True),
])
def test_control_tamper_fails_closed(field, value):
    stopped = engage_emergency_stop(
        create_admission_control(account_id="sandbox_1"), reason="OPERATOR",
        command_id="stop_1", recorded_at_epoch_ms=NOW + 1)
    changed = copy.deepcopy(stopped)
    changed[field] = value
    with pytest.raises(ValueError):
        validate_admission_control(changed)


def test_wrong_account_or_admission_binding_cannot_open_intent():
    decision = risk()
    with pytest.raises(ValueError, match="account mismatch"):
        assess_paper_admission(create_admission_control(account_id="other"), decision)
    other = risk(account="other")
    admission = assess_paper_admission(
        create_admission_control(account_id="other"), other)
    with pytest.raises(ValueError, match="does not bind"):
        open_paper_intent(decision, admission, recorded_at_epoch_ms=NOW + 1)


@pytest.mark.parametrize("call", [
    lambda control: engage_emergency_stop(
        control, reason="UNKNOWN", command_id="stop_1", recorded_at_epoch_ms=NOW),
    lambda control: trip_circuit(
        control, signal="OTHER", evidence_hash="a" * 64, recorded_at_epoch_ms=NOW),
    lambda control: trip_circuit(
        control, signal="RATE_LIMIT", evidence_hash="short", recorded_at_epoch_ms=NOW),
])
def test_unknown_reason_signal_or_bad_evidence_fails_closed(call):
    with pytest.raises(ValueError):
        call(create_admission_control(account_id="sandbox_1"))
