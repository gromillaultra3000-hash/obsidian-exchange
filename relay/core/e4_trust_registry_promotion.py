"""Fail-closed promotion of the public E4 trust registry.

The trust-root signature authenticates only the already reviewed public
registry binding.  This module never grants execution authority, never opens
the snapshot, never contacts a TSA, and never claims replay state.  It
rechecks the owner/reviewer artifacts and the DigiCert RFC 3161 response using
explicitly supplied public certificate files before returning a result that
the temporary replay ledger may claim.
"""

from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .e4_owner_reviewer_verifier import (
    VerificationInputError,
    _file_sha256,
    _load_and_validate,
    _public_key,
    _verify_ssh_signature,
)


PROMOTION_SCHEMA = "e4-trust-registry-promotion-payload.v1"
RESULT_SCHEMA = "e4-owner-reviewer-verification-result.v1"
ROOT_ISSUER = "e4-trust-root"
ROOT_NAMESPACE = "e4-trust-root"
MAX_BYTES = {
    "promotion": 64 * 1024,
    "signature": 8 * 1024,
    "timestamp_request": 16 * 1024,
    "timestamp_response": 32 * 1024,
    "certificate": 32 * 1024,
    "evidence": 32 * 1024,
}


class PromotionVerificationError(ValueError):
    """Raised when authenticated registry promotion cannot be proven."""


