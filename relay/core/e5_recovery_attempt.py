"""Pure E5 recovery-attempt state machine; never performs recovery."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from core.e5_key_boundary import validate_key_boundary
from core.e5_recovery_policy import validate_recovery_policy

SCHEMA = "native-wallet-recovery-attempt.v1"
MAX_ATTEMPT_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000


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


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _base(*, policy: Mapping[str, Any], boundary: Mapping[str, Any],
          attempt_nonce_sha256: str, wallet_identity_sha256: str,
          active_device_identity_sha256: str, target_device_identity_sha256: str,
          target_device_attestation_sha256: str, current_recovery_epoch: int,
          proposed_recovery_epoch: int, created_at_epoch_ms: int,
          expires_at_epoch_ms: int) -> dict[str, Any]:
    key_boundary = validate_key_boundary(boundary)
    recovery_policy = validate_recovery_policy(policy, boundary=key_boundary)
    current_epoch = _epoch(current_recovery_epoch, "currentRecoveryEpoch")
    proposed_epoch = _epoch(proposed_recovery_epoch, "proposedRecoveryEpoch")
    if proposed_epoch != current_epoch + 1:
        raise ValueError("recovery epoch must advance exactly once")
    created = _time(created_at_epoch_ms, "createdAtEpochMs")
    expires = _time(expires_at_epoch_ms, "expiresAtEpochMs")
    delay_ms = recovery_policy["abuseResistance"]["recoveryDelayHours"] * 3_600_000
    eligible_at = created + delay_ms
    if not eligible_at < expires <= created + MAX_ATTEMPT_LIFETIME_MS:
        raise ValueError("recovery attempt lifetime is invalid")
    active_device = _digest(
        active_device_identity_sha256, "activeDeviceIdentitySha256")
    target_device = _digest(
        target_device_identity_sha256, "targetDeviceIdentitySha256")
    if active_device == target_device:
        raise ValueError("target device must differ from active device")
    return {
        "schemaVersion": SCHEMA,
        "boundaryId": key_boundary["boundaryId"],
        "recoveryPolicyId": recovery_policy["recoveryPolicyId"],
        "attemptNonceSha256": _digest(attempt_nonce_sha256, "attemptNonceSha256"),
        "walletIdentitySha256": _digest(wallet_identity_sha256, "walletIdentitySha256"),
        "activeDeviceIdentitySha256": active_device,
        "targetDeviceIdentitySha256": target_device,
        "targetDeviceAttestationSha256": _digest(
            target_device_attestation_sha256, "targetDeviceAttestationSha256"),
        "currentRecoveryEpoch": current_epoch,
        "proposedRecoveryEpoch": proposed_epoch,
        "createdAtEpochMs": created,
        "eligibleAtEpochMs": eligible_at,
        "expiresAtEpochMs": expires,
        "guardianTrustDomains": recovery_policy["recoveryPaths"]
            ["thresholdGuardians"]["trustDomains"],
        "guardianThreshold": recovery_policy["recoveryPaths"]
            ["thresholdGuardians"]["threshold"],
    }


def _materialize(base: Mapping[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    approvals: dict[str, str] = {}
    status = "PENDING_DELAY"
    last_hash = "0" * 64
    normalized_events = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or event.get("sequence") != index + 1 \
                or event.get("previousEventSha256") != last_hash:
            raise ValueError("recovery event chain is invalid")
        unsigned_event = {key: event[key] for key in event if key != "eventSha256"}
        event_hash = _hash(unsigned_event)
        if event.get("eventSha256") != event_hash:
            raise ValueError("recovery event hash is invalid")
        event_type = event.get("type")
        occurred = _time(event.get("occurredAtEpochMs"), "occurredAtEpochMs")
        if occurred < base["createdAtEpochMs"] or occurred > base["expiresAtEpochMs"]:
            raise ValueError("recovery event is outside attempt lifetime")
        if status != "PENDING_DELAY":
            raise ValueError("terminal recovery attempt cannot change")
        if event_type == "GUARDIAN_APPROVED":
            domain = event.get("guardianTrustDomain")
            if domain not in base["guardianTrustDomains"]:
                raise ValueError("guardian is outside recovery policy")
            evidence = _digest(event.get("approvalEvidenceSha256"),
                               "approvalEvidenceSha256")
            if event.get("targetDeviceIdentitySha256") \
                    != base["targetDeviceIdentitySha256"] \
                    or event.get("proposedRecoveryEpoch") \
                    != base["proposedRecoveryEpoch"]:
                raise ValueError("guardian approval binding is invalid")
            if domain in approvals:
                raise ValueError("guardian approval was appended twice")
            approvals[domain] = evidence
        elif event_type == "ACTIVE_DEVICE_VETOED":
            if event.get("activeDeviceIdentitySha256") \
                    != base["activeDeviceIdentitySha256"]:
                raise ValueError("active-device veto binding is invalid")
            _digest(event.get("vetoEvidenceSha256"), "vetoEvidenceSha256")
            if occurred >= base["eligibleAtEpochMs"]:
                raise ValueError("active-device veto is outside delay window")
            status = "VETOED"
        elif event_type == "EVALUATED_ELIGIBLE":
            if occurred < base["eligibleAtEpochMs"] \
                    or len(approvals) < base["guardianThreshold"]:
                raise ValueError("recovery attempt is not eligible")
            status = "ELIGIBLE_OFFLINE"
        elif event_type == "EVALUATED_EXPIRED":
            if occurred != base["expiresAtEpochMs"]:
                raise ValueError("expiry evaluation time is invalid")
            status = "EXPIRED"
        else:
            raise ValueError("recovery event type is invalid")
        normalized_events.append(dict(event))
        last_hash = event_hash
    unsigned = {
        **dict(base),
        "events": normalized_events,
        "guardianApprovalCount": len(approvals),
        "approvedGuardianTrustDomains": list(approvals),
        "status": status,
        "recoveryEligibleOffline": status == "ELIGIBLE_OFFLINE",
        "recoveryExecuted": False,
        "newAuthorityInstalled": False,
        "priorDeviceRevoked": False,
        "containsSeed": False,
        "containsRecoveryShare": False,
        "serverCanRecover": False,
        "productionRecoveryAllowed": False,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "attemptId": "nwra_" + _hash(unsigned)}


def open_recovery_attempt(**values: Any) -> dict[str, Any]:
    return _materialize(_base(**values), [])


def _append(attempt: Mapping[str, Any], event: dict[str, Any], *,
            policy: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, Any]:
    current = validate_recovery_attempt(attempt, policy=policy, boundary=boundary)
    unsigned_event = {
        "sequence": len(current["events"]) + 1,
        "previousEventSha256": current["events"][-1]["eventSha256"]
            if current["events"] else "0" * 64,
        **event,
    }
    appended = {**unsigned_event, "eventSha256": _hash(unsigned_event)}
    base = {key: current[key] for key in _BASE_FIELDS}
    return _materialize(base, [*current["events"], appended])


def approve_recovery_attempt(
        attempt: Mapping[str, Any], *, policy: Mapping[str, Any],
        boundary: Mapping[str, Any], guardian_trust_domain: str,
        approval_evidence_sha256: str, occurred_at_epoch_ms: int) -> dict[str, Any]:
    current = validate_recovery_attempt(attempt, policy=policy, boundary=boundary)
    for event in current["events"]:
        if event.get("type") == "GUARDIAN_APPROVED" \
                and event.get("guardianTrustDomain") == guardian_trust_domain:
            if event.get("approvalEvidenceSha256") == approval_evidence_sha256:
                return current
            raise ValueError("guardian approval evidence drift")
    return _append(current, {
        "type": "GUARDIAN_APPROVED",
        "guardianTrustDomain": guardian_trust_domain,
        "approvalEvidenceSha256": _digest(
            approval_evidence_sha256, "approvalEvidenceSha256"),
        "targetDeviceIdentitySha256": current["targetDeviceIdentitySha256"],
        "proposedRecoveryEpoch": current["proposedRecoveryEpoch"],
        "occurredAtEpochMs": occurred_at_epoch_ms,
    }, policy=policy, boundary=boundary)


def veto_recovery_attempt(
        attempt: Mapping[str, Any], *, policy: Mapping[str, Any],
        boundary: Mapping[str, Any], veto_evidence_sha256: str,
        occurred_at_epoch_ms: int) -> dict[str, Any]:
    current = validate_recovery_attempt(attempt, policy=policy, boundary=boundary)
    return _append(current, {
        "type": "ACTIVE_DEVICE_VETOED",
        "activeDeviceIdentitySha256": current["activeDeviceIdentitySha256"],
        "vetoEvidenceSha256": _digest(veto_evidence_sha256, "vetoEvidenceSha256"),
        "occurredAtEpochMs": occurred_at_epoch_ms,
    }, policy=policy, boundary=boundary)


def evaluate_recovery_attempt(
        attempt: Mapping[str, Any], *, policy: Mapping[str, Any],
        boundary: Mapping[str, Any], observed_at_epoch_ms: int) -> dict[str, Any]:
    current = validate_recovery_attempt(attempt, policy=policy, boundary=boundary)
    observed = _time(observed_at_epoch_ms, "observedAtEpochMs")
    if current["status"] != "PENDING_DELAY":
        return current
    if observed >= current["expiresAtEpochMs"]:
        return _append(current, {
            "type": "EVALUATED_EXPIRED",
            "occurredAtEpochMs": current["expiresAtEpochMs"],
        }, policy=policy, boundary=boundary)
    if observed >= current["eligibleAtEpochMs"] \
            and current["guardianApprovalCount"] >= current["guardianThreshold"]:
        return _append(current, {
            "type": "EVALUATED_ELIGIBLE", "occurredAtEpochMs": observed,
        }, policy=policy, boundary=boundary)
    return current


_BASE_FIELDS = {
    "schemaVersion", "boundaryId", "recoveryPolicyId", "attemptNonceSha256",
    "walletIdentitySha256", "activeDeviceIdentitySha256",
    "targetDeviceIdentitySha256", "targetDeviceAttestationSha256",
    "currentRecoveryEpoch", "proposedRecoveryEpoch", "createdAtEpochMs",
    "eligibleAtEpochMs", "expiresAtEpochMs", "guardianTrustDomains",
    "guardianThreshold",
}


def validate_recovery_attempt(
        value: Mapping[str, Any], *, policy: Mapping[str, Any],
        boundary: Mapping[str, Any]) -> dict[str, Any]:
    required = _BASE_FIELDS | {
        "attemptId", "events", "guardianApprovalCount",
        "approvedGuardianTrustDomains", "status", "recoveryEligibleOffline",
        "recoveryExecuted", "newAuthorityInstalled", "priorDeviceRevoked",
        "containsSeed", "containsRecoveryShare", "serverCanRecover",
        "productionRecoveryAllowed", "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA:
        raise ValueError("recovery attempt schema is invalid")
    recovery_policy = validate_recovery_policy(policy, boundary=boundary)
    base = _base(
        policy=recovery_policy, boundary=boundary,
        attempt_nonce_sha256=value.get("attemptNonceSha256"),
        wallet_identity_sha256=value.get("walletIdentitySha256"),
        active_device_identity_sha256=value.get("activeDeviceIdentitySha256"),
        target_device_identity_sha256=value.get("targetDeviceIdentitySha256"),
        target_device_attestation_sha256=value.get("targetDeviceAttestationSha256"),
        current_recovery_epoch=value.get("currentRecoveryEpoch"),
        proposed_recovery_epoch=value.get("proposedRecoveryEpoch"),
        created_at_epoch_ms=value.get("createdAtEpochMs"),
        expires_at_epoch_ms=value.get("expiresAtEpochMs"))
    rebuilt = _materialize(base, value.get("events"))
    if rebuilt != dict(value):
        raise ValueError("recovery attempt does not match canonical event replay")
    return rebuilt
