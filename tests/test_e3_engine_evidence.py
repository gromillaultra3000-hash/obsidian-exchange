import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_engine_adapter import project_accepted_paper_engine_fill
from app.e3_engine_attempts import invoke_paper_engine_once
from app.e3_engine_evidence import (GENESIS_HASH,
                                    build_paper_engine_evidence_bundle,
                                    validate_paper_engine_evidence_bundle)
from app.e3_engine_resolution import (project_resolved_unknown_paper_engine_fill,
                                      resolve_unknown_paper_engine_attempt)
from test_e3_engine_adapter import FakeEngine, NOW, inputs, ready_intent
from test_e3_engine_attempts import FailingEngine
from test_e3_engine_resolution import EVIDENCE, recovered_receipt


def received_bundle(*, filled=False):
    ready = ready_intent()
    submission, attempt, receipt = invoke_paper_engine_once(
        ready, FakeEngine(), started_at_epoch_ms=NOW + 1,
        finished_at_epoch_ms=NOW + 3)
    filled_intent = projection = None
    if filled:
        ledger, market = inputs()
        filled_intent, _, projection = project_accepted_paper_engine_fill(
            ready, submission, receipt, ledger, market,
            idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 4)
    return build_paper_engine_evidence_bundle(
        sequence=0, previous_bundle_hash=GENESIS_HASH, ready_intent=ready,
        submission=submission, attempt=attempt, receipt=receipt,
        filled_intent=filled_intent, fill_projection=projection)


def unknown_bundle(*, resolution_kind=None, filled=False):
    ready = ready_intent()
    submission, attempt, _ = invoke_paper_engine_once(
        ready, FailingEngine(TimeoutError("late")),
        started_at_epoch_ms=NOW + 1, finished_at_epoch_ms=NOW + 3)
    receipt = resolution = filled_intent = projection = None
    if resolution_kind == "RECOVERED":
        receipt = recovered_receipt()
        resolution = resolve_unknown_paper_engine_attempt(
            attempt, submission, evidence_hash=EVIDENCE,
            resolved_at_epoch_ms=NOW + 4, recovered_receipt=receipt)
        if filled:
            ledger, market = inputs()
            filled_intent, _, projection = project_resolved_unknown_paper_engine_fill(
                resolution, attempt, submission, receipt, ready, ledger, market,
                idempotency_key="paper_1", recorded_at_epoch_ms=NOW + 5)
    elif resolution_kind == "MANUAL":
        resolution = resolve_unknown_paper_engine_attempt(
            attempt, submission, evidence_hash=EVIDENCE,
            resolved_at_epoch_ms=NOW + 4, manual_disposition="AMBIGUOUS")
    return build_paper_engine_evidence_bundle(
        sequence=0, previous_bundle_hash=GENESIS_HASH, ready_intent=ready,
        submission=submission, attempt=attempt, receipt=receipt,
        resolution=resolution, filled_intent=filled_intent,
        fill_projection=projection)


@pytest.mark.parametrize("bundle", [
    received_bundle(), received_bundle(filled=True), unknown_bundle(),
    unknown_bundle(resolution_kind="MANUAL"),
    unknown_bundle(resolution_kind="RECOVERED", filled=True),
])
def test_bundle_variants_are_self_contained_content_addressed_and_non_executing(bundle):
    assert bundle["bundleId"] == "peb_" + bundle["bundleHash"]
    assert bundle["accountId"] == "sandbox_1"
    assert bundle["simulationOnly"] is True
    assert bundle["executionEffect"] == "NONE"
    assert bundle["actionAllowed"] is False
    assert validate_paper_engine_evidence_bundle(
        json.loads(json.dumps(bundle))) == bundle


def test_sequence_and_previous_hash_contract_is_explicit():
    first = received_bundle()
    values = {key: first[key] for key in (
        "readyIntent", "submission", "attempt", "receipt", "resolution",
        "filledIntent", "fillProjection")}
    second = build_paper_engine_evidence_bundle(
        sequence=1, previous_bundle_hash=first["bundleHash"], **{
            "ready_intent": values["readyIntent"], "submission": values["submission"],
            "attempt": values["attempt"], "receipt": values["receipt"],
            "resolution": values["resolution"], "filled_intent": values["filledIntent"],
            "fill_projection": values["fillProjection"]})
    assert second["sequence"] == 1
    assert second["previousBundleHash"] == first["bundleHash"]
    with pytest.raises(ValueError):
        build_paper_engine_evidence_bundle(
            sequence=1, previous_bundle_hash=GENESIS_HASH,
            ready_intent=first["readyIntent"], submission=first["submission"],
            attempt=first["attempt"], receipt=first["receipt"])


@pytest.mark.parametrize("mutation", [
    lambda item: item.update(bundleHash="0" * 64),
    lambda item: item.update(actionAllowed=True),
    lambda item: item["submission"].update(engineMode="LIVE"),
    lambda item: item["attempt"].update(retryAllowed=True),
    lambda item: item["receipt"].update(receiptId="per_" + "0" * 64),
    lambda item: item.update(filledIntent=None),
])
def test_bundle_tamper_or_partial_fill_fails_closed(mutation):
    changed = copy.deepcopy(received_bundle(filled=True))
    mutation(changed)
    with pytest.raises(ValueError):
        validate_paper_engine_evidence_bundle(changed)


def test_manual_or_unresolved_unknown_cannot_smuggle_receipt_or_fill():
    changed = unknown_bundle(resolution_kind="MANUAL")
    changed["receipt"] = recovered_receipt()
    with pytest.raises(ValueError):
        validate_paper_engine_evidence_bundle(changed)
    unresolved = unknown_bundle()
    filled = received_bundle(filled=True)
    unresolved["filledIntent"] = filled["filledIntent"]
    unresolved["fillProjection"] = filled["fillProjection"]
    with pytest.raises(ValueError):
        validate_paper_engine_evidence_bundle(unresolved)