def _read_file(path: Path, kind: str) -> bytes:
    if not isinstance(path, Path):
        raise PromotionVerificationError(f"{kind} path is invalid")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise PromotionVerificationError(f"{kind} is not regular")
            if metadata.st_size > MAX_BYTES[kind]:
                raise PromotionVerificationError(f"{kind} is oversized")
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                data = handle.read(MAX_BYTES[kind] + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    except (FileNotFoundError, OSError) as exc:
        raise PromotionVerificationError(f"{kind} cannot be read") from exc
    if len(data) > MAX_BYTES[kind]:
        raise PromotionVerificationError(f"{kind} is oversized")
    return data


def _json(path: Path, kind: str) -> tuple[bytes, dict[str, Any]]:
    raw = _read_file(path, kind)

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PromotionVerificationError("duplicate JSON field")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=lambda item: (_ for _ in ()).throw(
                PromotionVerificationError("non-finite JSON value")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PromotionVerificationError(f"{kind} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise PromotionVerificationError(f"{kind} root is not an object")
    return raw, value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise PromotionVerificationError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PromotionVerificationError(f"{field} is invalid")
    return value


def _iso_epoch_ms(value: Any, field: str) -> int:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise PromotionVerificationError(f"{field} is invalid")
    try:
        parsed = _datetime.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise PromotionVerificationError(f"{field} is invalid") from exc
    return int(parsed.timestamp() * 1000)


def _verify_timestamp(*, request_path: Path, response_path: Path,
                      root_path: Path, intermediate_path: Path) -> bool:
    for path, kind in ((request_path, "timestamp_request"),
                       (response_path, "timestamp_response"),
                       (root_path, "certificate"),
                       (intermediate_path, "certificate")):
        _read_file(path, kind)
    openssl = shutil.which("openssl")
    if openssl is None:
        return False
    try:
        result = subprocess.run(
            [openssl, "ts", "-verify", "-queryfile", str(request_path),
             "-in", str(response_path), "-CAfile", str(root_path),
             "-untrusted", str(intermediate_path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5, check=False, close_fds=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and b"Verification: OK" in result.stdout


def _unsigned_result(*, evaluated_at_epoch_ms: int,
                     promotion_payload_sha256: str,
                     timestamp_gen_time_utc: str) -> dict[str, Any]:
    unsigned = {
        "schemaVersion": RESULT_SCHEMA,
        "status": "VERIFIED",
        "evaluatedAtEpochMs": evaluated_at_epoch_ms,
        "ownerSignatureVerified": True,
        "reviewerSignatureVerified": True,
        "exactBindingVerified": True,
        "freshnessVerified": True,
        "registryStatus": "AUTHENTICATED_ACTIVE",
        "replayState": "ELIGIBLE_NOT_CLAIMED",
        "trustedClockAttested": True,
        "replayRegistryChecked": False,
        "replayEligible": True,
        "hardenedExecutorAvailable": False,
        "promotionPayloadSha256": promotion_payload_sha256,
        "timestampGenTimeUtc": timestamp_gen_time_utc,
        "blockers": [
            "REPLAY_REGISTRY_NOT_CHECKED",
            "HARDENED_EXECUTOR_NOT_AVAILABLE",
        ],
        "rehearsalExecutionEligible": False,
        "executionAuthorized": False,
        "productionDatabaseContactAllowed": False,
        "productionNetworkAllowed": False,
        "productionCredentialsAllowed": False,
        "proposalApplicationAllowed": False,
        "persistentTargetAllowed": False,
        "automaticRetryAllowed": False,
        "containsSecrets": False,
        "containsConnectionMaterial": False,
        "executionEffect": "NONE",
        "promotionAllowed": False,
        "actionAllowed": False,
    }
    verification_id = hashlib.sha256(json.dumps(
        unsigned, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    return {**unsigned, "verificationId": "e4ovr_" + verification_id}


def verify_authenticated_promotion(
    *, promotion_path: Path,
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
    evaluated_at_epoch_ms: int,
) -> dict[str, Any]:
    """Verify promotion and return a replay-eligible, non-executing result."""
    evaluated = _epoch(evaluated_at_epoch_ms, "evaluatedAtEpochMs")
    promotion_raw, promotion = _json(promotion_path, "promotion")
    promotion_signature = _read_file(promotion_signature_path, "signature")
    root_raw, root_line, root_fingerprint = _public_key(
        trust_root_public_key_path, "public_key")
    if promotion.get("schemaVersion") != PROMOTION_SCHEMA \
            or promotion.get("status") != "READY_FOR_OFFLINE_TRUST_ROOT_SIGNATURE":
        raise PromotionVerificationError("promotion status is invalid")
    authority = promotion.get("authority")
    if not isinstance(authority, Mapping) \
            or authority.get("registryPromotionAuthorized") is not False \
            or authority.get("executionAuthorized") is not False \
            or authority.get("executionEffect") != "NONE":
        raise PromotionVerificationError("promotion authority is not fail-closed")
    trust_root = promotion.get("trustRoot")
    if not isinstance(trust_root, Mapping) \
            or trust_root.get("issuerId") != ROOT_ISSUER \
            or trust_root.get("fingerprint") != root_fingerprint \
            or trust_root.get("publicKeySha256") != _file_sha256(root_raw) \
            or trust_root.get("offlineOriginAttested") is not True \
            or trust_root.get("privateKeyMustRemainOffline") is not True:
        raise PromotionVerificationError("trust-root binding is invalid")
    if not _verify_ssh_signature(
            public_line=root_line, principal=ROOT_ISSUER,
            namespace=ROOT_NAMESPACE, signature=promotion_signature,
            message=promotion_raw):
        raise PromotionVerificationError("trust-root promotion signature invalid")

    registry_raw, registry = _json(registry_path, "promotion")
    expected_promotion = promotion.get("promotion")
    if not isinstance(expected_promotion, Mapping) \
            or expected_promotion.get("registryCandidateSha256") \
            != _file_sha256(registry_raw) \
            or expected_promotion.get("currentStatus") \
            != "CANDIDATE_NOT_AUTHORIZED" \
            or expected_promotion.get("requestedStatus") \
            != "AUTHENTICATED_ACTIVE" \
            or registry.get("status") != "CANDIDATE_NOT_AUTHORIZED":
        raise PromotionVerificationError("registry candidate binding is invalid")
    registry_id = expected_promotion.get("registryId")
    if registry.get("trustAnchors", {}).get("registryId") != registry_id:
        raise PromotionVerificationError("registry id binding is invalid")

    evidence_raw, evidence = _json(timestamp_evidence_path, "evidence")
    bound = promotion.get("boundEvidence")
    if not isinstance(bound, Mapping):
        raise PromotionVerificationError("bound evidence is invalid")
    if bound.get("timestampEvidenceSha256") != _file_sha256(evidence_raw) \
            or evidence.get("verification", {}).get("status") != "VERIFIED" \
            or evidence.get("provider", {}).get("name") != "DigiCert" \
            or evidence.get("authority", {}).get("trustedClockAttested") is not True:
        raise PromotionVerificationError("timestamp evidence binding is invalid")
    response = evidence.get("timestampResponse", {})
    imprint = evidence.get("messageImprint", {})
    signature_digest = bound.get("ownerSignatureSha256")
    if response.get("responseStatus") != "GRANTED" \
            or imprint.get("hashAlgorithm") != "sha256" \
            or imprint.get("value") != signature_digest \
            or imprint.get("matchesBoundArtifact") is not True:
        raise PromotionVerificationError("timestamp imprint is invalid")
    timestamp_gen_time = response.get("genTimeUtc")
    timestamp_epoch = _iso_epoch_ms(timestamp_gen_time, "timestamp.genTimeUtc")
    if not _verify_timestamp(
            request_path=timestamp_request_path,
            response_path=timestamp_response_path,
            root_path=timestamp_root_path,
            intermediate_path=timestamp_intermediate_path):
        raise PromotionVerificationError("DigiCert timestamp verification failed")

    try:
        (validated_registry, payload, envelope, owner_signature,
         reviewer_signature, owner_line, reviewer_line, payload_raw,
         envelope_raw) = _load_and_validate(
            registry_path=registry_path, payload_path=payload_path,
            owner_signature_path=owner_signature_path,
            owner_public_key_path=owner_public_key_path,
            envelope_path=envelope_path,
            reviewer_signature_path=reviewer_signature_path,
            reviewer_public_key_path=reviewer_public_key_path)
    except VerificationInputError as exc:
        raise PromotionVerificationError("owner/reviewer binding invalid") from exc
    if validated_registry is not registry and validated_registry.get("status") \
            != "CANDIDATE_NOT_AUTHORIZED":
        raise PromotionVerificationError("unexpected registry state")
    owner_ok = _verify_ssh_signature(
        public_line=owner_line, principal="e4-owner-signing-v2",
        namespace="e4-owner@obsidian-exchange.local",
        signature=owner_signature, message=payload_raw)
    reviewer_ok = _verify_ssh_signature(
        public_line=reviewer_line, principal="e4-independent-reviewer",
        namespace="e4-reviewer@obsidian-exchange.local",
        signature=reviewer_signature, message=envelope_raw)
    if not owner_ok or not reviewer_ok:
        raise PromotionVerificationError("owner/reviewer signature invalid")

    approval = payload["approval"]
    approved = _epoch(approval["approvedAtEpochMs"], "approval.approvedAtEpochMs")
    expires = _epoch(approval["expiresAtEpochMs"], "approval.expiresAtEpochMs")
    if not approved <= timestamp_epoch <= expires \
            or not approved <= evaluated <= expires:
        raise PromotionVerificationError("approval or timestamp window is invalid")
    if bound.get("ownerPayloadSha256") != _file_sha256(payload_raw) \
            or bound.get("ownerSignatureSha256") != _file_sha256(owner_signature) \
            or bound.get("reviewerEnvelopeSha256") != _file_sha256(envelope_raw) \
            or bound.get("reviewerSignatureSha256") != _file_sha256(reviewer_signature):
        raise PromotionVerificationError("promotion artifact digest differs")
    return _unsigned_result(
        evaluated_at_epoch_ms=evaluated,
        promotion_payload_sha256=_file_sha256(promotion_raw),
        timestamp_gen_time_utc=timestamp_gen_time)
