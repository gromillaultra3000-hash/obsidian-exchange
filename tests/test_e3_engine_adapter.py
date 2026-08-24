import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_engine_adapter import (build_paper_engine_submission,
                                   project_accepted_paper_engine_fill,
                                   submit_to_paper_engine,
                                   validate_paper_engine_fill_projection,
                                   validate_paper_engine_receipt,
                                   validate_paper_engine_submission)
from app.e3_market_contracts import build_market_snapshot
from app.e3_paper_admission import assess_paper_admission, create_admission_control
from app.e3_paper_intents import open_paper_intent
from app.e3_paper_ledger import create_paper_ledger
from app.e3_paper_risk import DAY_MS, build_paper_risk_policy, evaluate_paper_risk

NOW = 1786420801000


def ready_intent(*, blocked=False):
    ledger = create_paper_ledger(account_id="sandbox_1", balances={"BTC": "2", "USDT": "1000"})
    market = build_market_snapshot(source="bybit", symbol="BTCUSDT", base_asset="BTC",
                                   quote_asset="USDT", observed_at_epoch_ms=1786420800123,
                                   bids=[["99", "5"]], asks=[["101", "5"]])
    policy = build_paper_risk_policy(account_id="sandbox_1", allowed_symbols=["BTCUSDT"],
                                     max_order_notional_quote="300",
                                     max_daily_notional_quote="1000",
                                     max_trades_per_day=1, max_drawdown_quote="100")
    risk = evaluate_paper_risk(ledger, market, policy, side="BUY", input_amount="202",
                               fee_bps=10, idempotency_key="paper_1",
                               evaluated_at_epoch_ms=NOW, usage_day_epoch=NOW // DAY_MS,
                               daily_trade_count=1 if blocked else 0,
                               daily_notional_quote="0", current_drawdown_quote="0")
    admission = assess_paper_admission(create_admission_control(account_id="sandbox_1"), risk)
    return open_paper_intent(risk, admission, recorded_at_epoch_ms=NOW + 1)


def inputs():
    ledger = create_paper_ledger(account_id="sandbox_1", balances={"BTC": "2", "USDT": "1000"})
    market = build_market_snapshot(source="bybit", symbol="BTCUSDT", base_asset="BTC",
                                   quote_asset="USDT", observed_at_epoch_ms=1786420800123,
                                   bids=[["99", "5"]], asks=[["101", "5"]])
    return ledger, market


class FakeEngine:
    def __init__(self, **changes):
        self.calls = []
        self.changes = changes

    def submit(self, request):
        self.calls.append(request)
        response = {"submissionId": request["submissionId"], "intentId": request["intentId"],
                    "engineMode": "PAPER_SIMULATION", "outcome": "ACCEPTED",
                    "reason": "NONE", "engineReceiptId": "sim_1",
                    "observedAtEpochMs": NOW + 2}
        response.update(self.changes)
        return response


def test_submission_and_receipt_are_content_bound_and_non_executing():
    intent = ready_intent()
    engine = FakeEngine()
    submission, receipt = submit_to_paper_engine(intent, engine)
    assert engine.calls == [submission]
    assert validate_paper_engine_submission(json.loads(json.dumps(submission))) == submission
    assert validate_paper_engine_receipt(json.loads(json.dumps(receipt)), submission=submission) == receipt
    assert receipt["outcome"] == "ACCEPTED"
    assert receipt["simulationOnly"] is True
    assert receipt["executionEffect"] == "NONE"
    assert receipt["actionAllowed"] is False


def test_rejection_is_explicit_and_does_not_mutate_intent():
    intent = ready_intent()
    before = copy.deepcopy(intent)
    _, receipt = submit_to_paper_engine(
        intent, FakeEngine(outcome="REJECTED", reason="ENGINE_UNAVAILABLE"))
    assert receipt["outcome"] == "REJECTED"
    assert intent == before


def test_hold_intent_never_reaches_transport():
    engine = FakeEngine()
    with pytest.raises(ValueError, match="READY"):
        submit_to_paper_engine(ready_intent(blocked=True), engine)
    assert engine.calls == []


