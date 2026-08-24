"""Pure E5 isolated-rehearsal result contract; performs no rehearsal or recovery."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from core.e5_recovery_review import validate_rehearsal_authorization

CONSUMPTION_SCHEMA = "native-wallet-recovery-rehearsal-consumption.v1"
OBSERVATION_SCHEMA = "native-wallet-recovery-rehearsal-observation.v1"
RESULT_SCHEMA = "native-wallet-recovery-rehearsal-result.v1"
REQUIRED_STEPS = (
    "TARGET_ISOLATION_VERIFIED", "MOBILE_BUILD_MATCHED",
    "AUTHORIZATION_CONSUMED_ONCE", "SYNTHETIC_WALLET_ONLY",
    "NO_PRODUCTION_NETWORK", "NO_REAL_KEY_MATERIAL",
    "NO_AUTHORITY_INSTALLED", "PRIOR_DEVICE_NOT_REVOKED",
    "NO_TRANSACTION_BROADCAST", "TARGET_TEARDOWN_VERIFIED",
)
MAX_REHEARSAL_DURATION_MS = 30 * 60 * 1000
FUTURE_SKEW_MS = 1_000


def _hash(value: Any) -> str:
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


def build_consumption_evidence(
        *, authorization: Mapping[str, Any], invocation_identity_sha256: str,
        invoked_at_epoch_ms: int) -> dict[str, Any]:
    invoked = _time(invoked_at_epoch_ms, "invokedAtEpochMs")
    if not authorization.get("authorizedAtEpochMs") <= invoked \
            <= authorization.get("expiresAtEpochMs"):
        raise ValueError("rehearsal invocation is outside authorization lifetime")
    unsigned = {
        "schemaVersion": CONSUMPTION_SCHEMA,
        "authorizationId": authorization.get("authorizationId"),
        "invocationIdentitySha256": _digest(
            invocation_identity_sha256, "invocationIdentitySha256"),
        "isolatedTargetIdentitySha256": authorization.get(
            "isolatedTargetIdentitySha256"),
        "mobileBuildSha256": authorization.get("mobileBuildSha256"),
        "rehearsalNonceSha256": authorization.get("rehearsalNonceSha256"),
        "invokedAtEpochMs": invoked, "consumptionCount": 1,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "consumptionId": "nwrrc_" + _hash(unsigned)}


def build_rehearsal_observation(
        *, authorization: Mapping[str, Any], consumption: Mapping[str, Any],
        step_id: str, outcome: str, evidence_sha256: str,
        observer_identity_sha256: str, observed_at_epoch_ms: int) -> dict[str, Any]:
    if step_id not in REQUIRED_STEPS or outcome not in {"PASS", "FAIL"}:
        raise ValueError("rehearsal observation verdict is invalid")
    unsigned = {
        "schemaVersion": OBSERVATION_SCHEMA,
        "authorizationId": authorization.get("authorizationId"),
        "consumptionId": consumption.get("consumptionId"),
        "isolatedTargetIdentitySha256": authorization.get(
            "isolatedTargetIdentitySha256"),
        "mobileBuildSha256": authorization.get("mobileBuildSha256"),
        "stepId": step_id, "outcome": outcome,
        "evidenceSha256": _digest(evidence_sha256, "evidenceSha256"),
        "observerIdentitySha256": _digest(
            observer_identity_sha256, "observerIdentitySha256"),
        "observedAtEpochMs": _time(observed_at_epoch_ms, "observedAtEpochMs"),
        "containsSecrets": False, "containsRealKeyMaterial": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "observationId": "nwrro_" + _hash(unsigned)}


def _validate_consumption(value: Mapping[str, Any], authorization: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "consumptionId", "authorizationId",
        "invocationIdentitySha256", "isolatedTargetIdentitySha256",
        "mobileBuildSha256", "rehearsalNonceSha256", "invokedAtEpochMs",
        "consumptionCount", "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != fields \
            or value.get("schemaVersion") != CONSUMPTION_SCHEMA \
            or value.get("consumptionCount") != 1 \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("rehearsal consumption schema is invalid")
    rebuilt = build_consumption_evidence(
        authorization=authorization,
        invocation_identity_sha256=value.get("invocationIdentitySha256"),
        invoked_at_epoch_ms=value.get("invokedAtEpochMs"))
    if rebuilt != dict(value):
        raise ValueError("rehearsal consumption binding is invalid")
    return rebuilt


def _validate_observation(
        value: Mapping[str, Any], *, authorization: Mapping[str, Any],
        consumption: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schemaVersion", "observationId", "authorizationId", "consumptionId",
        "isolatedTargetIdentitySha256", "mobileBuildSha256", "stepId", "outcome",
        "evidenceSha256", "observerIdentitySha256", "observedAtEpochMs",
        "containsSecrets", "containsRealKeyMaterial", "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != fields \
            or value.get("schemaVersion") != OBSERVATION_SCHEMA \
            or value.get("containsSecrets") is not False \
            or value.get("containsRealKeyMaterial") is not False \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("rehearsal observation schema is invalid")
    rebuilt = build_rehearsal_observation(
        authorization=authorization, consumption=consumption,
        step_id=value.get("stepId"), outcome=value.get("outcome"),
        evidence_sha256=value.get("evidenceSha256"),
        observer_identity_sha256=value.get("observerIdentitySha256"),
        observed_at_epoch_ms=value.get("observedAtEpochMs"))
    if rebuilt != dict(value):
        raise ValueError("rehearsal observation binding is invalid")
    return rebuilt


def build_rehearsal_result(
        *, authorization: Mapping[str, Any], review: Mapping[str, Any],
        proposal: Mapping[str, Any], attempt: Mapping[str, Any],
        policy: Mapping[str, Any], boundary: Mapping[str, Any],
        consumption: Mapping[str, Any], observations: Sequence[Mapping[str, Any]],
        consumed_authorization_ids: Sequence[str],
        attestor_identity_sha256: str, attested_at_epoch_ms: int) -> dict[str, Any]:
    authorized = validate_rehearsal_authorization(
        authorization, review=review, proposal=proposal, attempt=attempt,
        policy=policy, boundary=boundary)
    consumed = _validate_consumption(consumption, authorized)
    if not isinstance(consumed_authorization_ids, (list, tuple)) \
            or any(not isinstance(item, str) for item in consumed_authorization_ids) \
            or consumed_authorization_ids.count(authorized["authorizationId"]) != 1:
        raise ValueError("authorization consumption ledger does not prove exactly once")
    items = [_validate_observation(
        item, authorization=authorized, consumption=consumed) for item in observations]
    if len(items) != len(REQUIRED_STEPS) \
            or len({item["stepId"] for item in items}) != len(REQUIRED_STEPS):
        raise ValueError("rehearsal observation set is incomplete or duplicated")
    by_step = {item["stepId"]: item for item in items}
    attested = _time(attested_at_epoch_ms, "attestedAtEpochMs")
    if any(item["observedAtEpochMs"] < consumed["invokedAtEpochMs"]
           or item["observedAtEpochMs"] > attested + FUTURE_SKEW_MS
           for item in items):
        raise ValueError("rehearsal observation time is invalid")
    if attested < consumed["invokedAtEpochMs"] \
            or attested > consumed["invokedAtEpochMs"] + MAX_REHEARSAL_DURATION_MS:
        raise ValueError("rehearsal attestation time is invalid")
    attestor = _digest(attestor_identity_sha256, "attestorIdentitySha256")
    if attestor in {consumed["invocationIdentitySha256"],
                    *{item["observerIdentitySha256"] for item in items}}:
        raise ValueError("rehearsal attestor is not independent")
    blockers = [step for step in REQUIRED_STEPS if by_step[step]["outcome"] != "PASS"]
    passed = not blockers
    unsigned = {
        "schemaVersion": RESULT_SCHEMA,
        "authorizationId": authorized["authorizationId"],
        "consumptionId": consumed["consumptionId"],
        "attemptId": authorized["attemptId"],
        "walletIdentitySha256": authorized["walletIdentitySha256"],
        "targetDeviceIdentitySha256": authorized["targetDeviceIdentitySha256"],
        "proposedRecoveryEpoch": authorized["proposedRecoveryEpoch"],
        "isolatedTargetIdentitySha256": authorized["isolatedTargetIdentitySha256"],
        "mobileBuildSha256": authorized["mobileBuildSha256"],
        "observationIds": [by_step[step]["observationId"] for step in REQUIRED_STEPS],
        "attestorIdentitySha256": attestor, "attestedAtEpochMs": attested,
        "status": "PASS" if passed else "FAIL", "blockers": blockers,
        "isolatedRehearsalPassed": passed,
        "onDeviceSecurityVerified": False, "productionReadinessSatisfied": False,
        "recoveryExecuted": False, "newAuthorityInstalled": False,
        "priorDeviceRevoked": False, "signingAllowed": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "resultId": "nwrrs_" + _hash(unsigned)}


def validate_rehearsal_result(
        value: Mapping[str, Any], *, authorization: Mapping[str, Any],
        review: Mapping[str, Any], proposal: Mapping[str, Any],
        attempt: Mapping[str, Any], policy: Mapping[str, Any],
        boundary: Mapping[str, Any], consumption: Mapping[str, Any],
        observations: Sequence[Mapping[str, Any]],
        consumed_authorization_ids: Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schemaVersion") != RESULT_SCHEMA:
        raise ValueError("rehearsal result schema is invalid")
    rebuilt = build_rehearsal_result(
        authorization=authorization, review=review, proposal=proposal,
        attempt=attempt, policy=policy, boundary=boundary,
        consumption=consumption, observations=observations,
        consumed_authorization_ids=consumed_authorization_ids,
        attestor_identity_sha256=value.get("attestorIdentitySha256"),
        attested_at_epoch_ms=value.get("attestedAtEpochMs"))
    if rebuilt != dict(value):
        raise ValueError("rehearsal result does not match canonical content")
    return rebuilt
