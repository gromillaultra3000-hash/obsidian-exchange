"""Concrete, fail-closed callback wiring for the E4 rehearsal gate.

This module is the composition boundary between the authenticated promotion
verifier, the one-shot owner/reviewer replay registry and the formal rehearsal
receipt ledger.  It is deliberately test-only/non-production: construction
does not read artifacts or create a claim, and ``acquire`` never starts a
runtime.  A receipt-ledger failure after a replay claim is committed is
reported as non-retryable ambiguity; callers must not invoke ``acquire`` again.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from core.e4_authenticated_gate_provider import (
    GateProviderError, SCHEMA as GATE_SCHEMA,
)
from core.e4_owner_reviewer_replay_registry import (
    SQLiteE4OwnerReviewerReplayRegistry,
)
from core.e4_rehearsal_receipt_consumption import (
    SQLiteE4RehearsalReceiptLedger,
)
from core.e4_rehearsal_runner_authorization import (
    validate_authorization_receipt, validate_owner_approval,
)
from core.e4_rehearsal_runner_boundary import validate_runner_boundary
from core.e4_rehearsal_runner_plan import validate_rehearsal_runner_plan
from core.e4_trust_registry_promotion import verify_authenticated_promotion


AUTHENTICATED_EVIDENCE_SCHEMA = "e4-authenticated-owner-reviewer-replay-evidence.v1"
MAX_PUBLIC_JSON_BYTES = 64 * 1024


class PromotionVerifier(Protocol):
    def __call__(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


class ReplayRegistry(Protocol):
    def claim(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


class ReceiptLedger(Protocol):
    def consume(self, **kwargs: Any) -> Mapping[str, Any]:
        ...


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise GateProviderError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GateProviderError(f"{field} is invalid")
    return value


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise GateProviderError(f"{field} is invalid")
    return value


def _read_public_json(path: Path, field: str) -> tuple[bytes, dict[str, Any]]:
    """Read a bounded, no-follow public artifact after verifier success."""
    if not isinstance(path, Path):
        raise GateProviderError(f"{field} path is invalid")
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC |
                     getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_PUBLIC_JSON_BYTES:
            raise GateProviderError(f"{field} file shape is invalid")
        raw = os.read(fd, MAX_PUBLIC_JSON_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise GateProviderError(f"{field} cannot be read safely") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > MAX_PUBLIC_JSON_BYTES:
        raise GateProviderError(f"{field} is oversized")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateProviderError(f"{field} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise GateProviderError(f"{field} root is invalid")
    return raw, value


def _context(*, plan: Mapping[str, Any], receipt: Mapping[str, Any],
             boundary: Mapping[str, Any], evaluated_at_epoch_ms: int) -> dict[str, Any]:
    return {
        "planId": plan["planId"],
        "targetRef": receipt["targetRef"],
        "snapshotSha256": receipt["snapshotSha256"],
        "boundaryId": boundary["boundaryId"],
        "evaluatedAtEpochMs": evaluated_at_epoch_ms,
    }


class E4AuthoritativeGateCallbacks:
    """Acquire the exact E4 gate through the authoritative callback chain.

    All collaborators are injectable so tests can exercise ordering and
    binding without touching the current expired/consumed handoff.  The
    default verifier is the real cryptographic promotion verifier; the caller
    supplies explicitly temporary ledger instances.
    """

    def __init__(self, *, promotion_path: Path,
                 promotion_signature_path: Path,
                 trust_root_public_key_path: Path,
                 registry_path: Path,
                 payload_path: Path,
                 owner_signature_path: Path,
                 owner_public_key_path: Path,
                 envelope_path: Path,
                 reviewer_signature_path: Path,
                 reviewer_public_key_path: Path,
                 timestamp_evidence_path: Path,
                 timestamp_request_path: Path,
                 timestamp_response_path: Path,
                 timestamp_root_path: Path,
                 timestamp_intermediate_path: Path,
                 replay_registry: ReplayRegistry,
                 receipt_ledger: ReceiptLedger,
                 promotion_verifier: PromotionVerifier = verify_authenticated_promotion):
        # Store only handles/configuration.  Do not resolve/read artifacts or
        # touch either ledger here: constructing the adapter is side-effect free.
        self.artifacts = {
            "promotion_path": Path(promotion_path),
            "promotion_signature_path": Path(promotion_signature_path),
            "trust_root_public_key_path": Path(trust_root_public_key_path),
            "registry_path": Path(registry_path),
            "payload_path": Path(payload_path),
            "owner_signature_path": Path(owner_signature_path),
            "owner_public_key_path": Path(owner_public_key_path),
            "envelope_path": Path(envelope_path),
            "reviewer_signature_path": Path(reviewer_signature_path),
            "reviewer_public_key_path": Path(reviewer_public_key_path),
            "timestamp_evidence_path": Path(timestamp_evidence_path),
            "timestamp_request_path": Path(timestamp_request_path),
            "timestamp_response_path": Path(timestamp_response_path),
            "timestamp_root_path": Path(timestamp_root_path),
            "timestamp_intermediate_path": Path(timestamp_intermediate_path),
        }
        if not callable(promotion_verifier):
            raise GateProviderError("promotion verifier is required")
        if not hasattr(replay_registry, "claim") or not hasattr(receipt_ledger, "consume"):
            raise GateProviderError("replay and receipt collaborators are required")
        self.promotion_verifier = promotion_verifier
        self.replay_registry = replay_registry
        self.receipt_ledger = receipt_ledger

    def _verify_promotion(self, *, evaluated_at_epoch_ms: int) -> Mapping[str, Any]:
        try:
            result = self.promotion_verifier(
                **self.artifacts, evaluated_at_epoch_ms=evaluated_at_epoch_ms)
        except Exception as exc:
            if isinstance(exc, GateProviderError):
                raise
            raise GateProviderError("authoritative promotion verification failed") from exc
        if not isinstance(result, Mapping) \
                or result.get("schemaVersion") != "e4-owner-reviewer-verification-result.v1" \
                or result.get("status") != "VERIFIED" \
                or result.get("registryStatus") != "AUTHENTICATED_ACTIVE" \
                or result.get("replayEligible") is not True \
                or result.get("trustedClockAttested") is not True \
                or result.get("executionAuthorized") is not False \
                or result.get("actionAllowed") is not False:
            raise GateProviderError("promotion result is not replay-eligible")
        _epoch(result.get("evaluatedAtEpochMs"), "promotion.evaluatedAtEpochMs")
        _token(result.get("verificationId"), "promotion.verificationId")
        return result

    def _artifact_identity(self, *, promotion_result: Mapping[str, Any],
                           plan: Mapping[str, Any], receipt: Mapping[str, Any],
                           owner_approval: Mapping[str, Any]) -> tuple[str, str, str]:
        promotion_raw, promotion = _read_public_json(
            self.artifacts["promotion_path"], "promotion")
        payload_raw, payload = _read_public_json(
            self.artifacts["payload_path"], "owner payload")
        _envelope_raw, envelope = _read_public_json(
            self.artifacts["envelope_path"], "review envelope")

        if promotion_result.get("promotionPayloadSha256") != hashlib.sha256(
                promotion_raw).hexdigest():
            raise GateProviderError("promotion result is not bound to promotion bytes")
        frozen = promotion.get("frozenBinding")
        if not isinstance(frozen, Mapping):
            raise GateProviderError("promotion frozen binding is missing")
        expected = {
            "planId": plan["planId"], "targetRef": receipt["targetRef"],
            "targetFingerprintSha256": receipt["targetFingerprintSha256"],
            "snapshotSha256": receipt["snapshotSha256"],
            "keyRefSha256": receipt["keyRefSha256"],
            "scope": owner_approval["scope"], "invocationLimit": 1,
        }
        if any(frozen.get(field) != value for field, value in expected.items()):
            raise GateProviderError("promotion binding differs from runner context")

        approval = payload.get("approval")
        if not isinstance(approval, Mapping):
            raise GateProviderError("owner payload approval is missing")
        approval_fields = (
            "planId", "targetRef", "targetFingerprintSha256", "snapshotSha256",
            "snapshotRefSha256", "keyRefSha256", "approvedAtEpochMs",
            "expiresAtEpochMs", "scope", "invocationLimit",
        )
        if any(approval.get(field) != owner_approval.get(field)
               for field in approval_fields):
            raise GateProviderError("owner payload approval differs from receipt")
        payload_id = _token(payload.get("payloadId"), "owner payload ID")
        envelope_id = _token(envelope.get("envelopeId"), "review envelope ID")
        bound = promotion.get("boundEvidence")
        if not isinstance(bound, Mapping):
            raise GateProviderError("promotion artifact binding is missing")
        artifact_identity = {
            "promotionPayloadSha256": hashlib.sha256(promotion_raw).hexdigest(),
            "ownerPayloadSha256": hashlib.sha256(payload_raw).hexdigest(),
            "boundEvidence": dict(bound),
            "payloadId": payload_id,
            "envelopeId": envelope_id,
        }
        return payload_id, envelope_id, _hash(artifact_identity)

    def acquire(self, *, plan: Mapping[str, Any], receipt: Mapping[str, Any],
                owner_approval: Mapping[str, Any], boundary: Mapping[str, Any],
                snapshot_ref: str, key_ref: str,
                evaluated_at_epoch_ms: int) -> Mapping[str, Any]:
        frozen_plan = validate_rehearsal_runner_plan(plan)
        frozen_receipt = validate_authorization_receipt(receipt)
        frozen_approval = validate_owner_approval(owner_approval)
        if frozen_receipt["status"] != "ELIGIBLE" \
                or frozen_receipt["rehearsalExecutionEligible"] is not True:
            raise GateProviderError("authoritative gate requires an eligible receipt")
        if frozen_approval["approvalId"] != frozen_receipt["approvalId"]:
            raise GateProviderError("owner approval and receipt differ")
        frozen_boundary = validate_runner_boundary(
            boundary, plan=frozen_plan, receipt=frozen_receipt,
            snapshot_ref=snapshot_ref, key_ref=key_ref)
        evaluated = _epoch(evaluated_at_epoch_ms, "evaluatedAtEpochMs")
        context = _context(plan=frozen_plan, receipt=frozen_receipt,
                           boundary=frozen_boundary,
                           evaluated_at_epoch_ms=evaluated)

        verified = self._verify_promotion(evaluated_at_epoch_ms=evaluated)
        if verified["evaluatedAtEpochMs"] != evaluated:
            raise GateProviderError("promotion evaluation time differs")
        payload_id, envelope_id, artifact_digest = self._artifact_identity(
            promotion_result=verified, plan=frozen_plan,
            receipt=frozen_receipt, owner_approval=frozen_approval)

        # This is deliberately the only ordering accepted: cryptographic
        # verifier first, one-shot claim second, formal receipt third.
        try:
            claim = self.replay_registry.claim(
                verification_result=verified, payload_id=payload_id,
                envelope_id=envelope_id, artifact_digest=artifact_digest,
                claimed_at_epoch_ms=evaluated)
        except Exception as exc:
            raise GateProviderError("replay claim failed; do not retry blindly") from exc
        if not isinstance(claim, Mapping) \
                or claim.get("status") != "CONSUMED" \
                or claim.get("replayClaimAllowed") is not True:
            raise GateProviderError("replay claim was not consumed")
        claim_id = claim.get("claimId")
        _token(claim_id, "replay claim ID")
        if not claim_id.startswith("e4orr_") or len(claim_id) != 70:
            raise GateProviderError("replay claim ID is invalid")

        invocation_identity = _hash({
            "planId": context["planId"], "targetRef": context["targetRef"],
            "snapshotSha256": context["snapshotSha256"],
            "boundaryId": context["boundaryId"],
            "snapshotRefSha256": frozen_receipt["snapshotRefSha256"],
            "keyRefSha256": frozen_receipt["keyRefSha256"],
            "claimId": claim_id,
        })
        try:
            consumption = self.receipt_ledger.consume(
                plan=frozen_plan, receipt=frozen_receipt,
                owner_approval=frozen_approval, boundary=frozen_boundary,
                snapshot_ref=snapshot_ref, key_ref=key_ref,
                replay_claim_id=claim_id,
                invocation_identity_sha256=invocation_identity,
                invoked_at_epoch_ms=evaluated)
        except Exception as exc:
            raise GateProviderError(
                "receipt consumption failed after replay claim; do not retry") from exc
        if not isinstance(consumption, Mapping) \
                or consumption.get("status") != "CONSUMED" \
                or consumption.get("rehearsalInvocationAllowed") is not True \
                or consumption.get("replayClaimId") != claim_id:
            raise GateProviderError("formal receipt was not consumed")
        if any(consumption.get(field) != context[field]
               for field in ("planId", "targetRef", "snapshotSha256", "boundaryId")):
            raise GateProviderError("formal receipt binding differs")

        authenticated = {
            "schemaVersion": AUTHENTICATED_EVIDENCE_SCHEMA,
            "status": "VERIFIED",
            **context,
            "promotion": {
                "registryStatus": verified["registryStatus"],
                "verificationId": verified["verificationId"],
                "promotionPayloadSha256": verified["promotionPayloadSha256"],
                "timestampGenTimeUtc": verified["timestampGenTimeUtc"],
            },
            "replay": {
                "status": "CONSUMED", "claimId": claim_id,
                "replayClaimAllowed": True, "artifactDigest": artifact_digest,
                "payloadId": payload_id, "envelopeId": envelope_id,
                "executionEffect": "NONE", "actionAllowed": False,
            },
            "authority": {
                "trustRegistryAuthenticated": True,
                "trustedClockAttested": True,
                "replayRegistryChecked": True,
                "replayClaimConsumed": True,
                "hardenedExecutorAvailable": False,
                "rehearsalExecutionEligible": False,
                "executionAuthorized": False,
                "productionDatabaseContactAllowed": False,
                "productionNetworkAllowed": False,
                "productionCredentialsAllowed": False,
                "proposalApplicationAllowed": False,
                "persistentTargetAllowed": False,
                "containsSecrets": False,
                "containsConnectionMaterial": False,
                "executionEffect": "NONE",
                "promotionAllowed": False,
                "actionAllowed": False,
                "moneyActionAllowed": False,
            },
            "verification": dict(verified),
        }
        unsigned = {
            "schemaVersion": GATE_SCHEMA,
            **context,
            "authenticatedEvidence": authenticated,
            "replayConsumption": dict(consumption),
        }
        return {**unsigned, "gateId": "e4aeg_" + _hash(unsigned)}


# Keep the concrete collaborator types visible to callers without forcing an
# actual ledger creation during adapter construction.
__all__ = [
    "E4AuthoritativeGateCallbacks", "SQLiteE4OwnerReviewerReplayRegistry",
    "SQLiteE4RehearsalReceiptLedger",
]