@pytest.mark.parametrize("changes", [
    {"intentId": "ppi_wrong"}, {"engineMode": "LIVE"}, {"extra": "field"},
    {"outcome": "ACCEPTED", "reason": "ENGINE_UNAVAILABLE"},
    {"outcome": "REJECTED", "reason": "NONE"},
    {"engineReceiptId": "bad value"}, {"observedAtEpochMs": 0},
])
def test_untrusted_transport_response_fails_closed(changes):
    with pytest.raises(ValueError):
        submit_to_paper_engine(ready_intent(), FakeEngine(**changes))


@pytest.mark.parametrize("field,value", [
    ("submissionId", "pes_" + "0" * 64), ("actionAllowed", True),
    ("engineMode", "LIVE"),
])
def test_submission_tamper_fails_closed(field, value):
    changed = build_paper_engine_submission(ready_intent())
    changed[field] = value
    with pytest.raises(ValueError):
        validate_paper_engine_submission(changed)


def test_module_has_no_network_sdk_or_runtime_configuration_surface():
    source = (ROOT / "kairos/app/e3_engine_adapter.py").read_text()
    for forbidden in ("requests", "httpx", "aiohttp", "socket", "ccxt", "os.environ", "subprocess"):
        assert forbidden not in source


def test_accepted_receipt_is_required_and_bound_into_filled_state():
    intent = ready_intent()
    submission, receipt = submit_to_paper_engine(intent, FakeEngine())
    ledger, market = inputs()
    filled, after, projection = project_accepted_paper_engine_fill(
        intent, submission, receipt, ledger, market, idempotency_key="paper_1",
        recorded_at_epoch_ms=NOW + 3)
    assert filled["status"] == "FILLED"
    assert filled["events"][-1]["evidenceHash"] == receipt["receiptId"]
    assert projection["expectedLedgerHash"] == after["ledgerHash"]
    assert projection["filledStateHash"] == filled["stateHash"]
    assert projection["simulationOnly"] is True
    assert projection["actionAllowed"] is False
    assert validate_paper_engine_fill_projection(
        json.loads(json.dumps(projection)), intent_state=intent,
        filled_state=filled, submission=submission, receipt=receipt) == projection


def test_rejected_receipt_cannot_project_fill():
    intent = ready_intent()
    submission, receipt = submit_to_paper_engine(
        intent, FakeEngine(outcome="REJECTED", reason="ENGINE_UNAVAILABLE"))
    ledger, market = inputs()
    with pytest.raises(ValueError, match="accepted"):
        project_accepted_paper_engine_fill(
            intent, submission, receipt, ledger, market,
            idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 3)


def test_receipt_for_another_ready_state_or_future_receipt_fails_closed():
    intent = ready_intent()
    submission, receipt = submit_to_paper_engine(intent, FakeEngine())
    ledger, market = inputs()
    other = copy.deepcopy(intent)
    other["stateHash"] = "pis_" + "0" * 64
    with pytest.raises(ValueError):
        project_accepted_paper_engine_fill(
            other, submission, receipt, ledger, market,
            idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 3)
    future = copy.deepcopy(receipt)
    future["observedAtEpochMs"] = NOW + 99
    unsigned = dict(future)
    unsigned.pop("receiptId")
    from app.e3_paper_ledger import _hash
    future["receiptId"] = "per_" + _hash(unsigned)
    with pytest.raises(ValueError, match="accepted"):
        project_accepted_paper_engine_fill(
            intent, submission, future, ledger, market,
            idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 3)


def test_fill_projection_tamper_fails_closed():
    intent = ready_intent()
    submission, receipt = submit_to_paper_engine(intent, FakeEngine())
    ledger, market = inputs()
    filled, _, projection = project_accepted_paper_engine_fill(
        intent, submission, receipt, ledger, market,
        idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 3)
    changed = copy.deepcopy(projection)
    changed["receiptId"] = "per_" + "0" * 64
    with pytest.raises(ValueError):
        validate_paper_engine_fill_projection(
            changed, intent_state=intent, filled_state=filled,
            submission=submission, receipt=receipt)
