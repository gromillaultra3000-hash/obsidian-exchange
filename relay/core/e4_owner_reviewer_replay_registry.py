"""Temporary one-shot replay registry for an authenticated E4 handoff.

The registry is a claim ledger, not an authorization source.  It refuses the
current evidence-only verifier result unless a future authenticated verifier
explicitly sets ``replayEligible``.  The path is restricted to an explicitly
temporary rehearsal directory and the claim is committed before any executor
could be called.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping


SCHEMA = "e4-owner-reviewer-replay-registry.v1"
_TABLE = "e4_owner_reviewer_replay_claims"
MAX_FUTURE_SKEW_MS = 1_000


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _token(value: Any, field: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} is invalid")
    return value


def _temporary_db_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("registry path is invalid")
    path = os.path.realpath(os.path.abspath(value))
    allowed = path == "/tmp" or path.startswith("/tmp/") \
        or path == "/var/tmp" or path.startswith("/var/tmp/")
    lowered = path.lower()
    if not allowed or any(marker in lowered for marker in (
            "exchange.db", "obsidian", "postgres", "production", "database_url")):
        raise ValueError("registry path is not explicitly temporary")
    return path


def _claim_key(*, payload_id: str, envelope_id: str,
               artifact_digest: str) -> str:
    return _hash({
        "payloadId": payload_id,
        "envelopeId": envelope_id,
        "artifactDigest": artifact_digest,
    })


def build_claim_record(*, payload_id: str, envelope_id: str,
                       artifact_digest: str, verification_id: str,
                       claimed_at_epoch_ms: int) -> dict[str, Any]:
    payload = _token(payload_id, "payloadId")
    envelope = _token(envelope_id, "envelopeId")
    artifact = _digest(artifact_digest, "artifactDigest")
    verification = _token(verification_id, "verificationId")
    claimed = _epoch(claimed_at_epoch_ms, "claimedAtEpochMs")
    unsigned = {
        "schemaVersion": SCHEMA,
        "claimKey": _claim_key(payload_id=payload, envelope_id=envelope,
                                artifact_digest=artifact),
        "payloadId": payload,
        "envelopeId": envelope,
        "artifactDigest": artifact,
        "verificationId": verification,
        "claimedAtEpochMs": claimed,
        "claimCount": 1,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "claimId": "e4orr_" + _hash(unsigned)}


def validate_claim_record(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "claimId", "claimKey", "payloadId", "envelopeId",
        "artifactDigest", "verificationId", "claimedAtEpochMs", "claimCount",
        "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != fields \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("claimCount") != 1 \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("replay claim schema is invalid")
    rebuilt = build_claim_record(
        payload_id=value["payloadId"], envelope_id=value["envelopeId"],
        artifact_digest=value["artifactDigest"],
        verification_id=value["verificationId"],
        claimed_at_epoch_ms=value["claimedAtEpochMs"])
    if rebuilt != dict(value):
        raise ValueError("replay claim hash differs")
    return rebuilt


def _require_eligible_verification(value: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) \
            or value.get("schemaVersion") != "e4-owner-reviewer-verification-result.v1" \
            or value.get("replayEligible") is not True \
            or value.get("ownerSignatureVerified") is not True \
            or value.get("reviewerSignatureVerified") is not True \
            or value.get("exactBindingVerified") is not True \
            or value.get("freshnessVerified") is not True \
            or value.get("registryStatus") != "AUTHENTICATED_ACTIVE" \
            or value.get("trustedClockAttested") is not True \
            or value.get("status") != "VERIFIED" \
            or value.get("executionAuthorized") is not False \
            or value.get("actionAllowed") is not False:
        raise ValueError("verification result is not replay-eligible")
    _token(value.get("verificationId"), "verificationId")
    _epoch(value.get("evaluatedAtEpochMs"), "evaluatedAtEpochMs")


class SQLiteE4OwnerReviewerReplayRegistry:
    """Explicitly temporary, atomic one-shot claim registry."""

    def __init__(self, path: str, *, timeout: float = 10,
                 fault_before_commit: Callable[[], None] | None = None,
                 fault_after_commit: Callable[[], None] | None = None):
        self.path = _temporary_db_path(path)
        self.timeout = timeout
        self.fault_before_commit = fault_before_commit
        self.fault_after_commit = fault_after_commit
        with sqlite3.connect(self.path, timeout=self.timeout) as connection:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
                "claim_key TEXT PRIMARY KEY, payload_id TEXT NOT NULL UNIQUE, "
                "envelope_id TEXT NOT NULL UNIQUE, artifact_digest TEXT NOT NULL, "
                "record_json TEXT NOT NULL, claimed_at_epoch_ms INTEGER NOT NULL, "
                "state TEXT NOT NULL CHECK(state='CONSUMED'))")
            connection.commit()

    def claim(self, *, verification_result: Mapping[str, Any],
              payload_id: str, envelope_id: str, artifact_digest: str,
              claimed_at_epoch_ms: int) -> dict[str, Any]:
        _require_eligible_verification(verification_result)
        record = build_claim_record(
            payload_id=payload_id, envelope_id=envelope_id,
            artifact_digest=artifact_digest,
            verification_id=verification_result["verificationId"],
            claimed_at_epoch_ms=claimed_at_epoch_ms)
        if claimed_at_epoch_ms < verification_result["evaluatedAtEpochMs"] \
                - MAX_FUTURE_SKEW_MS:
            raise ValueError("claim timestamp predates verification")
        try:
            with sqlite3.connect(self.path, timeout=self.timeout) as connection:
                connection.execute("BEGIN IMMEDIATE")
                prior = connection.execute(
                    f"SELECT claim_key, payload_id, envelope_id, artifact_digest, "
                    f"record_json FROM {_TABLE} WHERE claim_key=? OR payload_id=? "
                    f"OR envelope_id=?", (record["claimKey"], record["payloadId"],
                                           record["envelopeId"])).fetchall()
                if prior:
                    prior_record = json.loads(prior[0][4])
                    prior_claim_id = prior_record["claimId"]
                    if len(prior) != 1 or prior[0][0] != record["claimKey"] \
                            or prior[0][1] != record["payloadId"] \
                            or prior[0][2] != record["envelopeId"] \
                            or prior[0][3] != record["artifactDigest"]:
                        connection.rollback()
                        return {
                            "status": "CONFLICT_BLOCKED",
                            "claimId": prior_claim_id,
                            "replayClaimAllowed": False,
                            "executionEffect": "NONE",
                            "actionAllowed": False,
                        }
                    connection.rollback()
                    return {
                        "status": "REPLAY_BLOCKED",
                        "claimId": prior_claim_id,
                        "replayClaimAllowed": False,
                        "executionEffect": "NONE",
                        "actionAllowed": False,
                    }
                connection.execute(
                    f"INSERT INTO {_TABLE} (claim_key, payload_id, envelope_id, "
                    "artifact_digest, record_json, claimed_at_epoch_ms, state) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'CONSUMED')",
                    (record["claimKey"], record["payloadId"], record["envelopeId"],
                     record["artifactDigest"], json.dumps(record, sort_keys=True),
                     record["claimedAtEpochMs"]))
                if self.fault_before_commit:
                    self.fault_before_commit()
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("replay claim uniqueness conflict") from exc
        if self.fault_after_commit:
            self.fault_after_commit()
        return {
            "status": "CONSUMED",
            "claimId": record["claimId"],
            "replayClaimAllowed": True,
            "executionEffect": "NONE",
            "actionAllowed": False,
        }
