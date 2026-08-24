"""Dormant server-check adapter for an E4 private confirmation draft."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from .e4_confirmation_draft import validate_confirmation_draft

EVIDENCE_SCHEMA = "private-action-server-check-evidence.v1"
ASSESSMENT_SCHEMA = "private-action-server-assessment.v1"
CHECKS = (
    "AUTHENTICATED_PRINCIPAL",
    "QUOTE_CURRENT",
    "DESTINATION_VALID",
    "DESTINATION_AUTHORIZED_BY_PRINCIPAL",
    "PROVIDER_AVAILABLE",
    "RISK_POLICY_ALLOW",
)
MAX_EVIDENCE_AGE_MS = 30_000
FUTURE_SKEW_MS = 1_000


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 80 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _time(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _digest(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("evidenceSha256 is invalid")
    return value


def build_server_check_evidence(*, draft_id: str, principal_ref: str,
                                actor_user_id: int,
                                check_id: str, observed_at_epoch_ms: int,
                                outcome: str, evidence_sha256: str) -> dict[str, Any]:
    if check_id not in CHECKS or outcome not in {"PASS", "FAIL", "UNAVAILABLE"}:
        raise ValueError("server check verdict is invalid")
    if isinstance(actor_user_id, bool) or not isinstance(actor_user_id, int) \
            or actor_user_id <= 0:
        raise ValueError("actorUserId is invalid")
    unsigned = {
        "schemaVersion": EVIDENCE_SCHEMA, "draftId": _token(draft_id, "draftId"),
        "principalRef": _token(principal_ref, "principalRef"),
        "actorUserId": actor_user_id, "checkId": check_id,
        "observedAtEpochMs": _time(observed_at_epoch_ms, "observedAtEpochMs"),
        "outcome": outcome, "evidenceSha256": _digest(evidence_sha256),
        "containsSecrets": False, "containsRawDestination": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "evidenceId": "pasce_" + _hash(unsigned)}


def validate_server_check_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "evidenceId", "draftId", "principalRef",
                "actorUserId", "checkId",
                "observedAtEpochMs", "outcome", "evidenceSha256", "containsSecrets",
                "containsRawDestination", "executionEffect", "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != EVIDENCE_SCHEMA \
            or value.get("containsSecrets") is not False \
            or value.get("containsRawDestination") is not False \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("server check evidence schema is invalid")
    rebuilt = build_server_check_evidence(
        draft_id=value["draftId"], principal_ref=value["principalRef"],
        actor_user_id=value["actorUserId"],
        check_id=value["checkId"], observed_at_epoch_ms=value["observedAtEpochMs"],
        outcome=value["outcome"], evidence_sha256=value["evidenceSha256"])
    if rebuilt != dict(value):
        raise ValueError("server check evidence hash does not match content")
    return rebuilt


def assess_private_action_draft(*, draft: Mapping[str, Any], preview: Mapping[str, Any],
                                challenge: Mapping[str, Any],
                                acknowledgement_receipt: Mapping[str, Any],
                                idempotency_key: str, principal_ref: str,
                                actor_user_id: int,
                                evidence: Iterable[Mapping[str, Any]],
                                assessed_at_epoch_ms: int) -> dict[str, Any]:
    candidate = validate_confirmation_draft(
        draft, preview=preview, challenge=challenge,
        acknowledgement_receipt=acknowledgement_receipt,
        idempotency_key=idempotency_key)
    if candidate["lane"] != "private_exchange":
        raise ValueError("only the private exchange lane is supported")
    principal = _token(principal_ref, "principalRef")
    if isinstance(actor_user_id, bool) or not isinstance(actor_user_id, int) \
            or actor_user_id <= 0:
        raise ValueError("actorUserId is invalid")
    assessed = _time(assessed_at_epoch_ms, "assessedAtEpochMs")
    if assessed > preview["quote"]["expiresAtEpochMs"]:
        quote_expired = True
    else:
        quote_expired = False
    items = [validate_server_check_evidence(item) for item in evidence]
    if len(items) != len(CHECKS) or len({item["checkId"] for item in items}) != len(items):
        raise ValueError("server check evidence set is incomplete or duplicated")
    if any((item["draftId"], item["principalRef"], item["actorUserId"]) != (
            candidate["draftId"], principal, actor_user_id) for item in items):
        raise ValueError("server check evidence binding is invalid")
    by_check = {item["checkId"]: item for item in items}
    blockers = []
    for check in CHECKS:
        item = by_check[check]
        age = assessed - item["observedAtEpochMs"]
        if age < -FUTURE_SKEW_MS:
            blockers.append(check + "_FUTURE")
        elif age > MAX_EVIDENCE_AGE_MS:
            blockers.append(check + "_STALE")
        elif item["outcome"] != "PASS":
            blockers.append(check + "_" + item["outcome"])
    if quote_expired and "QUOTE_CURRENT_FAIL" not in blockers:
        blockers.append("QUOTE_EXPIRED")
    passed = not blockers
    unsigned = {
        "schemaVersion": ASSESSMENT_SCHEMA, "draftId": candidate["draftId"],
        "principalRef": principal, "actorUserId": actor_user_id,
        "assessedAtEpochMs": assessed,
        "workflowMapping": ("BUY_ORDER_CREATION" if candidate["side"] == "BUY_CRYPTO"
                            else "SELL_ORDER_CREATION"),
        "status": "SERVER_CHECKS_PASSED_OFFLINE" if passed else "NO_GO",
        "blockers": blockers, "evidence": [by_check[check] for check in CHECKS],
        "serverAuthenticationSatisfied": passed,
        "serverStateChecksSatisfied": passed,
        "workflowInvocationEligible": passed,
        "routeConnected": False, "persisted": False,
        "moneyIntentAllowed": False, "containsSecrets": False,
        "containsRawDestination": False, "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "assessmentId": "pasa_" + _hash(unsigned)}


def validate_private_action_assessment(
        value: Mapping[str, Any], *, draft: Mapping[str, Any],
        preview: Mapping[str, Any], challenge: Mapping[str, Any],
        acknowledgement_receipt: Mapping[str, Any], idempotency_key: str,
        principal_ref: str) -> dict[str, Any]:
    required = {"schemaVersion", "assessmentId", "draftId", "principalRef",
                "actorUserId",
                "assessedAtEpochMs", "workflowMapping", "status", "blockers",
                "evidence", "serverAuthenticationSatisfied",
                "serverStateChecksSatisfied", "workflowInvocationEligible",
                "routeConnected", "persisted", "moneyIntentAllowed",
                "containsSecrets", "containsRawDestination", "executionEffect",
                "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != ASSESSMENT_SCHEMA \
            or any(value.get(field) is not False for field in (
                "routeConnected", "persisted", "moneyIntentAllowed", "containsSecrets",
                "containsRawDestination", "actionAllowed")) \
            or value.get("executionEffect") != "NONE":
        raise ValueError("private action assessment schema is invalid")
    rebuilt = assess_private_action_draft(
        draft=draft, preview=preview, challenge=challenge,
        acknowledgement_receipt=acknowledgement_receipt,
        idempotency_key=idempotency_key, principal_ref=principal_ref,
        actor_user_id=value["actorUserId"],
        evidence=value["evidence"], assessed_at_epoch_ms=value["assessedAtEpochMs"])
    if rebuilt != dict(value):
        raise ValueError("private action assessment does not match evidence")
    return rebuilt
