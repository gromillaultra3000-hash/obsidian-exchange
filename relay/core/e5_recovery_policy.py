"""Pure E5 recovery policy contract; contains no recovery implementation."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from core.e5_key_boundary import validate_key_boundary

SCHEMA = "native-wallet-recovery-policy.v1"
GUARDIAN_THRESHOLD = 2
GUARDIAN_COUNT = 3
RECOVERY_DELAY_HOURS = 24


def _hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _guardians(values: Sequence[str]) -> list[str]:
    if not isinstance(values, (list, tuple)) or len(values) != GUARDIAN_COUNT:
        raise ValueError("exactly three guardian trust domains are required")
    normalized = [_token(value, "guardianTrustDomain") for value in values]
    if len(set(normalized)) != GUARDIAN_COUNT:
        raise ValueError("guardian trust domains must be independent")
    forbidden = {"server", "operator", "analytics", "support"}
    if forbidden.intersection(normalized):
        raise ValueError("server-controlled guardian is forbidden")
    return normalized


def build_recovery_policy(
        *, boundary: Mapping[str, Any], policy_id: str,
        guardian_trust_domains: Sequence[str]) -> dict[str, Any]:
    key_boundary = validate_key_boundary(boundary)
    guardians = _guardians(guardian_trust_domains)
    unsigned = {
        "schemaVersion": SCHEMA,
        "policyName": _token(policy_id, "policyId"),
        "boundaryId": key_boundary["boundaryId"],
        "recoveryPaths": {
            "offlineSeed": {
                "enabled": True,
                "userControlled": True,
                "serverRequired": False,
                "serverMayReceiveSeed": False,
                "localRestoreOnly": True,
            },
            "thresholdGuardians": {
                "enabled": True,
                "threshold": GUARDIAN_THRESHOLD,
                "guardianCount": GUARDIAN_COUNT,
                "trustDomains": guardians,
                "serverMayBeGuardian": False,
                "serverMayHoldRecoveryShare": False,
                "newDeviceAttestationRequired": True,
                "localUserVerificationRequired": True,
            },
        },
        "rollbackResistance": {
            "monotonicRecoveryEpochRequired": True,
            "priorDeviceRevocationRequired": True,
            "priorGuardianApprovalsSingleUse": True,
            "oldBackupCannotLowerEpoch": True,
        },
        "abuseResistance": {
            "recoveryDelayHours": RECOVERY_DELAY_HOURS,
            "outOfBandNotificationsRequired": True,
            "activeDeviceVetoDuringDelay": True,
            "guardianRateLimitRequired": True,
            "guardianReplacementDelayRequired": True,
            "supportOverrideForbidden": True,
            "operatorOverrideForbidden": True,
        },
        "backupRequirements": {
            "plaintextCloudBackupForbidden": True,
            "serverReadableBackupForbidden": True,
            "integrityBindingRequired": True,
            "versionBindingRequired": True,
            "restoreRehearsalRequired": True,
        },
        "selectedCryptography": "UNDECIDED",
        "selectedPlatformSdk": "UNDECIDED",
        "formalProtocolSpecified": False,
        "recoveryImplemented": False,
        "recoveryTestedOnDevice": False,
        "containsSeed": False,
        "containsRecoveryShare": False,
        "serverCanRecover": False,
        "productionReleaseAllowed": False,
        "executionEffect": "NONE",
        "actionAllowed": False,
        "status": "DESIGN_ONLY",
    }
    return {**unsigned, "recoveryPolicyId": "nwrp_" + _hash(unsigned)}


def validate_recovery_policy(
        value: Mapping[str, Any], *, boundary: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "recoveryPolicyId", "policyName", "boundaryId",
        "recoveryPaths", "rollbackResistance", "abuseResistance",
        "backupRequirements", "selectedCryptography", "selectedPlatformSdk",
        "formalProtocolSpecified", "recoveryImplemented",
        "recoveryTestedOnDevice", "containsSeed", "containsRecoveryShare",
        "serverCanRecover", "productionReleaseAllowed", "executionEffect",
        "actionAllowed", "status",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA:
        raise ValueError("recovery policy schema is invalid")
    paths = value.get("recoveryPaths")
    if not isinstance(paths, Mapping) \
            or not isinstance(paths.get("thresholdGuardians"), Mapping):
        raise ValueError("recovery paths are invalid")
    rebuilt = build_recovery_policy(
        boundary=boundary, policy_id=value.get("policyName"),
        guardian_trust_domains=paths["thresholdGuardians"].get("trustDomains"))
    if rebuilt != dict(value):
        raise ValueError("recovery policy does not match canonical content")
    return rebuilt
