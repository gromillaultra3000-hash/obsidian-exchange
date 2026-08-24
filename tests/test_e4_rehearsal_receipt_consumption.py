import copy
import hashlib
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_rehearsal_receipt_consumption import (  # noqa: E402
    SQLiteE4RehearsalReceiptLedger, build_consumption_record,
    validate_consumption_record,
)
from core.e4_rehearsal_runner_authorization import (  # noqa: E402
    MAX_AUTHORIZATION_MS, PRECONDITIONS, build_owner_approval,
    build_precondition_evidence, authorize_rehearsal_runner,
)
from core.e4_rehearsal_runner_boundary import (  # noqa: E402
    build_runner_boundary, target_spec_fingerprint,
)
from core.e4_rehearsal_runner_plan import build_rehearsal_runner_plan  # noqa: E402

NOW = 1_800_000_000_000
TARGET = "e4-consumption-pg-1"
SNAPSHOT = "2" * 64
CLAIM_ID = "e4orr_" + "a" * 64
MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    plan = build_rehearsal_runner_plan(
        evidence_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())
    fingerprint = target_spec_fingerprint(target_ref=TARGET)
    approval = build_owner_approval(
        approval_ref="owner_approval_e4_consume_1", plan_id=plan["planId"],
        target_ref=TARGET, target_fingerprint_sha256=fingerprint,
        snapshot_sha256=SNAPSHOT,
        snapshot_ref_sha256=hashlib.sha256(b"snapshot_ref_1").hexdigest(),
        key_ref_sha256=hashlib.sha256(b"key_handle_1").hexdigest(),
        approved_at_epoch_ms=NOW,
        expires_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS)
    evidence = [build_precondition_evidence(
        plan_id=plan["planId"], target_ref=TARGET,
        target_fingerprint_sha256=fingerprint, snapshot_sha256=SNAPSHOT,
        check_id=check, observed_at_epoch_ms=NOW, outcome="PASS",
        evidence_sha256=digest(check)) for check in PRECONDITIONS]
    receipt = authorize_rehearsal_runner(
        plan=plan, target_ref=TARGET, target_fingerprint_sha256=fingerprint,
        snapshot_sha256=SNAPSHOT, evidence=evidence,
        owner_approval=approval, assessed_at_epoch_ms=NOW + 1)
    boundary = build_runner_boundary(
        plan=plan, receipt=receipt, snapshot_ref="snapshot_ref_1",
        key_ref="key_handle_1")
    return plan, approval, receipt, boundary


def consume(ledger, fixture_value=None, **changes):
    plan, approval, receipt, boundary = fixture_value or fixture()
    args = dict(
        plan=plan, receipt=receipt, owner_approval=approval, boundary=boundary,
        snapshot_ref="snapshot_ref_1", key_ref="key_handle_1",
        replay_claim_id=CLAIM_ID,
        invocation_identity_sha256=digest("invocation-1"),
        invoked_at_epoch_ms=NOW + 2)
    args.update(changes)
    return ledger.consume(**args)


def test_consume_is_durable_and_second_invocation_is_blocked():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "receipt-ledger.db")
        ledger = SQLiteE4RehearsalReceiptLedger(path)
        first = consume(ledger)
        assert first["status"] == "CONSUMED"
        assert first["rehearsalInvocationAllowed"] is True
        assert first["moneyActionAllowed"] is False
        assert first["executionEffect"] == "NONE"
        second = consume(ledger, invocation_identity_sha256=digest("invocation-2"))
        assert second == {
            "status": "REPLAY_BLOCKED", "consumptionId": first["consumptionId"],
            "replayClaimId": CLAIM_ID, "planId": first["planId"],
            "targetRef": TARGET, "snapshotSha256": SNAPSHOT,
            "boundaryId": first["boundaryId"],
            "rehearsalInvocationAllowed": False, "moneyActionAllowed": False,
            "executionEffect": "NONE",
            "actionAllowed": False,
        }


def test_concurrent_claims_have_one_winner_and_one_replay_block():
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteE4RehearsalReceiptLedger(str(Path(directory) / "ledger.db"))
        results, errors = [], []
        def run(index):
            try:
                results.append(consume(ledger, invocation_identity_sha256=digest(
                    f"invocation-{index}")))
            except Exception as exc:  # pragma: no cover - diagnostic assertion below
                errors.append(exc)
        threads = [threading.Thread(target=run, args=(index,)) for index in (1, 2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert errors == []
        assert sorted(item["status"] for item in results) == ["CONSUMED", "REPLAY_BLOCKED"]


def test_fault_before_commit_rolls_back_and_fault_after_commit_blocks_retry():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "fault.db")
        def fail(): raise RuntimeError("injected")
        before = SQLiteE4RehearsalReceiptLedger(path, fault_before_commit=fail)
        with pytest.raises(RuntimeError): consume(before)
        assert consume(SQLiteE4RehearsalReceiptLedger(path))["status"] == "CONSUMED"
        after = SQLiteE4RehearsalReceiptLedger(
            str(Path(directory) / "after.db"), fault_after_commit=fail)
        with pytest.raises(RuntimeError): consume(after)
        retry = SQLiteE4RehearsalReceiptLedger(str(Path(directory) / "after.db"))
        retry_result = consume(retry)
        assert retry_result
        assert retry_result["status"] == "REPLAY_BLOCKED"


def test_owner_window_and_exact_boundary_binding_are_required():
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteE4RehearsalReceiptLedger(str(Path(directory) / "binding.db"))
        plan, approval, receipt, boundary = fixture()
        with pytest.raises(ValueError, match="window"):
            consume(ledger, (plan, approval, receipt, boundary),
                    invoked_at_epoch_ms=approval["expiresAtEpochMs"] + 1)
        changed = copy.deepcopy(boundary)
        changed["target"]["network"] = "host"
        with pytest.raises(ValueError):
            consume(ledger, (plan, approval, receipt, changed))
        with pytest.raises(ValueError, match="references"):
            consume(ledger, (plan, approval, receipt, boundary),
                    snapshot_ref="snapshot_ref_2")


def test_record_is_closed_and_tamper_evident():
    _, _, receipt, boundary = fixture()
    record = build_consumption_record(
        receipt=receipt, boundary=boundary, replay_claim_id=CLAIM_ID,
        invocation_identity_sha256=digest("invocation-1"), invoked_at_epoch_ms=NOW + 2)
    assert validate_consumption_record(record) == record
    changed = copy.deepcopy(record); changed["actionAllowed"] = True
    with pytest.raises(ValueError): validate_consumption_record(changed)


def test_path_and_source_surface_are_rehearsal_only():
    with pytest.raises(ValueError): SQLiteE4RehearsalReceiptLedger("/root/exchange.db")
    source = (ROOT / "relay/core/e4_rehearsal_receipt_consumption.py").read_text().lower()
    for forbidden in ("psycopg", "docker", "subprocess", "socket", "requests",
                      "httpx", "fastapi", "systemctl", "os.environ",
                      "obsidian-postgres"):
        assert forbidden not in source
