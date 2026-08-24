"""Pure E5 completion review and isolated-rehearsal authorization contracts."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from core.e5_recovery_attempt import validate_recovery_attempt
from core.e5_recovery_completion import validate_recovery_completion_proposal

DECISION_SCHEMA = "native-wallet-recovery-completion-review.v1"
AUTHORIZATION_SCHEMA = "native-wallet-recovery-rehearsal-authorization.v1"
REQUIRED_CHECKS = (
    "PROPOSAL_CANONICAL", "ATTEMPT_ELIGIBLE_OFFLINE",
    "NEW_DEVICE_EVIDENCE_BOUND", "REVOCATION_EVIDENCE_BOUND",
    "INDEPENDENT_VERIFIERS", "NO_AUTHORITY_INSTALL_EFFECT",
    "NO_PRODUCTION_ROUTE", "ISOLATED_TARGET_DECLARED",
)
MAX_REVIEW_AGE_MS = 10 * 60 * 1000
MAX_AUTHORIZATION_MS = 10 * 60 * 1000
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


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 96 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def build_completion_review(
        *, proposal: Mapping[str, Any], attempt: Mapping[str, Any],
        policy: Mapping[str, Any], boundary: Mapping[str, Any],
        reviewer_identity_sha256: str, reviewed_at_epoch_ms: int,
        check_outcomes: Mapping[str, str]) -> dict[str, Any]:
    completion = validate_recovery_completion_proposal(
        proposal, attempt=attempt, policy=policy, boundary=boundary)
    recovery_attempt = validate_recovery_attempt(
        attempt, policy=policy, boundary=boundary)
    if not isinstance(check_outcomes, Mapping) \
            or set(check_outcomes) != set(REQUIRED_CHECKS) \
            or any(value not in {"PASS", "FAIL"} for value in check_outcomes.values()):
        raise ValueError("completion review check set is invalid")
    outcomes = [{"checkId": check, "outcome": check_outcomes[check]}
                for check in REQUIRED_CHECKS]
    blockers = [item["checkId"] for item in outcomes if item["outcome"] != "PASS"]
    reviewed = _time(reviewed_at_epoch_ms, "reviewedAtEpochMs")
    if reviewed < completion["observedAtEpochMs"]:
        raise ValueError("completion review predates proposal")
    if reviewed > recovery_attempt["expiresAtEpochMs"]:
        raise ValueError("completion review is outside attempt lifetime")
    reviewer = _digest(reviewer_identity_sha256, "reviewerIdentitySha256")
    excluded_reviewers = {
        recovery_attempt["activeDeviceIdentitySha256"],
        recovery_attempt["targetDeviceIdentitySha256"],
        completion["newDeviceEvidence"]["verifierIdentitySha256"],
        completion["revocationEvidence"]["verifierIdentitySha256"],
    }
    if reviewer in excluded_reviewers:
        raise ValueError("completion reviewer is not independent")
    review_ready = not blockers
    unsigned = {
        "schemaVersion": DECISION_SCHEMA,
        "proposalId": completion["proposalId"],
        "attemptId": recovery_attempt["attemptId"],
        "walletIdentitySha256": completion["walletIdentitySha256"],
        "targetDeviceIdentitySha256": completion["targetDeviceIdentitySha256"],
        "proposedRecoveryEpoch": completion["proposedRecoveryEpoch"],
        "reviewerIdentitySha256": reviewer,
        "reviewedAtEpochMs": reviewed,
        "checkOutcomes": outcomes,
        "blockers": blockers,
        "status": "REHEARSAL_REVIEW_READY" if review_ready else "NO_GO",
        "isolatedRehearsalReviewReady": review_ready,
        "recoveryExecuted": False, "newAuthorityInstalled": False,
        "signingAllowed": False, "productionRecoveryAllowed": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "reviewId": "nwrrv_" + _hash(unsigned)}


def validate_completion_review(
        value: Mapping[str, Any], *, proposal: Mapping[str, Any],
        attempt: Mapping[str, Any], policy: Mapping[str, Any],
        boundary: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schemaVersion", "reviewId", "proposalId", "attemptId",
        "walletIdentitySha256", "targetDeviceIdentitySha256",
        "proposedRecoveryEpoch", "reviewerIdentitySha256",
        "reviewedAtEpochMs", "checkOutcomes", "blockers", "status",
        "isolatedRehearsalReviewReady", "recoveryExecuted",
        "newAuthorityInstalled", "signingAllowed", "productionRecoveryAllowed",
        "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != DECISION_SCHEMA:
        raise ValueError("completion review schema is invalid")
    items = value.get("checkOutcomes")
    if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
        raise ValueError("completion review outcomes are invalid")
    outcomes = {item.get("checkId"): item.get("outcome") for item in items}
    if len(outcomes) != len(items):
        raise ValueError("completion review outcomes are duplicated")
    rebuilt = build_completion_review(
        proposal=proposal, attempt=attempt, policy=policy, boundary=boundary,
        reviewer_identity_sha256=value.get("reviewerIdentitySha256"),
        reviewed_at_epoch_ms=value.get("reviewedAtEpochMs"),
        check_outcomes=outcomes)
    if rebuilt != dict(value):
        raise ValueError("completion review does not match canonical content")
    return rebuilt


def build_rehearsal_authorization(
        *, review: Mapping[str, Any], proposal: Mapping[str, Any],
        attempt: Mapping[str, Any], policy: Mapping[str, Any],
        boundary: Mapping[str, Any], rehearsal_nonce_sha256: str,
        isolated_target_identity_sha256: str, mobile_build_sha256: str,
        authorized_at_epoch_ms: int, expires_at_epoch_ms: int,
        consumed_authorization_ids: Iterable[str] = ()) -> dict[str, Any]:
    decision = validate_completion_review(
        review, proposal=proposal, attempt=attempt, policy=policy, boundary=boundary)
    if not decision["isolatedRehearsalReviewReady"]:
        raise ValueError("completion review is not ready")
    authorized = _time(authorized_at_epoch_ms, "authorizedAtEpochMs")
    expires = _time(expires_at_epoch_ms, "expiresAtEpochMs")
    if authorized - decision["reviewedAtEpochMs"] > MAX_REVIEW_AGE_MS \
            or authorized < decision["reviewedAtEpochMs"] - FUTURE_SKEW_MS:
        raise ValueError("completion review is not current")
    if not authorized < expires <= authorized + MAX_AUTHORIZATION_MS:
        raise ValueError("rehearsal authorization lifetime is invalid")
    unsigned = {
        "schemaVersion": AUTHORIZATION_SCHEMA,
        "reviewId": decision["reviewId"], "proposalId": decision["proposalId"],
        "attemptId": decision["attemptId"],
        "walletIdentitySha256": decision["walletIdentitySha256"],
        "targetDeviceIdentitySha256": decision["targetDeviceIdentitySha256"],
        "proposedRecoveryEpoch": decision["proposedRecoveryEpoch"],
        "rehearsalNonceSha256": _digest(
            rehearsal_nonce_sha256, "rehearsalNonceSha256"),
        "isolatedTargetIdentitySha256": _digest(
            isolated_target_identity_sha256, "isolatedTargetIdentitySha256"),
        "mobileBuildSha256": _digest(mobile_build_sha256, "mobileBuildSha256"),
        "authorizedAtEpochMs": authorized, "expiresAtEpochMs": expires,
        "scope": "ONE_ISOLATED_NON_PRODUCTION_MOBILE_RECOVERY_REHEARSAL",
        "invocationLimit": 1, "isolatedRehearsalEligible": True,
        "productionNetworkAllowed": False, "productionCredentialsAllowed": False,
        "productionWalletAllowed": False, "realKeyMaterialAllowed": False,
        "authorityInstallationAllowed": False, "priorDeviceRevocationAllowed": False,
        "broadcastAllowed": False, "automaticRetryAllowed": False,
        "recoveryExecuted": False, "signingAllowed": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    result = {**unsigned, "authorizationId": "nwrra_" + _hash(unsigned)}
    consumed = set(consumed_authorization_ids)
    if not all(isinstance(item, str) for item in consumed):
        raise ValueError("consumed authorization IDs are invalid")
    if result["authorizationId"] in consumed:
        raise ValueError("rehearsal authorization was already consumed")
    return result


def validate_rehearsal_authorization(
        value: Mapping[str, Any], *, review: Mapping[str, Any],
        proposal: Mapping[str, Any], attempt: Mapping[str, Any],
        policy: Mapping[str, Any], boundary: Mapping[str, Any],
        consumed_authorization_ids: Iterable[str] = ()) -> dict[str, Any]:
    required = {
        "schemaVersion", "authorizationId", "reviewId", "proposalId", "attemptId",
        "walletIdentitySha256", "targetDeviceIdentitySha256",
        "proposedRecoveryEpoch", "rehearsalNonceSha256",
        "isolatedTargetIdentitySha256", "mobileBuildSha256",
        "authorizedAtEpochMs", "expiresAtEpochMs", "scope", "invocationLimit",
        "isolatedRehearsalEligible", "productionNetworkAllowed",
        "productionCredentialsAllowed", "productionWalletAllowed",
        "realKeyMaterialAllowed", "authorityInstallationAllowed",
        "priorDeviceRevocationAllowed", "broadcastAllowed", "automaticRetryAllowed",
        "recoveryExecuted", "signingAllowed", "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != AUTHORIZATION_SCHEMA:
        raise ValueError("rehearsal authorization schema is invalid")
    rebuilt = build_rehearsal_authorization(
        review=review, proposal=proposal, attempt=attempt, policy=policy,
        boundary=boundary, rehearsal_nonce_sha256=value.get("rehearsalNonceSha256"),
        isolated_target_identity_sha256=value.get("isolatedTargetIdentitySha256"),
        mobile_build_sha256=value.get("mobileBuildSha256"),
        authorized_at_epoch_ms=value.get("authorizedAtEpochMs"),
        expires_at_epoch_ms=value.get("expiresAtEpochMs"),
        consumed_authorization_ids=consumed_authorization_ids)
    if rebuilt != dict(value):
        raise ValueError("rehearsal authorization does not match canonical content")
    return rebuilt
