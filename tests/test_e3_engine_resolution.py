import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_engine_adapter import submit_to_paper_engine
from app.e3_engine_attempts import invoke_paper_engine_once
from app.e3_engine_resolution import (project_resolved_unknown_paper_engine_fill,
                                      resolve_unknown_paper_engine_attempt,
                                      validate_paper_engine_resolution)
from test_e3_engine_adapter import FakeEngine, NOW, inputs, ready_intent
from test_e3_engine_attempts import FailingEngine

EVIDENCE = "a" * 64


def uncertain():
    return invoke_paper_engine_once(
        ready_intent(), FailingEngine(TimeoutError("late")),
        started_at_epoch_ms=NOW + 1, finished_at_epoch_ms=NOW + 3)[:2]


def recovered_receipt(*, rejected=False):
    engine = (FakeEngine(outcome="REJECTED", reason="ENGINE_UNAVAILABLE")
              if rejected else FakeEngine())
    return submit_to_paper_engine(ready_intent(), engine)[1]


def test_exact_recovered_accepted_receipt_is_fill_eligible_without_rewriting_attempt():
    submission, attempt = uncertain()
    before = copy.deepcopy(attempt)
    receipt = recovered_receipt()
    resolution = resolve_unknown_paper_engine_attempt(
        attempt, submission, evidence_hash=EVIDENCE,
        resolved_at_epoch_ms=NOW + 4, recovered_receipt=receipt)
    assert attempt == before
    assert resolution["resolution"] == "RECEIPT_RECOVERED"
    assert resolution["recoveredReceiptId"] == receipt["receiptId"]
    assert resolution["fillEligible"] is True
    assert resolution["retryAllowed"] is False
    ledger, market = inputs()
    filled, _, _ = project_resolved_unknown_paper_engine_fill(
        resolution, attempt, submission, receipt, ready_intent(), ledger, market,
        idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 4)
    assert filled["status"] == "FILLED"


def test_recovered_rejection_is_terminal_and_not_fill_eligible():
    submission, attempt = uncertain()
    receipt = recovered_receipt(rejected=True)
    resolution = resolve_unknown_paper_engine_attempt(
        attempt, submission, evidence_hash=EVIDENCE,
        resolved_at_epoch_ms=NOW + 4, recovered_receipt=receipt)
    assert resolution["fillEligible"] is False
    assert resolution["automaticResubmitAllowed"] is False
    ledger, market = inputs()
    with pytest.raises(ValueError, match="not fill eligible"):
        project_resolved_unknown_paper_engine_fill(
            resolution, attempt, submission, receipt, ready_intent(), ledger, market,
            idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 4)


@pytest.mark.parametrize("disposition", [
    "AMBIGUOUS", "ENGINE_UNAVAILABLE", "NOT_FOUND", "OPERATOR_ESCALATED",
])
def test_bounded_manual_disposition_never_allows_fill_or_retry(disposition):
    submission, attempt = uncertain()
    resolution = resolve_unknown_paper_engine_attempt(
        attempt, submission, evidence_hash=EVIDENCE,
        resolved_at_epoch_ms=NOW + 4, manual_disposition=disposition)
    assert resolution["resolution"] == "MANUAL_REVIEW"
    assert resolution["fillEligible"] is False
    assert resolution["retryAllowed"] is False
    assert resolution["automaticResubmitAllowed"] is False
    assert resolution["recoveredReceiptId"] is None


def test_exact_resolution_replay_is_unchanged_and_drift_fails():
    submission, attempt = uncertain()
    receipt = recovered_receipt()
    resolution = resolve_unknown_paper_engine_attempt(
        attempt, submission, evidence_hash=EVIDENCE,
        resolved_at_epoch_ms=NOW + 4, recovered_receipt=receipt)
    replayed = resolve_unknown_paper_engine_attempt(
        attempt, submission, evidence_hash="b" * 64,
        resolved_at_epoch_ms=NOW + 99, recovered_receipt=receipt,
        previous_resolution=json.loads(json.dumps(resolution)))
    assert replayed == resolution
    changed_receipt = copy.deepcopy(receipt)
    changed_receipt["receiptId"] = "per_" + "0" * 64
    with pytest.raises(ValueError):
        resolve_unknown_paper_engine_attempt(
            attempt, submission, evidence_hash=EVIDENCE,
            resolved_at_epoch_ms=NOW + 4, recovered_receipt=changed_receipt,
            previous_resolution=resolution)


def test_received_attempt_and_cross_submission_receipt_are_rejected():
    submission, attempt, receipt = invoke_paper_engine_once(
        ready_intent(), FakeEngine(), started_at_epoch_ms=NOW + 1,
        finished_at_epoch_ms=NOW + 3)
    with pytest.raises(ValueError):
        resolve_unknown_paper_engine_attempt(
            attempt, submission, evidence_hash=EVIDENCE,
            resolved_at_epoch_ms=NOW + 4, recovered_receipt=receipt)


@pytest.mark.parametrize("field,value", [
    ("attemptId", "pea_" + "0" * 64), ("fillEligible", False),
    ("retryAllowed", True), ("automaticResubmitAllowed", True),
    ("resolutionId", "pear_" + "0" * 64),
])
def test_resolution_tamper_fails_closed(field, value):
    submission, attempt = uncertain()
    receipt = recovered_receipt()
    resolution = resolve_unknown_paper_engine_attempt(
        attempt, submission, evidence_hash=EVIDENCE,
        resolved_at_epoch_ms=NOW + 4, recovered_receipt=receipt)
    changed = copy.deepcopy(resolution)
    changed[field] = value
    with pytest.raises(ValueError):
        validate_paper_engine_resolution(
            changed, attempt=attempt, submission=submission,
            recovered_receipt=receipt)


@pytest.mark.parametrize("kwargs", [
    {"evidence_hash": "x" * 64, "manual_disposition": "AMBIGUOUS"},
    {"evidence_hash": EVIDENCE, "manual_disposition": "RETRY"},
    {"evidence_hash": EVIDENCE, "manual_disposition": "AMBIGUOUS",
     "recovered_receipt": {}},
])
def test_malformed_evidence_unknown_disposition_or_dual_resolution_fails(kwargs):
    submission, attempt = uncertain()
    with pytest.raises(ValueError):
        resolve_unknown_paper_engine_attempt(
            attempt, submission, resolved_at_epoch_ms=NOW + 4, **kwargs)


def test_resolution_module_has_no_transport_network_or_runtime_surface():
    source = (ROOT / "kairos/app/e3_engine_resolution.py").read_text()
    for forbidden in (".submit(", "requests", "httpx", "aiohttp", "socket",
                      "ccxt", "os.environ", "subprocess", "time.time"):
        assert forbidden not in source
