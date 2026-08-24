import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_engine_adapter import project_accepted_paper_engine_fill
from app.e3_engine_attempts import (invoke_paper_engine_once,
                                    validate_paper_engine_attempt)
from test_e3_engine_adapter import FakeEngine, NOW, inputs, ready_intent


class FailingEngine:
    def __init__(self, error):
        self.error, self.calls = error, 0

    def submit(self, request):
        self.calls += 1
        raise self.error


def invoke(engine, **changes):
    values = dict(started_at_epoch_ms=NOW + 1, finished_at_epoch_ms=NOW + 3)
    values.update(changes)
    return invoke_paper_engine_once(ready_intent(), engine, **values)


def test_received_attempt_binds_receipt_and_can_project_fill():
    engine = FakeEngine()
    submission, attempt, receipt = invoke(engine)
    assert attempt["status"] == "RECEIVED"
    assert attempt["receiptId"] == receipt["receiptId"]
    assert attempt["retryAllowed"] is False
    assert attempt["automaticResubmitAllowed"] is False
    assert validate_paper_engine_attempt(
        json.loads(json.dumps(attempt)), submission=submission, receipt=receipt) == attempt
    ledger, market = inputs()
    filled, _, _ = project_accepted_paper_engine_fill(
        ready_intent(), submission, receipt, ledger, market,
        idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 3)
    assert filled["status"] == "FILLED"


@pytest.mark.parametrize("error,reason", [
    (TimeoutError("late"), "TIMEOUT"),
    (ConnectionError("down"), "TRANSPORT_ERROR"),
])
def test_uncertain_transport_is_terminal_manual_review_and_never_fillable(error, reason):
    engine = FailingEngine(error)
    submission, attempt, receipt = invoke(engine)
    assert engine.calls == 1
    assert receipt is None
    assert attempt["status"] == "UNKNOWN"
    assert attempt["reason"] == reason
    assert attempt["manualReviewRequired"] is True
    assert attempt["retryAllowed"] is False
    assert validate_paper_engine_attempt(attempt, submission=submission) == attempt
    ledger, market = inputs()
    with pytest.raises((TypeError, ValueError)):
        project_accepted_paper_engine_fill(
            ready_intent(), submission, receipt, ledger, market,
            idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 4)


def test_invalid_response_is_unknown_not_a_synthetic_rejection():
    engine = FakeEngine(extra="field")
    _, attempt, receipt = invoke(engine)
    assert len(engine.calls) == 1
    assert receipt is None
    assert attempt["status"] == "UNKNOWN"
    assert attempt["reason"] == "INVALID_RESPONSE"
    assert attempt["manualReviewRequired"] is True


def test_exact_replay_does_not_call_transport_again():
    first_engine = FailingEngine(TimeoutError("late"))
    submission, attempt, receipt = invoke(first_engine)
    second_engine = FakeEngine()
    replay_submission, replay_attempt, replay_receipt = invoke(
        second_engine, previous_attempt=json.loads(json.dumps(attempt)),
        previous_receipt=receipt)
    assert second_engine.calls == []
    assert (replay_submission, replay_attempt, replay_receipt) == (submission, attempt, None)


def test_received_exact_replay_returns_original_receipt_without_transport():
    submission, attempt, receipt = invoke(FakeEngine())
    engine = FakeEngine()
    replayed = invoke(engine, previous_attempt=attempt, previous_receipt=receipt)
    assert engine.calls == []
    assert replayed == (submission, attempt, receipt)


def test_attempt_or_receipt_drift_fails_before_transport():
    submission, attempt, receipt = invoke(FakeEngine())
    changed = copy.deepcopy(attempt)
    changed["stateHash"] = "pis_" + "0" * 64
    engine = FakeEngine()
    with pytest.raises(ValueError):
        invoke(engine, previous_attempt=changed, previous_receipt=receipt)
    assert engine.calls == []
    changed_receipt = copy.deepcopy(receipt)
    changed_receipt["receiptId"] = "per_" + "0" * 64
    with pytest.raises(ValueError):
        invoke(engine, previous_attempt=attempt, previous_receipt=changed_receipt)
    assert engine.calls == []


def test_attempt_time_and_safety_tamper_fail_closed():
    submission, attempt, receipt = invoke(FakeEngine())
    for field, value in (("finishedAtEpochMs", NOW), ("retryAllowed", True),
                         ("automaticResubmitAllowed", True),
                         ("attemptId", "pea_" + "0" * 64)):
        changed = copy.deepcopy(attempt)
        changed[field] = value
        with pytest.raises(ValueError):
            validate_paper_engine_attempt(changed, submission=submission, receipt=receipt)


def test_attempt_module_has_no_network_clock_or_runtime_configuration_surface():
    source = (ROOT / "kairos/app/e3_engine_attempts.py").read_text()
    for forbidden in ("requests", "httpx", "aiohttp", "socket", "ccxt",
                      "os.environ", "subprocess", "time.time"):
        assert forbidden not in source
