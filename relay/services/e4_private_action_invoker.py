"""Test-only invocation boundary for the complete E4 private action chain."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Protocol

from core.e4_action_acknowledgement import (
    validate_acknowledgement_challenge, validate_acknowledgement_receipt,
)
from core.e4_action_preview import validate_action_preview
from core.e4_action_reservation import (
    build_action_reservation_request, validate_action_reservation_request,
)
from core.e4_confirmation_draft import validate_confirmation_draft
from core.e4_private_action_adapter import validate_private_action_assessment

SCHEMA = "private-action-test-invocation-result.v1"


class HandoffStore(Protocol):
    def handoff(self, **kwargs) -> dict[str, Any]: ...


class E4TestOnlyHandoffStore:
    """Explicit fixture wrapper; this is isolation, not production authorization."""

    __slots__ = ("_delegate",)

    def __init__(self, delegate: HandoffStore):
        if not callable(getattr(delegate, "handoff", None)):
            raise TypeError("test-only handoff delegate is invalid")
        self._delegate = delegate

    def handoff(self, **kwargs) -> dict[str, Any]:
        return self._delegate.handoff(**kwargs)


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _require_trusted_identity(*, assessment: Mapping[str, Any], order: dict[str, Any],
                              trusted_principal_ref: str,
                              trusted_actor_user_id: int,
                              trusted_web_user_id: int) -> None:
    # Request-supplied evidence is not authentication; these values must come
    # from the future route's already-authenticated server context.
    if not isinstance(trusted_principal_ref, str) or not 1 <= len(trusted_principal_ref) <= 80 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                   for char in trusted_principal_ref):
        raise ValueError("trusted principalRef is invalid")
    for value, field in ((trusted_actor_user_id, "trusted actorUserId"),
                         (trusted_web_user_id, "trusted webUserId")):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} is invalid")
    if not isinstance(assessment, Mapping):
        raise ValueError("assessment identity is invalid")
    if (assessment.get("principalRef"), assessment.get("actorUserId")) != (
            trusted_principal_ref, trusted_actor_user_id):
        raise ValueError("assessment identity does not match trusted caller")
    order_actor = order.get("user_id") if isinstance(order, dict) else None
    if isinstance(order_actor, bool) or not isinstance(order_actor, int) \
            or order_actor != trusted_actor_user_id:
        raise ValueError("order actor does not match trusted caller")
    if "web_user_id" in order:
        web_user_id = order["web_user_id"]
        if isinstance(web_user_id, bool) or not isinstance(web_user_id, int) \
                or web_user_id != trusted_web_user_id:
            raise ValueError("order web user does not match trusted caller")


def invoke_private_action_test_only(
        *, store: E4TestOnlyHandoffStore, preview: Mapping[str, Any],
        challenge: Mapping[str, Any], acknowledgement_receipt: Mapping[str, Any],
        draft: Mapping[str, Any], idempotency_key: str,
        assessment: Mapping[str, Any], reservation: Mapping[str, Any],
        order: dict[str, Any], trusted_principal_ref: str,
        trusted_actor_user_id: int, trusted_web_user_id: int) -> dict[str, Any]:
    if not isinstance(store, E4TestOnlyHandoffStore):
        raise ValueError("test-only invocation requires an explicit fixture wrapper")
    _require_trusted_identity(
        assessment=assessment, order=order,
        trusted_principal_ref=trusted_principal_ref,
        trusted_actor_user_id=trusted_actor_user_id,
        trusted_web_user_id=trusted_web_user_id)
    action = validate_action_preview(preview)
    gate = validate_acknowledgement_challenge(challenge, preview=action)
    receipt = validate_acknowledgement_receipt(
        acknowledgement_receipt, preview=action, challenge=gate)
    candidate = validate_confirmation_draft(
        draft, preview=action, challenge=gate,
        acknowledgement_receipt=receipt, idempotency_key=idempotency_key)
    assessed = validate_private_action_assessment(
        assessment, draft=candidate, preview=action, challenge=gate,
        acknowledgement_receipt=receipt, idempotency_key=idempotency_key,
        principal_ref=trusted_principal_ref)
    reserved = validate_action_reservation_request(reservation)
    rebuilt = build_action_reservation_request(
        draft=candidate, assessment=assessed,
        requested_at_epoch_ms=reserved["requestedAtEpochMs"],
        expires_at_epoch_ms=reserved["expiresAtEpochMs"])
    if rebuilt != reserved:
        raise ValueError("reservation does not bind the validated invocation chain")
    try:
        result = store.handoff(reservation=reserved, draft=candidate,
                               assessment=assessed, order=order)
        action_name = result.get("action") if isinstance(result, Mapping) else None
        if action_name not in {"created", "replayed", "conflict"}:
            raise RuntimeError("invalid handoff result")
        if action_name in {"created", "replayed"}:
            result_kind = result.get("result_kind")
            result_id = result.get("result_id")
            if result_kind not in {"BUY_ORDER", "SELL_ORDER"} \
                    or isinstance(result_id, bool) or not isinstance(result_id, int) \
                    or result_id <= 0:
                raise RuntimeError("invalid handoff result")
            status = "CREATED_TEST_ONLY" if action_name == "created" else "REPLAYED_TEST_ONLY"
            reason = "NONE"
        else:
            status, reason, result_kind, result_id = "NO_GO", "CONFLICT", None, None
    except TimeoutError:
        status, reason, result_kind, result_id = "NO_GO", "STORE_TIMEOUT", None, None
    except Exception:
        status, reason, result_kind, result_id = "NO_GO", "STORE_ERROR", None, None
    unsigned = {
        "schemaVersion": SCHEMA, "draftId": candidate["draftId"],
        "assessmentId": assessed["assessmentId"],
        "reservationRequestId": reserved["requestId"],
        "principalRef": assessed["principalRef"], "actorUserId": assessed["actorUserId"],
        "status": status, "reason": reason, "resultKind": result_kind,
        "resultId": result_id, "testOnly": True,
        "testDatabaseWriteOccurred": status == "CREATED_TEST_ONLY",
        "productionInvocationAllowed": False, "routeConnected": False,
        "containsSecrets": False, "containsRawDestination": False,
        "executionEffect": ("TEST_DATABASE_WRITE" if status == "CREATED_TEST_ONLY"
                            else "NONE"),
        "actionAllowed": False,
    }
    return {**unsigned, "invocationId": "pati_" + _hash(unsigned)}


def validate_test_invocation_result(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "invocationId", "draftId", "assessmentId",
                "reservationRequestId", "principalRef", "actorUserId", "status",
                "reason", "resultKind", "resultId", "testOnly",
                "testDatabaseWriteOccurred", "productionInvocationAllowed",
                "routeConnected", "containsSecrets", "containsRawDestination",
                "executionEffect", "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA or value.get("testOnly") is not True \
            or value.get("productionInvocationAllowed") is not False \
            or value.get("routeConnected") is not False \
            or value.get("containsSecrets") is not False \
            or value.get("containsRawDestination") is not False \
            or value.get("actionAllowed") is not False:
        raise ValueError("test invocation result schema is invalid")
    unsigned = dict(value)
    identifier = unsigned.pop("invocationId", None)
    if identifier != "pati_" + _hash(unsigned):
        raise ValueError("test invocation result hash is invalid")
    expected_write = value.get("status") == "CREATED_TEST_ONLY"
    expected_effect = "TEST_DATABASE_WRITE" if expected_write else "NONE"
    if value.get("testDatabaseWriteOccurred") is not expected_write \
            or value.get("executionEffect") != expected_effect:
        raise ValueError("test invocation result effect is inconsistent")
    return dict(value)
