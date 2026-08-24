"""Pure route-authorization design for a future E4 production endpoint."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "private-action-route-authorization.v1"
MAX_AUTH_AGE_MS = 5 * 60 * 1000
FUTURE_SKEW_MS = 1_000


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} is invalid")
    return value


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 80 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def assess_route_authorization(*, assessment: Mapping[str, Any],
                               reservation: Mapping[str, Any], web_user_id: int,
                               actor_user_id: int, principal_ref: str,
                               session_fingerprint_sha256: str,
                               csrf_evidence_sha256: str,
                               authenticated_at_epoch_ms: int,
                               assessed_at_epoch_ms: int,
                               handoff_enabled: bool,
                               route_enabled: bool) -> dict[str, Any]:
    web_id = _positive_int(web_user_id, "webUserId")
    actor_id = _positive_int(actor_user_id, "actorUserId")
    authenticated = _positive_int(authenticated_at_epoch_ms, "authenticatedAtEpochMs")
    assessed_at = _positive_int(assessed_at_epoch_ms, "assessedAtEpochMs")
    if not isinstance(handoff_enabled, bool) or not isinstance(route_enabled, bool):
        raise ValueError("feature gates must be boolean")
    if assessment.get("schemaVersion") != "private-action-server-assessment.v1" \
            or reservation.get("schemaVersion") != "private-action-reservation-request.v1" \
            or assessment.get("status") != "SERVER_CHECKS_PASSED_OFFLINE" \
            or assessment.get("workflowInvocationEligible") is not True \
            or reservation.get("draftId") != assessment.get("draftId") \
            or reservation.get("assessmentId") != assessment.get("assessmentId"):
        raise ValueError("route evidence chain is invalid")
    principal = _token(principal_ref, "principalRef")
    if (principal, actor_id) != (
            assessment.get("principalRef"), assessment.get("actorUserId")) \
            or (principal, actor_id) != (
                reservation.get("principalRef"), reservation.get("actorUserId")):
        raise ValueError("route principal or actor binding is invalid")
    blockers = []
    age = assessed_at - authenticated
    if age < -FUTURE_SKEW_MS:
        blockers.append("AUTHENTICATION_FUTURE")
    elif age > MAX_AUTH_AGE_MS:
        blockers.append("AUTHENTICATION_STALE")
    if assessed_at > reservation.get("expiresAtEpochMs", 0):
        blockers.append("RESERVATION_EXPIRED")
    if not handoff_enabled:
        blockers.append("HANDOFF_FEATURE_DISABLED")
    if not route_enabled:
        blockers.append("ROUTE_FEATURE_DISABLED")
    eligible = not blockers
    unsigned = {
        "schemaVersion": SCHEMA, "method": "POST",
        "path": "/api/wallet/private-action/confirm",
        "webUserId": web_id, "actorUserId": actor_id, "principalRef": principal,
        "draftId": assessment["draftId"], "assessmentId": assessment["assessmentId"],
        "reservationRequestId": reservation["requestId"],
        "sessionFingerprintSha256": _digest(
            session_fingerprint_sha256, "sessionFingerprintSha256"),
        "csrfEvidenceSha256": _digest(csrf_evidence_sha256, "csrfEvidenceSha256"),
        "authenticatedAtEpochMs": authenticated, "assessedAtEpochMs": assessed_at,
        "handoffFeatureEnabled": handoff_enabled,
        "routeFeatureEnabled": route_enabled,
        "status": "PRECONDITIONS_SATISFIED_OFFLINE" if eligible else "NO_GO",
        "blockers": blockers, "routeInvocationEligible": eligible,
        "productionMigrationApplied": False, "productionAclVerified": False,
        "productionInvocationAllowed": False, "routeConnected": False,
        "containsSecrets": False, "containsRawDestination": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "authorizationId": "para_" + _hash(unsigned)}


def validate_route_authorization(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "authorizationId", "method", "path", "webUserId",
                "actorUserId", "principalRef", "draftId", "assessmentId",
                "reservationRequestId", "sessionFingerprintSha256",
                "csrfEvidenceSha256", "authenticatedAtEpochMs", "assessedAtEpochMs",
                "handoffFeatureEnabled", "routeFeatureEnabled", "status", "blockers",
                "routeInvocationEligible", "productionMigrationApplied",
                "productionAclVerified", "productionInvocationAllowed", "routeConnected",
                "containsSecrets", "containsRawDestination", "executionEffect",
                "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA or value.get("method") != "POST" \
            or value.get("path") != "/api/wallet/private-action/confirm" \
            or any(value.get(field) is not False for field in (
                "productionMigrationApplied", "productionAclVerified",
                "productionInvocationAllowed", "routeConnected", "containsSecrets",
                "containsRawDestination", "actionAllowed")) \
            or value.get("executionEffect") != "NONE":
        raise ValueError("route authorization schema is invalid")
    unsigned = dict(value); identifier = unsigned.pop("authorizationId", None)
    if identifier != "para_" + _hash(unsigned):
        raise ValueError("route authorization hash is invalid")
    return dict(value)
