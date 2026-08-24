"""Read-only E5 readiness proof; never enables recovery or a production wallet."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from core.e5_recovery_rehearsal_result import validate_rehearsal_result

SCHEMA = "native-wallet-e5-readiness-proof.v1"
FOUNDATION_CHECKS = (
    "KEY_AND_CONSENT_BOUNDARY_VERIFIED",
    "AUTHENTICATOR_EVIDENCE_BOUNDARY_VERIFIED",
    "RECOVERY_POLICY_VERIFIED",
    "RECOVERY_ATTEMPT_STATE_MACHINE_VERIFIED",
    "COMPLETION_REVIEW_BOUNDARY_VERIFIED",
    "SINGLE_USE_REHEARSAL_AUTHORIZATION_VERIFIED",
    "SYNTHETIC_REHEARSAL_RESULT_PASSED",
)
OPERATIONAL_CHECKS = (
    "MOBILE_STACK_SELECTED_AND_REVIEWED",
    "FORMAL_RECOVERY_PROTOCOL_REVIEWED",
    "REPRODUCIBLE_BUILD_PROVENANCE_VERIFIED",
    "REAL_PLATFORM_ATTESTATION_VERIFIED",
    "HARDWARE_BACKING_VERIFIED_ON_DEVICE",
    "ON_DEVICE_BACKUP_RESTORE_E2E_PASSED",
    "RECOVERY_ABUSE_AND_FAULT_TESTS_PASSED",
    "OWNER_PRODUCTION_RELEASE_APPROVED",
)
CHECKS = FOUNDATION_CHECKS + OPERATIONAL_CHECKS
CURRENT_OPERATIONAL_PROBES = {name: False for name in OPERATIONAL_CHECKS}


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def assess_e5_readiness(
        *, result: Mapping[str, Any], authorization: Mapping[str, Any],
        review: Mapping[str, Any], proposal: Mapping[str, Any],
        attempt: Mapping[str, Any], policy: Mapping[str, Any],
        boundary: Mapping[str, Any], consumption: Mapping[str, Any],
        observations: Sequence[Mapping[str, Any]],
        consumed_authorization_ids: Sequence[str],
        operational_probes: Mapping[str, Any]) -> dict[str, Any]:
    rehearsal = validate_rehearsal_result(
        result, authorization=authorization, review=review, proposal=proposal,
        attempt=attempt, policy=policy, boundary=boundary,
        consumption=consumption, observations=observations,
        consumed_authorization_ids=consumed_authorization_ids)
    if not isinstance(operational_probes, Mapping) \
            or set(operational_probes) != set(OPERATIONAL_CHECKS) \
            or any(type(operational_probes[name]) is not bool for name in OPERATIONAL_CHECKS):
        raise ValueError("E5 operational probes must match the frozen boolean schema")
    foundation = {
        **{name: True for name in FOUNDATION_CHECKS[:-1]},
        "SYNTHETIC_REHEARSAL_RESULT_PASSED": rehearsal["isolatedRehearsalPassed"],
    }
    values = {**foundation, **dict(operational_probes)}
    checks = [{"checkId": name, "ready": values[name]} for name in CHECKS]
    blockers = [name for name in CHECKS if not values[name]]
    foundation_ready = all(foundation.values())
    ready = not blockers
    unsigned = {
        "schemaVersion": SCHEMA,
        "rehearsalResultId": rehearsal["resultId"],
        "status": "GO" if ready else "NO_GO",
        "ready": ready,
        "stage": ("OPERATIONAL_PREREQUISITES_COMPLETE" if ready
                  else "DESIGN_AND_SYNTHETIC_FOUNDATION_COMPLETE"
                  if foundation_ready else "FOUNDATION_INCOMPLETE"),
        "checks": checks, "blockers": blockers,
        "eligibleForNativeImplementationReview": ready,
        "selectedMobileStack": "UNDECIDED",
        "selectedProductionNetwork": "UNDECIDED",
        "productionReleaseAllowed": False,
        "recoveryExecutionAllowed": False,
        "authorityInstallationAllowed": False,
        "signingAllowed": False,
        "runtimeEnableAllowed": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "proofId": "nwe5p_" + _hash(unsigned)}


def validate_e5_readiness(
        value: Mapping[str, Any], *, result: Mapping[str, Any],
        authorization: Mapping[str, Any], review: Mapping[str, Any],
        proposal: Mapping[str, Any], attempt: Mapping[str, Any],
        policy: Mapping[str, Any], boundary: Mapping[str, Any],
        consumption: Mapping[str, Any], observations: Sequence[Mapping[str, Any]],
        consumed_authorization_ids: Sequence[str]) -> dict[str, Any]:
    required = {
        "schemaVersion", "proofId", "rehearsalResultId", "status", "ready",
        "stage", "checks", "blockers", "eligibleForNativeImplementationReview",
        "selectedMobileStack", "selectedProductionNetwork",
        "productionReleaseAllowed", "recoveryExecutionAllowed",
        "authorityInstallationAllowed", "signingAllowed", "runtimeEnableAllowed",
        "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA:
        raise ValueError("E5 readiness proof schema is invalid")
    checks = value.get("checks")
    if not isinstance(checks, list) or len(checks) != len(CHECKS) \
            or [item.get("checkId") for item in checks] != list(CHECKS) \
            or any(not isinstance(item, Mapping)
                   or set(item) != {"checkId", "ready"}
                   or type(item["ready"]) is not bool for item in checks):
        raise ValueError("E5 readiness checks are invalid")
    probes = {item["checkId"]: item["ready"] for item in checks
              if item["checkId"] in OPERATIONAL_CHECKS}
    rebuilt = assess_e5_readiness(
        result=result, authorization=authorization, review=review,
        proposal=proposal, attempt=attempt, policy=policy, boundary=boundary,
        consumption=consumption, observations=observations,
        consumed_authorization_ids=consumed_authorization_ids,
        operational_probes=probes)
    if rebuilt != dict(value):
        raise ValueError("E5 readiness proof is inconsistent")
    return rebuilt
