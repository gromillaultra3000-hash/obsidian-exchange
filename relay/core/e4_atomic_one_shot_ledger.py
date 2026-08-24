"""Atomic replay and receipt ledger for one E4 one-shot invocation.

The authoritative gate calls ``claim`` and then ``consume``.  This adapter
keeps both inserts in one SQLite transaction and commits only after the formal
receipt is valid.  A crash or exception between the calls rolls the replay row
back instead of leaving a consumed authorization without a receipt.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from core.e4_owner_reviewer_replay_registry import (
    MAX_FUTURE_SKEW_MS,
    _require_eligible_verification,
    _temporary_db_path,
    build_claim_record,
)
from core.e4_rehearsal_receipt_consumption import build_consumption_record
from core.e4_rehearsal_runner_authorization import (
    validate_authorization_receipt,
    validate_owner_approval,
)
from core.e4_rehearsal_runner_boundary import validate_runner_boundary
from core.e4_rehearsal_runner_plan import validate_rehearsal_runner_plan


REPLAY_TABLE = "e4_owner_reviewer_replay_claims"
RECEIPT_TABLE = "e4_rehearsal_receipt_consumptions"


class AtomicOneShotLedgerError(ValueError):
    """An atomic one-shot ledger validation or state error."""


class AtomicE4OneShotLedger:
    """Expose replay/receipt callbacks backed by one uncommitted transaction."""

    def __init__(self, path: str, *, timeout: float = 10):
        self.path = _temporary_db_path(path)
        self.timeout = timeout
        self.connection: sqlite3.Connection | None = None
        self.claim_record: dict[str, Any] | None = None
        self.committed = False

    def _open(self) -> sqlite3.Connection:
        if self.connection is not None:
            raise AtomicOneShotLedgerError("one-shot transaction is already open")
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        connection.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {REPLAY_TABLE} ("
            "claim_key TEXT PRIMARY KEY, payload_id TEXT NOT NULL UNIQUE, "
            "envelope_id TEXT NOT NULL UNIQUE, artifact_digest TEXT NOT NULL, "
            "record_json TEXT NOT NULL, claimed_at_epoch_ms INTEGER NOT NULL, "
            "state TEXT NOT NULL CHECK(state='CONSUMED'))")
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {RECEIPT_TABLE} ("
            "receipt_id TEXT PRIMARY KEY, consumption_id TEXT NOT NULL UNIQUE, "
            "record_json TEXT NOT NULL, consumed_at_epoch_ms INTEGER NOT NULL, "
            "state TEXT NOT NULL CHECK(state='CONSUMED'))")
        self.connection = connection
        return connection

    def claim(self, *, verification_result: Mapping[str, Any], payload_id: str,
              envelope_id: str, artifact_digest: str,
              claimed_at_epoch_ms: int) -> dict[str, Any]:
        _require_eligible_verification(verification_result)
        record = build_claim_record(
            payload_id=payload_id, envelope_id=envelope_id,
            artifact_digest=artifact_digest,
            verification_id=verification_result["verificationId"],
            claimed_at_epoch_ms=claimed_at_epoch_ms)
        if claimed_at_epoch_ms < verification_result["evaluatedAtEpochMs"] \
                - MAX_FUTURE_SKEW_MS:
            raise AtomicOneShotLedgerError(
                "claim timestamp predates verification")
        connection = self._open()
        try:
            prior = connection.execute(
                f"SELECT 1 FROM {REPLAY_TABLE} WHERE claim_key=? OR "
                "payload_id=? OR envelope_id=?",
                (record["claimKey"], record["payloadId"],
                 record["envelopeId"])).fetchone()
            if prior:
                raise AtomicOneShotLedgerError("one-shot replay already exists")
            connection.execute(
                f"INSERT INTO {REPLAY_TABLE} (claim_key,payload_id,envelope_id,"
                "artifact_digest,record_json,claimed_at_epoch_ms,state) "
                "VALUES (?,?,?,?,?,?,'CONSUMED')",
                (record["claimKey"], record["payloadId"], record["envelopeId"],
                 record["artifactDigest"], json.dumps(record, sort_keys=True),
                 record["claimedAtEpochMs"]))
        except Exception:
            self.close()
            raise
        self.claim_record = record
        return {
            "status": "CONSUMED", "claimId": record["claimId"],
            "replayClaimAllowed": True, "executionEffect": "NONE",
            "actionAllowed": False,
        }

    def consume(self, *, plan: Mapping[str, Any], receipt: Mapping[str, Any],
                owner_approval: Mapping[str, Any], boundary: Mapping[str, Any],
                snapshot_ref: str, key_ref: str, replay_claim_id: str,
                invocation_identity_sha256: str,
                invoked_at_epoch_ms: int) -> dict[str, Any]:
        if self.connection is None or self.claim_record is None \
                or self.committed:
            raise AtomicOneShotLedgerError("replay claim transaction is not pending")
        frozen_plan = validate_rehearsal_runner_plan(plan)
        frozen_receipt = validate_authorization_receipt(receipt)
        approval = validate_owner_approval(owner_approval)
        if (approval["approvalId"], approval["planId"], approval["targetRef"],
                approval["targetFingerprintSha256"], approval["snapshotSha256"]) != (
                    frozen_receipt["approvalId"], frozen_receipt["planId"],
                    frozen_receipt["targetRef"],
                    frozen_receipt["targetFingerprintSha256"],
                    frozen_receipt["snapshotSha256"]):
            self.close()
            raise AtomicOneShotLedgerError("receipt and owner approval differ")
        if (frozen_receipt["approvalApprovedAtEpochMs"],
                frozen_receipt["approvalExpiresAtEpochMs"]) != (
                    approval["approvedAtEpochMs"], approval["expiresAtEpochMs"]):
            self.close()
            raise AtomicOneShotLedgerError("receipt and approval window differ")
        frozen_boundary = validate_runner_boundary(
            boundary, plan=frozen_plan, receipt=frozen_receipt,
            snapshot_ref=snapshot_ref, key_ref=key_ref)
        record = build_consumption_record(
            receipt=frozen_receipt, boundary=frozen_boundary,
            replay_claim_id=replay_claim_id,
            invocation_identity_sha256=invocation_identity_sha256,
            invoked_at_epoch_ms=invoked_at_epoch_ms)
        if replay_claim_id != self.claim_record["claimId"]:
            self.close()
            raise AtomicOneShotLedgerError("receipt replay claim differs")
        try:
            self.connection.execute(
                f"INSERT INTO {RECEIPT_TABLE} (receipt_id,consumption_id,"
                "record_json,consumed_at_epoch_ms,state) VALUES (?,?,?,?,'CONSUMED')",
                (record["receiptId"], record["consumptionId"],
                 json.dumps(record, sort_keys=True), record["invokedAtEpochMs"]))
            self.connection.commit()
            self.committed = True
            directory_fd = os.open(Path(self.path).parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            self.close()
            raise
        self.connection.close()
        self.connection = None
        return {
            "status": "CONSUMED", "consumptionId": record["consumptionId"],
            "replayClaimId": record["replayClaimId"],
            "planId": record["planId"], "targetRef": record["targetRef"],
            "snapshotSha256": record["snapshotSha256"],
            "boundaryId": record["boundaryId"],
            "rehearsalInvocationAllowed": True, "moneyActionAllowed": False,
            "executionEffect": "NONE", "actionAllowed": False,
        }

    def close(self) -> None:
        if self.connection is not None:
            try:
                if not self.committed:
                    self.connection.rollback()
            finally:
                self.connection.close()
                self.connection = None

    def __enter__(self) -> "AtomicE4OneShotLedger":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
