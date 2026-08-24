"""Pure target-bound authorization contract for one E4 rehearsal invocation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from core.e4_rehearsal_runner_plan import (
    PRECONDITIONS, validate_rehearsal_runner_plan,
)

EVIDENCE_SCHEMA = "e4-rehearsal-runner-precondition-evidence.v1"
APPROVAL_SCHEMA = "e4-rehearsal-runner-owner-approval.v1"
RECEIPT_SCHEMA = "e4-rehearsal-runner-authorization-receipt.v1"
MAX_AUTHORIZATION_MS = 30 * 60 * 1000
MAX_EVIDENCE_AGE_MS = 10 * 60 * 1000
FUTURE_SKEW_MS = 1_000


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _token(value: Any, field: str, maximum: int = 96) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} is invalid")
    return value


def build_precondition_evidence(*, plan_id: str, target_ref: str,
                                target_fingerprint_sha256: str,
                                snapshot_sha256: str, check_id: str,
                                observed_at_epoch_ms: int, outcome: str,
                                evidence_sha256: str) -> dict[str, Any]:
    if check_id not in PRECONDITIONS or outcome not in {"PASS", "FAIL", "UNAVAILABLE"}:
        raise ValueError("precondition evidence verdict is invalid")
    unsigned = {
        "schemaVersion": EVIDENCE_SCHEMA,
        "planId": _token(plan_id, "planId"),
        "targetRef": _token(target_ref, "targetRef"),
        "targetFingerprintSha256": _digest(
            target_fingerprint_sha256, "targetFingerprintSha256"),
        "snapshotSha256": _digest(snapshot_sha256, "snapshotSha256"),
        "checkId": check_id,
        "observedAtEpochMs": _epoch(observed_at_epoch_ms, "observedAtEpochMs"),
        "outcome": outcome,
        "evidenceSha256": _digest(evidence_sha256, "evidenceSha256"),
        "containsSecrets": False, "containsConnectionMaterial": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "evidenceId": "e4rrpe_" + _hash(unsigned)}


def validate_precondition_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "evidenceId", "planId", "targetRef",
        "targetFingerprintSha256", "snapshotSha256", "checkId",
        "observedAtEpochMs", "outcome", "evidenceSha256", "containsSecrets",
        "containsConnectionMaterial", "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != fields \
            or value.get("schemaVersion") != EVIDENCE_SCHEMA \
            or value.get("containsSecrets") is not False \
            or value.get("containsConnectionMaterial") is not False \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("precondition evidence schema is invalid")
    rebuilt = build_precondition_evidence(
        plan_id=value["planId"], target_ref=value["targetRef"],
        target_fingerprint_sha256=value["targetFingerprintSha256"],
        snapshot_sha256=value["snapshotSha256"], check_id=value["checkId"],
        observed_at_epoch_ms=value["observedAtEpochMs"], outcome=value["outcome"],
        evidence_sha256=value["evidenceSha256"])
    if rebuilt != dict(value):
        raise ValueError("precondition evidence hash differs")
    return rebuilt


def build_owner_approval(*, approval_ref: str, plan_id: str, target_ref: str,
                         target_fingerprint_sha256: str, snapshot_sha256: str,
                         snapshot_ref_sha256: str, key_ref_sha256: str,
                         approved_at_epoch_ms: int,
                         expires_at_epoch_ms: int) -> dict[str, Any]:
    approved = _epoch(approved_at_epoch_ms, "approvedAtEpochMs")
    expires = _epoch(expires_at_epoch_ms, "expiresAtEpochMs")
    if not approved < expires <= approved + MAX_AUTHORIZATION_MS:
        raise ValueError("owner approval lifetime is invalid")
    unsigned = {
        "schemaVersion": APPROVAL_SCHEMA,
        "approvalRef": _token(approval_ref, "approvalRef"),
        "planId": _token(plan_id, "planId"),
        "targetRef": _token(target_ref, "targetRef"),
        "targetFingerprintSha256": _digest(
            target_fingerprint_sha256, "targetFingerprintSha256"),
        "snapshotSha256": _digest(snapshot_sha256, "snapshotSha256"),
        "snapshotRefSha256": _digest(snapshot_ref_sha256, "snapshotRefSha256"),
        "keyRefSha256": _digest(key_ref_sha256, "keyRefSha256"),
        "approvedAtEpochMs": approved, "expiresAtEpochMs": expires,
        "scope": "ONE_E4_ISOLATED_FULL_SNAPSHOT_REHEARSAL",
        "invocationLimit": 1, "productionDatabaseContactAllowed": False,
        "productionNetworkAllowed": False, "productionCredentialsAllowed": False,
        "proposalApplicationAllowed": False, "persistentTargetAllowed": False,
        "automaticRetryAllowed": False, "containsSecrets": False,
        "containsConnectionMaterial": False, "executionEffect": "NONE",
        "promotionAllowed": False, "actionAllowed": False,
    }
    return {**unsigned, "approvalId": "e4rroa_" + _hash(unsigned)}


def validate_owner_approval(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "approvalId", "approvalRef", "planId", "targetRef",
        "targetFingerprintSha256", "snapshotSha256", "snapshotRefSha256",
        "keyRefSha256", "approvedAtEpochMs",
        "expiresAtEpochMs", "scope", "invocationLimit",
        "productionDatabaseContactAllowed", "productionNetworkAllowed",
        "productionCredentialsAllowed", "proposalApplicationAllowed",
        "persistentTargetAllowed", "automaticRetryAllowed", "containsSecrets",
        "containsConnectionMaterial", "executionEffect", "promotionAllowed",
        "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != fields \
            or value.get("schemaVersion") != APPROVAL_SCHEMA \
            or value.get("scope") != "ONE_E4_ISOLATED_FULL_SNAPSHOT_REHEARSAL" \
            or value.get("invocationLimit") != 1 \
            or any(value.get(field) is not False for field in (
                "productionDatabaseContactAllowed", "productionNetworkAllowed",
                "productionCredentialsAllowed", "proposalApplicationAllowed",
                "persistentTargetAllowed", "automaticRetryAllowed", "containsSecrets",
                "containsConnectionMaterial", "promotionAllowed", "actionAllowed")) \
            or value.get("executionEffect") != "NONE":
        raise ValueError("owner approval schema is invalid")
    rebuilt = build_owner_approval(
        approval_ref=value["approvalRef"], plan_id=value["planId"],
        target_ref=value["targetRef"],
        target_fingerprint_sha256=value["targetFingerprintSha256"],
        snapshot_sha256=value["snapshotSha256"],
        snapshot_ref_sha256=value["snapshotRefSha256"],
        key_ref_sha256=value["keyRefSha256"],
        approved_at_epoch_ms=value["approvedAtEpochMs"],
        expires_at_epoch_ms=value["expiresAtEpochMs"])
    if rebuilt != dict(value):
        raise ValueError("owner approval hash differs")
    return rebuilt


def authorize_rehearsal_runner(*, plan: Mapping[str, Any], target_ref: str,
                               target_fingerprint_sha256: str,
                               snapshot_sha256: str,
                               evidence: Iterable[Mapping[str, Any]],
                               owner_approval: Mapping[str, Any],
                               assessed_at_epoch_ms: int) -> dict[str, Any]:
    frozen = validate_rehearsal_runner_plan(plan)
    target = _token(target_ref, "targetRef")
    fingerprint = _digest(target_fingerprint_sha256, "targetFingerprintSha256")
    snapshot = _digest(snapshot_sha256, "snapshotSha256")
    assessed = _epoch(assessed_at_epoch_ms, "assessedAtEpochMs")
    approval = validate_owner_approval(owner_approval)
    binding = (frozen["planId"], target, fingerprint, snapshot)
    if (approval["planId"], approval["targetRef"],
            approval["targetFingerprintSha256"], approval["snapshotSha256"]) != binding:
        raise ValueError("owner approval binding is invalid")
    items = [validate_precondition_evidence(item) for item in evidence]
    if len(items) != len(PRECONDITIONS) \
            or len({item["checkId"] for item in items}) != len(PRECONDITIONS):
        raise ValueError("precondition evidence set is incomplete or duplicated")
    if any((item["planId"], item["targetRef"], item["targetFingerprintSha256"],
            item["snapshotSha256"]) != binding for item in items):
        raise ValueError("precondition evidence binding is invalid")
    by_check = {item["checkId"]: item for item in items}
    blockers = [check for check in PRECONDITIONS
                if by_check[check]["outcome"] != "PASS"]
    for check in PRECONDITIONS:
        age = assessed - by_check[check]["observedAtEpochMs"]
        if age < -FUTURE_SKEW_MS:
            blockers.append(f"{check}_FROM_FUTURE")
        elif age > MAX_EVIDENCE_AGE_MS:
            blockers.append(f"{check}_STALE")
    if not approval["approvedAtEpochMs"] <= assessed <= approval["expiresAtEpochMs"]:
        blockers.append("OWNER_APPROVAL_NOT_CURRENT")
    eligible = not blockers
    unsigned = {
        "schemaVersion": RECEIPT_SCHEMA, "planId": frozen["planId"],
        "targetRef": target, "targetFingerprintSha256": fingerprint,
        "snapshotSha256": snapshot, "approvalId": approval["approvalId"],
        "snapshotRefSha256": approval["snapshotRefSha256"],
        "keyRefSha256": approval["keyRefSha256"],
        "approvalApprovedAtEpochMs": approval["approvedAtEpochMs"],
        "approvalExpiresAtEpochMs": approval["expiresAtEpochMs"],
        "assessedAtEpochMs": assessed, "status": "ELIGIBLE" if eligible else "NO_GO",
        "blockers": blockers, "evidenceIds": [by_check[item]["evidenceId"]
                                              for item in PRECONDITIONS],
        "rehearsalExecutionEligible": eligible, "invocationLimit": 1,
        "productionDatabaseContactAllowed": False, "productionNetworkAllowed": False,
        "productionCredentialsAllowed": False, "proposalApplicationAllowed": False,
        "persistentTargetAllowed": False, "automaticRetryAllowed": False,
        "containsSecrets": False, "containsConnectionMaterial": False,
        "promotionAllowed": False, "actionAllowed": False,
        "executionEffect": "NONE",
    }
    return {**unsigned, "receiptId": "e4rrar_" + _hash(unsigned)}


def validate_authorization_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "receiptId", "planId", "targetRef",
        "targetFingerprintSha256", "snapshotSha256", "approvalId",
        "snapshotRefSha256", "keyRefSha256",
        "approvalApprovedAtEpochMs", "approvalExpiresAtEpochMs",
        "assessedAtEpochMs", "status", "blockers", "evidenceIds",
        "rehearsalExecutionEligible", "invocationLimit",
        "productionDatabaseContactAllowed", "productionNetworkAllowed",
        "productionCredentialsAllowed", "proposalApplicationAllowed",
        "persistentTargetAllowed", "automaticRetryAllowed", "containsSecrets",
        "containsConnectionMaterial", "promotionAllowed", "actionAllowed",
        "executionEffect",
    }
    if not isinstance(value, Mapping) or set(value) != fields \
            or value.get("schemaVersion") != RECEIPT_SCHEMA \
            or value.get("status") not in {"ELIGIBLE", "NO_GO"} \
            or type(value.get("rehearsalExecutionEligible")) is not bool \
            or value.get("invocationLimit") != 1 \
            or any(value.get(field) is not False for field in (
                "productionDatabaseContactAllowed", "productionNetworkAllowed",
                "productionCredentialsAllowed", "proposalApplicationAllowed",
                "persistentTargetAllowed", "automaticRetryAllowed", "containsSecrets",
                "containsConnectionMaterial", "promotionAllowed", "actionAllowed")) \
            or value.get("executionEffect") != "NONE" \
            or not isinstance(value.get("blockers"), list) \
            or not isinstance(value.get("evidenceIds"), list) \
            or len(value["evidenceIds"]) != len(PRECONDITIONS) \
            or len(set(value["evidenceIds"])) != len(PRECONDITIONS):
        raise ValueError("authorization receipt schema is invalid")
    eligible = not value["blockers"]
    if value["rehearsalExecutionEligible"] != eligible \
            or value["status"] != ("ELIGIBLE" if eligible else "NO_GO"):
        raise ValueError("authorization receipt verdict is inconsistent")
    _token(value["planId"], "planId")
    _token(value["targetRef"], "targetRef")
    _digest(value["targetFingerprintSha256"], "targetFingerprintSha256")
    _digest(value["snapshotSha256"], "snapshotSha256")
    _digest(value["snapshotRefSha256"], "snapshotRefSha256")
    _digest(value["keyRefSha256"], "keyRefSha256")
    _epoch(value["approvalApprovedAtEpochMs"], "approvalApprovedAtEpochMs")
    _epoch(value["approvalExpiresAtEpochMs"], "approvalExpiresAtEpochMs")
    _epoch(value["assessedAtEpochMs"], "assessedAtEpochMs")
    if not value["approvalApprovedAtEpochMs"] < value["approvalExpiresAtEpochMs"] \
            or value["approvalExpiresAtEpochMs"] > (
                value["approvalApprovedAtEpochMs"] + MAX_AUTHORIZATION_MS) \
            or value["assessedAtEpochMs"] < value["approvalApprovedAtEpochMs"] \
            or value["assessedAtEpochMs"] > value["approvalExpiresAtEpochMs"]:
        raise ValueError("authorization receipt approval window is invalid")
    unsigned = dict(value); identifier = unsigned.pop("receiptId", None)
    if identifier != "e4rrar_" + _hash(unsigned):
        raise ValueError("authorization receipt hash differs")
    return dict(value)
