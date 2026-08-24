"""Canonical immutable request for reserving one E4 private action."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "private-action-reservation-request.v1"
MAX_RESERVATION_MS = 5 * 60 * 1000


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _time(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _verify_content_id(value: Mapping[str, Any], id_field: str, prefix: str) -> None:
    if not isinstance(value, Mapping):
        raise ValueError("content-addressed input is invalid")
    unsigned = dict(value)
    identifier = unsigned.pop(id_field, None)
    if identifier != prefix + _hash(unsigned):
        raise ValueError("content-addressed input hash is invalid")


def build_action_reservation_request(*, draft: Mapping[str, Any],
                                     assessment: Mapping[str, Any],
                                     requested_at_epoch_ms: int,
                                     expires_at_epoch_ms: int) -> dict[str, Any]:
    _verify_content_id(draft, "draftId", "wacd_")
    _verify_content_id(assessment, "assessmentId", "pasa_")
    if draft.get("schemaVersion") != "wallet-action-confirmation-draft.v1" \
            or draft.get("status") != "DRAFT_ONLY" \
            or assessment.get("schemaVersion") != "private-action-server-assessment.v1" \
            or assessment.get("status") != "SERVER_CHECKS_PASSED_OFFLINE" \
            or assessment.get("workflowInvocationEligible") is not True \
            or (assessment.get("draftId"), assessment.get("principalRef")) != (
                draft.get("draftId"), assessment.get("principalRef")):
        raise ValueError("draft or assessment is not reservation eligible")
    if any(draft.get(field) is not False for field in (
            "persisted", "moneyIntentAllowed", "actionAllowed")) \
            or any(assessment.get(field) is not False for field in (
                "routeConnected", "persisted", "moneyIntentAllowed", "actionAllowed")):
        raise ValueError("draft or assessment safety state is invalid")
    requested = _time(requested_at_epoch_ms, "requestedAtEpochMs")
    expires = _time(expires_at_epoch_ms, "expiresAtEpochMs")
    if not requested < expires <= min(
            requested + MAX_RESERVATION_MS, draft.get("quoteExpiresAtEpochMs", 0)):
        raise ValueError("reservation lifetime is invalid")
    if requested < assessment.get("assessedAtEpochMs", 0) \
            or requested > draft.get("quoteExpiresAtEpochMs", 0):
        raise ValueError("reservation request time is invalid")
    unsigned = {
        "schemaVersion": SCHEMA, "draftId": draft["draftId"],
        "assessmentId": assessment["assessmentId"],
        "principalRef": assessment["principalRef"],
        "actorUserId": assessment["actorUserId"],
        "idempotencyKeySha256": draft["idempotencyKeySha256"],
        "workflowMapping": assessment["workflowMapping"],
        "payloadSha256": _hash({"draft": draft, "assessment": assessment}),
        "quoteExpiresAtEpochMs": draft["quoteExpiresAtEpochMs"],
        "requestedAtEpochMs": requested, "expiresAtEpochMs": expires,
        "containsSecrets": False, "containsRawDestination": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "requestId": "parr_" + _hash(unsigned)}


def validate_action_reservation_request(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "requestId", "draftId", "assessmentId",
                "principalRef", "actorUserId", "idempotencyKeySha256", "workflowMapping",
                "payloadSha256", "quoteExpiresAtEpochMs", "requestedAtEpochMs",
                "expiresAtEpochMs",
                "containsSecrets", "containsRawDestination", "executionEffect",
                "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("workflowMapping") not in {
                "BUY_ORDER_CREATION", "SELL_ORDER_CREATION"} \
            or value.get("containsSecrets") is not False \
            or value.get("containsRawDestination") is not False \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("action reservation request schema is invalid")
    requested = _time(value["requestedAtEpochMs"], "requestedAtEpochMs")
    expires = _time(value["expiresAtEpochMs"], "expiresAtEpochMs")
    quote_expires = _time(value["quoteExpiresAtEpochMs"], "quoteExpiresAtEpochMs")
    if not requested < expires <= min(requested + MAX_RESERVATION_MS, quote_expires):
        raise ValueError("reservation lifetime is invalid")
    for field in ("idempotencyKeySha256", "payloadSha256"):
        digest = value.get(field)
        if not isinstance(digest, str) or len(digest) != 64 \
                or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"{field} is invalid")
    unsigned = dict(value)
    identifier = unsigned.pop("requestId", None)
    if identifier != "parr_" + _hash(unsigned):
        raise ValueError("action reservation request hash is invalid")
    return dict(value)
