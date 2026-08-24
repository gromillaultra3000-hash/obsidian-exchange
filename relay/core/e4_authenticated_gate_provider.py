"""Provider boundary between authoritative E4 verification and the executor.

The executor must not consume operator-supplied JSON that merely claims
``VERIFIED`` or ``CONSUMED``.  A provider obtains the promotion result from the
cryptographic verifier and then obtains the one-shot receipt result from the
replay/consumption ledger in that order.  The callbacks are deliberately
injected so this contract remains testable without touching current evidence or
starting a runtime.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Protocol

from core.e4_rehearsal_runner_boundary import validate_runner_boundary
from core.e4_rehearsal_runner_plan import validate_rehearsal_runner_plan
from core.e4_rehearsal_runner_authorization import (
    validate_authorization_receipt, validate_owner_approval,
)

SCHEMA = "e4-authenticated-execution-gate.v1"


class GateProviderError(ValueError):
    """A fail-closed gate acquisition or binding error."""


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


class PromotionVerifier(Protocol):
    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


class ReplayConsumer(Protocol):
    def __call__(self, *, authenticated_evidence: Mapping[str, Any],
                 **kwargs: Any) -> Mapping[str, Any]:
        ...


class AuthenticatedExecutionGateProvider(Protocol):
    def acquire(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


class VerifierReplayGateProvider:
    """Acquire a bound gate from verifier then one-shot consumer callbacks."""

    def __init__(self, *, promotion_verifier: PromotionVerifier,
                 replay_consumer: ReplayConsumer):
        if not callable(promotion_verifier) or not callable(replay_consumer):
            raise GateProviderError("gate callbacks are required")
        self.promotion_verifier = promotion_verifier
        self.replay_consumer = replay_consumer

    def acquire(self, *, plan: Mapping[str, Any], receipt: Mapping[str, Any],
                owner_approval: Mapping[str, Any], boundary: Mapping[str, Any],
                snapshot_ref: str, key_ref: str,
                evaluated_at_epoch_ms: int) -> Mapping[str, Any]:
        frozen_plan = validate_rehearsal_runner_plan(plan)
        frozen_receipt = validate_authorization_receipt(receipt)
        frozen_approval = validate_owner_approval(owner_approval)
        if frozen_receipt["status"] != "ELIGIBLE" \
                or frozen_receipt["rehearsalExecutionEligible"] is not True:
            raise GateProviderError("gate provider requires an eligible receipt")
        if frozen_approval["approvalId"] != frozen_receipt["approvalId"]:
            raise GateProviderError("owner approval and receipt differ")
        frozen_boundary = validate_runner_boundary(
            boundary, plan=frozen_plan, receipt=frozen_receipt,
            snapshot_ref=snapshot_ref, key_ref=key_ref)
        context = {
            "planId": frozen_plan["planId"],
            "targetRef": frozen_receipt["targetRef"],
            "snapshotSha256": frozen_receipt["snapshotSha256"],
            "boundaryId": frozen_boundary["boundaryId"],
            "evaluatedAtEpochMs": evaluated_at_epoch_ms,
        }
        authenticated = self.promotion_verifier(
            plan=frozen_plan, receipt=frozen_receipt,
            owner_approval=frozen_approval, boundary=frozen_boundary,
            snapshot_ref=snapshot_ref, key_ref=key_ref,
            evaluated_at_epoch_ms=evaluated_at_epoch_ms)
        if not isinstance(authenticated, Mapping):
            raise GateProviderError("promotion verifier returned no evidence")
        consumed = self.replay_consumer(
            authenticated_evidence=authenticated, **context)
        if not isinstance(consumed, Mapping):
            raise GateProviderError("replay consumer returned no result")
        for source, name in ((authenticated, "authenticated evidence"),
                             (consumed, "replay consumption")):
            if any(field in source and source[field] != expected
                   for field, expected in context.items()
                   if field != "evaluatedAtEpochMs"):
                raise GateProviderError(f"{name} is not context-bound")
        bound_authenticated = {**dict(authenticated), **{
            field: context[field]
            for field in ("planId", "targetRef", "snapshotSha256", "boundaryId")}}
        bound_consumed = {**dict(consumed), **{
            field: context[field]
            for field in ("planId", "targetRef", "snapshotSha256", "boundaryId")}}
        unsigned = {
            "schemaVersion": SCHEMA,
            **context,
            "authenticatedEvidence": bound_authenticated,
            "replayConsumption": bound_consumed,
        }
        return {**unsigned, "gateId": "e4aeg_" + _hash(unsigned)}


def validate_gate_provider_result(value: Mapping[str, Any], *, plan: Mapping[str, Any],
                                  receipt: Mapping[str, Any],
                                  boundary: Mapping[str, Any],
                                  snapshot_ref: str, key_ref: str) -> dict[str, Any]:
    """Validate provider output and reject context drift before execution."""
    if not isinstance(value, Mapping) or value.get("schemaVersion") != SCHEMA:
        raise GateProviderError("gate provider result schema is invalid")
    frozen_plan = validate_rehearsal_runner_plan(plan)
    frozen_receipt = validate_authorization_receipt(receipt)
    frozen_boundary = validate_runner_boundary(
        boundary, plan=frozen_plan, receipt=frozen_receipt,
        snapshot_ref=snapshot_ref, key_ref=key_ref)
    expected = {
        "planId": frozen_plan["planId"], "targetRef": frozen_receipt["targetRef"],
        "snapshotSha256": frozen_receipt["snapshotSha256"],
        "boundaryId": frozen_boundary["boundaryId"],
    }
    if any(value.get(field) != expected_value
           for field, expected_value in expected.items()):
        raise GateProviderError("gate provider context binding differs")
    authenticated = value.get("authenticatedEvidence")
    consumed = value.get("replayConsumption")
    if not isinstance(authenticated, Mapping) or not isinstance(consumed, Mapping):
        raise GateProviderError("gate provider evidence is incomplete")
    if any(source.get(field) != expected_value
           for source in (authenticated, consumed)
           for field, expected_value in expected.items()):
        raise GateProviderError("nested gate evidence binding differs")
    unsigned = dict(value)
    gate_id = unsigned.pop("gateId", None)
    if gate_id != "e4aeg_" + _hash(unsigned):
        raise GateProviderError("gate provider result hash differs")
    return dict(value)
