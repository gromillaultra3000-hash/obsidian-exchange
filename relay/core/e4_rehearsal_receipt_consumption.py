"""Test-only durable consume boundary for one E4 rehearsal receipt.

This module is intentionally not a production repository or executor. It can
only use an explicitly temporary SQLite file, consumes one exact receipt once,
and records a replay block before any future runner could be invoked. It has no
container, PostgreSQL, network, environment, secret or production-route
surface.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import Any, Callable, Mapping

from core.e4_rehearsal_runner_authorization import (
    validate_authorization_receipt, validate_owner_approval,
)
from core.e4_rehearsal_runner_boundary import (
    validate_runner_boundary,
)
from core.e4_rehearsal_runner_plan import validate_rehearsal_runner_plan

SCHEMA = "e4-rehearsal-runner-receipt-consumption.v1"
MAX_FUTURE_SKEW_MS = 1_000
_TABLE = "e4_rehearsal_receipt_consumptions"


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} is invalid")
    return value


def _replay_claim(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("e4orr_") \
            or len(value) != 70 \
            or any(char not in "0123456789abcdef" for char in value[6:]):
        raise ValueError("replayClaimId is invalid")
    return value


def _temporary_db_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ledger path is invalid")
    path = os.path.realpath(os.path.abspath(value))
    allowed = path == "/tmp" or path.startswith("/tmp/") \
        or path == "/var/tmp" or path.startswith("/var/tmp/")
    lowered = path.lower()
    if not allowed or any(marker in lowered for marker in (
            "exchange.db", "obsidian", "postgres", "production", "database_url")):
        raise ValueError("ledger path is not an explicitly temporary rehearsal path")
    return path


def _boundary_digest(boundary: Mapping[str, Any]) -> str:
    return _hash(dict(boundary))


def build_consumption_record(*, receipt: Mapping[str, Any],
                             boundary: Mapping[str, Any],
                             replay_claim_id: str,
                             invocation_identity_sha256: str,
                             invoked_at_epoch_ms: int) -> dict[str, Any]:
    frozen = validate_authorization_receipt(receipt)
    if frozen["status"] != "ELIGIBLE" \
            or frozen["rehearsalExecutionEligible"] is not True:
        raise ValueError("only an eligible receipt can be consumed")
    invocation = _digest(invocation_identity_sha256, "invocationIdentitySha256")
    replay_claim = _replay_claim(replay_claim_id)
    invoked = _epoch(invoked_at_epoch_ms, "invokedAtEpochMs")
    if invoked < frozen["approvalApprovedAtEpochMs"] - MAX_FUTURE_SKEW_MS \
            or invoked > frozen["approvalExpiresAtEpochMs"]:
        raise ValueError("receipt is outside the owner approval window")
    unsigned = {
        "schemaVersion": SCHEMA,
        "receiptId": frozen["receiptId"],
        "planId": frozen["planId"],
        "targetRef": frozen["targetRef"],
        "snapshotSha256": frozen["snapshotSha256"],
        "boundaryId": boundary["boundaryId"],
        "boundarySha256": _boundary_digest(boundary),
        "replayClaimId": replay_claim,
        "invocationIdentitySha256": invocation,
        "invokedAtEpochMs": invoked,
        "consumptionCount": 1,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "consumptionId": "e4rrc_" + _hash(unsigned)}


def validate_consumption_record(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "consumptionId", "receiptId", "planId", "targetRef",
        "snapshotSha256", "boundaryId", "boundarySha256",
        "replayClaimId",
        "invocationIdentitySha256", "invokedAtEpochMs", "consumptionCount",
        "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != fields \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("consumptionCount") != 1 \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("consumption record schema is invalid")
    for field in ("snapshotSha256", "boundarySha256", "invocationIdentitySha256"):
        _digest(value.get(field), field)
    _replay_claim(value.get("replayClaimId"))
    _epoch(value.get("invokedAtEpochMs"), "invokedAtEpochMs")
    if not isinstance(value.get("receiptId"), str) \
            or not value["receiptId"].startswith("e4rrar_") \
            or not isinstance(value.get("planId"), str) \
            or not isinstance(value.get("targetRef"), str) \
            or not isinstance(value.get("boundaryId"), str):
        raise ValueError("consumption record binding is invalid")
    unsigned = dict(value)
    identifier = unsigned.pop("consumptionId", None)
    if identifier != "e4rrc_" + _hash(unsigned):
        raise ValueError("consumption record hash differs")
    return dict(value)


class SQLiteE4RehearsalReceiptLedger:
    """A disposable, single-use ledger for a test-only rehearsal invocation."""

    def __init__(self, path: str, *, timeout: float = 10,
                 fault_before_commit: Callable[[], None] | None = None,
                 fault_after_commit: Callable[[], None] | None = None):
        self.path = _temporary_db_path(path)
        self.timeout = timeout
        self.fault_before_commit = fault_before_commit
        self.fault_after_commit = fault_after_commit

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=self.timeout)
        connection.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(f"""
            CREATE TABLE IF NOT EXISTS {_TABLE}(
              receipt_id TEXT PRIMARY KEY,
              consumption_id TEXT NOT NULL UNIQUE,
              record_json TEXT NOT NULL,
              consumed_at_epoch_ms INTEGER NOT NULL,
              state TEXT NOT NULL CHECK(state='CONSUMED'))
        """)

    def consume(self, *, plan: Mapping[str, Any], receipt: Mapping[str, Any],
                owner_approval: Mapping[str, Any], boundary: Mapping[str, Any],
                snapshot_ref: str, key_ref: str,
                replay_claim_id: str,
                invocation_identity_sha256: str,
                invoked_at_epoch_ms: int) -> dict[str, Any]:
        frozen_plan = validate_rehearsal_runner_plan(plan)
        frozen_receipt = validate_authorization_receipt(receipt)
        approval = validate_owner_approval(owner_approval)
        if (approval["approvalId"], approval["planId"], approval["targetRef"],
                approval["targetFingerprintSha256"], approval["snapshotSha256"]) != (
                    frozen_receipt["approvalId"], frozen_receipt["planId"],
                    frozen_receipt["targetRef"], frozen_receipt["targetFingerprintSha256"],
                    frozen_receipt["snapshotSha256"]):
            raise ValueError("receipt and owner approval binding differs")
        if (frozen_receipt["approvalApprovedAtEpochMs"],
                frozen_receipt["approvalExpiresAtEpochMs"]) != (
                    approval["approvedAtEpochMs"], approval["expiresAtEpochMs"]):
            raise ValueError("receipt and owner approval window differs")
        frozen_boundary = validate_runner_boundary(
            boundary, plan=frozen_plan, receipt=frozen_receipt,
            snapshot_ref=snapshot_ref, key_ref=key_ref)
        record = build_consumption_record(
            receipt=frozen_receipt, boundary=frozen_boundary,
            replay_claim_id=replay_claim_id,
            invocation_identity_sha256=invocation_identity_sha256,
            invoked_at_epoch_ms=invoked_at_epoch_ms)
        encoded = json.dumps(record, ensure_ascii=True, sort_keys=True,
                             separators=(",", ":"))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._ensure_schema(connection)
            existing = connection.execute(
                f"SELECT record_json FROM {_TABLE} WHERE receipt_id=?",
                (frozen_receipt["receiptId"],)).fetchone()
            if existing:
                try:
                    prior = validate_consumption_record(json.loads(existing[0]))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    connection.rollback()
                    raise ValueError("consumption ledger integrity failure") from exc
                connection.rollback()
                if prior["receiptId"] == record["receiptId"]:
                    return {
                        "status": "REPLAY_BLOCKED", "consumptionId": prior["consumptionId"],
                        "replayClaimId": prior["replayClaimId"],
                        "planId": prior["planId"], "targetRef": prior["targetRef"],
                        "snapshotSha256": prior["snapshotSha256"],
                        "boundaryId": prior["boundaryId"],
                        "rehearsalInvocationAllowed": False, "moneyActionAllowed": False,
                        "executionEffect": "NONE",
                        "actionAllowed": False,
                    }
                raise ValueError("consumption ledger receipt conflict")
            connection.execute(
                f"INSERT INTO {_TABLE}(receipt_id,consumption_id,record_json,"
                "consumed_at_epoch_ms,state) VALUES(?,?,?,?, 'CONSUMED')",
                (record["receiptId"], record["consumptionId"], encoded,
                 record["invokedAtEpochMs"]))
            if self.fault_before_commit:
                self.fault_before_commit()
            connection.commit()
        if self.fault_after_commit:
            self.fault_after_commit()
        return {
            "status": "CONSUMED", "consumptionId": record["consumptionId"],
            "replayClaimId": record["replayClaimId"],
            "planId": record["planId"], "targetRef": record["targetRef"],
            "snapshotSha256": record["snapshotSha256"],
            "boundaryId": record["boundaryId"],
            "rehearsalInvocationAllowed": True, "moneyActionAllowed": False,
            "executionEffect": "NONE",
            "actionAllowed": False,
        }
