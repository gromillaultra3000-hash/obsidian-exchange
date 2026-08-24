"""Pure E5 recovery-completion proposal; never installs wallet authority."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from core.e5_key_boundary import validate_key_boundary
from core.e5_recovery_attempt import validate_recovery_attempt
from core.e5_recovery_policy import validate_recovery_policy

SCHEMA = "native-wallet-recovery-completion-proposal.v1"
MAX_EVIDENCE_AGE_MS = 5 * 60 * 1000
MAX_FUTURE_SKEW_MS = 1_000


def _hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _time(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _evidence(value: Mapping[str, Any], *, kind: str,
              attempt: Mapping[str, Any], observed_at: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{kind} evidence is invalid")
    expected = {
        "evidenceKind", "attemptId", "walletIdentitySha256",
        "targetDeviceIdentitySha256", "proposedRecoveryEpoch",
        "subjectIdentitySha256", "verifierIdentitySha256",
        "verifiedAtEpochMs", "evidenceSha256",
    }
    if set(value) != expected or value.get("evidenceKind") != kind:
        raise ValueError(f"{kind} evidence schema is invalid")
    if value.get("attemptId") != attempt["attemptId"] \
            or value.get("walletIdentitySha256") != attempt["walletIdentitySha256"] \
            or value.get("targetDeviceIdentitySha256") \
            != attempt["targetDeviceIdentitySha256"] \
            or value.get("proposedRecoveryEpoch") \
            != attempt["proposedRecoveryEpoch"]:
        raise ValueError(f"{kind} evidence binding is invalid")
    expected_subject = (attempt["targetDeviceIdentitySha256"]
                        if kind == "NEW_DEVICE_VERIFIED"
                        else attempt["activeDeviceIdentitySha256"])
    if value.get("subjectIdentitySha256") != expected_subject:
        raise ValueError(f"{kind} evidence subject is invalid")
    verifier = _digest(value.get("verifierIdentitySha256"),
                       "verifierIdentitySha256")
    if verifier in {attempt["activeDeviceIdentitySha256"],
                    attempt["targetDeviceIdentitySha256"]}:
        raise ValueError(f"{kind} evidence is not independently verified")
    verified = _time(value.get("verifiedAtEpochMs"), "verifiedAtEpochMs")
    if verified > observed_at + MAX_FUTURE_SKEW_MS \
            or observed_at - verified > MAX_EVIDENCE_AGE_MS:
        raise ValueError(f"{kind} evidence is not fresh")
    unsigned = {key: value[key] for key in value if key != "evidenceSha256"}
    if value.get("evidenceSha256") != _hash(unsigned):
        raise ValueError(f"{kind} evidence hash is invalid")
    return dict(value)


def build_completion_evidence(
        *, evidence_kind: str, attempt: Mapping[str, Any],
        subject_identity_sha256: str, verifier_identity_sha256: str,
        verified_at_epoch_ms: int) -> dict[str, Any]:
    if evidence_kind not in {"NEW_DEVICE_VERIFIED", "PRIOR_DEVICE_REVOCATION_VERIFIED"}:
        raise ValueError("completion evidence kind is invalid")
    unsigned = {
        "evidenceKind": evidence_kind,
        "attemptId": attempt.get("attemptId"),
        "walletIdentitySha256": attempt.get("walletIdentitySha256"),
        "targetDeviceIdentitySha256": attempt.get("targetDeviceIdentitySha256"),
        "proposedRecoveryEpoch": attempt.get("proposedRecoveryEpoch"),
        "subjectIdentitySha256": _digest(subject_identity_sha256,
                                         "subjectIdentitySha256"),
        "verifierIdentitySha256": _digest(verifier_identity_sha256,
                                          "verifierIdentitySha256"),
        "verifiedAtEpochMs": _time(verified_at_epoch_ms, "verifiedAtEpochMs"),
    }
    return {**unsigned, "evidenceSha256": _hash(unsigned)}


def build_recovery_completion_proposal(
        *, attempt: Mapping[str, Any], policy: Mapping[str, Any],
        boundary: Mapping[str, Any], new_device_evidence: Mapping[str, Any],
        revocation_evidence: Mapping[str, Any], observed_at_epoch_ms: int) -> dict[str, Any]:
    key_boundary = validate_key_boundary(boundary)
    recovery_policy = validate_recovery_policy(policy, boundary=key_boundary)
    recovery_attempt = validate_recovery_attempt(
        attempt, policy=recovery_policy, boundary=key_boundary)
    if recovery_attempt["status"] != "ELIGIBLE_OFFLINE":
        raise ValueError("recovery attempt is not eligible offline")
    observed = _time(observed_at_epoch_ms, "observedAtEpochMs")
    if observed > recovery_attempt["expiresAtEpochMs"]:
        raise ValueError("recovery attempt expired before completion review")
    device = _evidence(new_device_evidence, kind="NEW_DEVICE_VERIFIED",
                       attempt=recovery_attempt, observed_at=observed)
    revocation = _evidence(
        revocation_evidence, kind="PRIOR_DEVICE_REVOCATION_VERIFIED",
        attempt=recovery_attempt, observed_at=observed)
    if device["verifierIdentitySha256"] == revocation["verifierIdentitySha256"]:
        raise ValueError("completion evidence verifiers must be independent")
    unsigned = {
        "schemaVersion": SCHEMA,
        "boundaryId": key_boundary["boundaryId"],
        "recoveryPolicyId": recovery_policy["recoveryPolicyId"],
        "attemptId": recovery_attempt["attemptId"],
        "walletIdentitySha256": recovery_attempt["walletIdentitySha256"],
        "activeDeviceIdentitySha256": recovery_attempt["activeDeviceIdentitySha256"],
        "targetDeviceIdentitySha256": recovery_attempt["targetDeviceIdentitySha256"],
        "proposedRecoveryEpoch": recovery_attempt["proposedRecoveryEpoch"],
        "newDeviceEvidence": device,
        "revocationEvidence": revocation,
        "observedAtEpochMs": observed,
        "status": "COMPLETION_REVIEW_READY_OFFLINE",
        "recoveryExecuted": False,
        "newAuthorityInstalled": False,
        "priorDeviceRevoked": False,
        "signingAllowed": False,
        "productionRecoveryAllowed": False,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "proposalId": "nwrcp_" + _hash(unsigned)}


def validate_recovery_completion_proposal(
        value: Mapping[str, Any], *, attempt: Mapping[str, Any],
        policy: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "proposalId", "boundaryId", "recoveryPolicyId",
        "attemptId", "walletIdentitySha256", "activeDeviceIdentitySha256",
        "targetDeviceIdentitySha256", "proposedRecoveryEpoch",
        "newDeviceEvidence", "revocationEvidence", "observedAtEpochMs", "status",
        "recoveryExecuted", "newAuthorityInstalled", "priorDeviceRevoked",
        "signingAllowed", "productionRecoveryAllowed", "executionEffect",
        "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA:
        raise ValueError("recovery completion proposal schema is invalid")
    rebuilt = build_recovery_completion_proposal(
        attempt=attempt, policy=policy, boundary=boundary,
        new_device_evidence=value.get("newDeviceEvidence"),
        revocation_evidence=value.get("revocationEvidence"),
        observed_at_epoch_ms=value.get("observedAtEpochMs"))
    if rebuilt != dict(value):
        raise ValueError("recovery completion proposal does not match canonical content")
    return rebuilt
