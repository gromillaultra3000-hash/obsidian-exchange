"""Fail-closed verifier for the public E4 owner/reviewer handoff artifacts.

This module verifies two SSH signatures, exact public binding, freshness and
the candidate trust-registry state.  It deliberately does not create an
authorization receipt, consume replay state, run Docker, open PostgreSQL or
grant execution authority.  A conversation-confirmed registry candidate is
reported as evidence only until an authenticated registry and hardened
executor exist.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping


RESULT_SCHEMA = "e4-owner-reviewer-verification-result.v1"
REGISTRY_SCHEMA_PREFIX = "e4-owner-reviewer-trust-anchor-and-binding-candidate."
PAYLOAD_SCHEMA = "e4-owner-decision-payload.v1"
ENVELOPE_SCHEMA = "e4-reviewer-review-envelope.v1"
OWNER_NAMESPACE = "e4-owner@obsidian-exchange.local"
REVIEWER_NAMESPACE = "e4-reviewer@obsidian-exchange.local"
OWNER_ISSUER = "e4-owner-signing-v2"
REVIEWER_ISSUER = "e4-independent-reviewer"
MAX_CLOCK_SKEW_MS = 1_000
MAX_FILE_BYTES = {
    "registry": 32 * 1024,
    "payload": 64 * 1024,
    "envelope": 64 * 1024,
    "signature": 8 * 1024,
    "public_key": 4 * 1024,
}
AUTHORITY_FALSE_FIELDS = (
    "authenticated", "ownerApproval", "independentReview",
    "rehearsalExecutionEligible", "executionAuthorized",
    "productionDatabaseContactAllowed", "productionNetworkAllowed",
    "productionCredentialsAllowed", "proposalApplicationAllowed",
    "persistentTargetAllowed", "automaticRetryAllowed", "promotionAllowed",
    "actionAllowed", "containsSecrets", "containsConnectionMaterial",
)


class VerificationInputError(ValueError):
    """Raised internally when an untrusted artifact is malformed."""


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise VerificationInputError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VerificationInputError(f"{field} is invalid")
    return value


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationInputError("duplicate JSON field")
        result[key] = value
    return result


def _load_json(path: Path, kind: str) -> tuple[bytes, dict[str, Any]]:
    raw = _read_file(path, kind)
    try:
        value = json.loads(raw.decode("utf-8"),
                           object_pairs_hook=_no_duplicate_pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(
                               VerificationInputError("non-finite JSON value")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationInputError(f"{kind} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise VerificationInputError(f"{kind} root is not an object")
    return raw, value


def _read_file(path: Path, kind: str) -> bytes:
    if not isinstance(path, Path):
        raise VerificationInputError(f"{kind} path is invalid")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise VerificationInputError(f"{kind} is not a regular file")
            if metadata.st_size > MAX_FILE_BYTES[kind]:
                raise VerificationInputError(f"{kind} is oversized")
            with os.fdopen(fd, "rb") as handle:
                fd = -1
                data = handle.read(MAX_FILE_BYTES[kind] + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    except (FileNotFoundError, OSError) as exc:
        raise VerificationInputError(f"{kind} cannot be read") from exc
    if len(data) > MAX_FILE_BYTES[kind]:
        raise VerificationInputError(f"{kind} is oversized")
    return data


def _public_key(path: Path, kind: str) -> tuple[bytes, str, str]:
    raw = _read_file(path, kind)
    try:
        lines = [line.strip() for line in raw.decode("utf-8").splitlines()
                 if line.strip()]
    except UnicodeDecodeError as exc:
        raise VerificationInputError(f"{kind} is not UTF-8") from exc
    if len(lines) != 1:
        raise VerificationInputError(f"{kind} line shape is invalid")
    parts = lines[0].split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise VerificationInputError(f"{kind} algorithm is invalid")
    try:
        key_blob = base64.b64decode(parts[1], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise VerificationInputError(f"{kind} key encoding is invalid") from exc
    if not key_blob:
        raise VerificationInputError(f"{kind} key blob is empty")
    fingerprint = base64.b64encode(
        hashlib.sha256(key_blob).digest()).decode().rstrip("=")
    return raw, lines[0], "SHA256:" + fingerprint


def _require_authority_false(value: Mapping[str, Any], field: str) -> None:
    authority = value.get("authority")
    if not isinstance(authority, Mapping):
        raise VerificationInputError(f"{field} authority is invalid")
    required = ("authenticated", "executionAuthorized", "containsSecrets",
                "containsConnectionMaterial")
    if any(authority.get(item) is not False for item in required) \
            or any(isinstance(item, bool) and item is not False
                   for key, item in authority.items()) \
            or authority.get("executionEffect") != "NONE":
        raise VerificationInputError(f"{field} authority is not fail-closed")


def _verify_ssh_signature(*, public_line: str, principal: str, namespace: str,
                          signature: bytes, message: bytes) -> bool:
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        return False
    with tempfile.TemporaryDirectory(prefix="e4-owner-review-verify-") as directory:
        root = Path(directory)
        allowed = root / "allowed-signers"
        signature_path = root / "signature"
        allowed.write_text(principal + " " + public_line + "\n", encoding="utf-8")
        signature_path.write_bytes(signature)
        try:
            completed = subprocess.run(
                [ssh_keygen, "-Y", "verify", "-f", str(allowed), "-I",
                 principal, "-n", namespace, "-s", str(signature_path)],
                input=message, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=5, close_fds=True)
        except (OSError, subprocess.SubprocessError):
            return False
    return completed.returncode == 0


def _expected_binding(*, registry: Mapping[str, Any], payload: Mapping[str, Any]) \
        -> dict[str, Any]:
    frozen = payload["frozenBinding"]
    approval = payload["approval"]
    binding = registry["binding"]
    expected = {
        "planId": frozen["planId"],
        "planSourceSha256": frozen["planSourceSha256"],
        "evidenceManifestSha256": frozen["evidenceManifestSha256"],
        "stagedManifestSha256": frozen["stagedManifestSha256"],
        "targetRef": approval["targetRef"],
        "targetFingerprintSha256": approval["targetFingerprintSha256"],
        "snapshotRefSha256": approval["snapshotRefSha256"],
        "snapshotSha256": approval["snapshotSha256"],
        "keyRefSha256": approval["keyRefSha256"],
        "immutableHandle": binding["immutableHandle"],
        "scope": frozen["scope"],
        "invocationLimit": frozen["invocationLimit"],
    }
    if binding != expected:
        raise VerificationInputError("registry binding differs from payload")
    return expected


def _load_and_validate(*, registry_path: Path, payload_path: Path,
                       owner_signature_path: Path, owner_public_key_path: Path,
                       envelope_path: Path, reviewer_signature_path: Path,
                       reviewer_public_key_path: Path) -> tuple[dict[str, Any], ...]:
    registry_raw, registry = _load_json(registry_path, "registry")
    payload_raw, payload = _load_json(payload_path, "payload")
    envelope_raw, envelope = _load_json(envelope_path, "envelope")
    owner_signature = _read_file(owner_signature_path, "signature")
    reviewer_signature = _read_file(reviewer_signature_path, "signature")
    owner_public_raw, owner_public_line, owner_fingerprint = _public_key(
        owner_public_key_path, "public_key")
    reviewer_public_raw, reviewer_public_line, reviewer_fingerprint = _public_key(
        reviewer_public_key_path, "public_key")

    if not registry.get("schemaVersion", "").startswith(REGISTRY_SCHEMA_PREFIX) \
            or registry.get("status") != "CANDIDATE_NOT_AUTHORIZED":
        raise VerificationInputError("registry candidate status is unexpected")
    trust = registry.get("trustAnchors")
    if not isinstance(trust, Mapping) or trust.get("registryId") != registry.get(
            "trustAnchors", {}).get("registryId"):
        raise VerificationInputError("registry trust anchors are invalid")
    _require_authority_false(registry, "registry")

    if payload.get("schemaVersion") != PAYLOAD_SCHEMA:
        raise VerificationInputError("payload schema is invalid")
    if payload.get("trustAnchors", {}).get("registryProposalSha256") \
            != _file_sha256(registry_raw):
        raise VerificationInputError("payload registry proposal binding differs")
    _require_authority_false(payload, "payload")

    if envelope.get("schemaVersion") != ENVELOPE_SCHEMA \
            or envelope.get("status") != "READY_FOR_OFFLINE_REVIEWER_SIGNATURE" \
            or envelope.get("disposition") != "REVIEW_PASS_NON_AUTHORITATIVE":
        raise VerificationInputError("review envelope status is invalid")
    _require_authority_false(envelope, "envelope")

    owner_anchor = trust.get("owner")
    reviewer_anchor = trust.get("reviewer")
    if not isinstance(owner_anchor, Mapping) or not isinstance(reviewer_anchor, Mapping):
        raise VerificationInputError("registry key anchors are invalid")
    if owner_anchor.get("publicKeySha256") != _file_sha256(owner_public_raw) \
            or owner_anchor.get("fingerprint") != owner_fingerprint \
            or owner_anchor.get("issuerId") != OWNER_ISSUER:
        raise VerificationInputError("owner trust anchor differs from key")
    if reviewer_anchor.get("publicKeySha256") != _file_sha256(reviewer_public_raw) \
            or reviewer_anchor.get("fingerprint") != reviewer_fingerprint \
            or reviewer_anchor.get("issuerId") != REVIEWER_ISSUER:
        raise VerificationInputError("reviewer trust anchor differs from key")

    payload_trust = payload.get("trustAnchors")
    if not isinstance(payload_trust, Mapping) \
            or payload_trust.get("registryId") != trust.get("registryId"):
        raise VerificationInputError("payload trust binding differs")
    for role in ("owner", "reviewer"):
        payload_anchor = payload_trust.get(role)
        registry_anchor = trust.get(role)
        if not isinstance(payload_anchor, Mapping) \
                or not isinstance(registry_anchor, Mapping) \
                or any(payload_anchor.get(field) != registry_anchor.get(field)
                       for field in ("role", "issuerId", "trustRootId",
                                     "publicKeySha256", "fingerprint")):
            raise VerificationInputError("payload trust binding differs")

    _expected_binding(registry=registry, payload=payload)
    owner_payload = envelope.get("ownerPayload")
    if not isinstance(owner_payload, Mapping):
        raise VerificationInputError("review envelope owner payload is invalid")
    if owner_payload.get("payloadSha256") != _file_sha256(payload_raw) \
            or owner_payload.get("ownerSignatureSha256") != _file_sha256(owner_signature) \
            or owner_payload.get("payloadId") != payload.get("payloadId"):
        raise VerificationInputError("review envelope payload binding differs")
    if owner_payload.get("ownerFingerprint") != owner_fingerprint \
            or owner_payload.get("ownerIssuerId") != OWNER_ISSUER:
        raise VerificationInputError("review envelope owner identity differs")
    if envelope.get("reviewer", {}).get("fingerprint") != reviewer_fingerprint \
            or envelope.get("reviewer", {}).get("publicKeySha256") \
            != _file_sha256(reviewer_public_raw):
        raise VerificationInputError("review envelope reviewer identity differs")
    if envelope.get("binding") != _expected_binding(registry=registry, payload=payload):
        raise VerificationInputError("review envelope binding differs")
    approval = payload.get("approval", {})
    if owner_payload.get("approvedAtEpochMs") != approval.get("approvedAtEpochMs") \
            or owner_payload.get("expiresAtEpochMs") != approval.get("expiresAtEpochMs"):
        raise VerificationInputError("review envelope freshness binding differs")
    for item in (payload.get("replay", {}), envelope):
        if not isinstance(item, Mapping):
            raise VerificationInputError("replay envelope is invalid")
    if payload["replay"].get("nonceSha256") == envelope.get("reviewNonceSha256"):
        raise VerificationInputError("owner and reviewer nonces are reused")

    return (registry, payload, envelope, owner_signature, reviewer_signature,
            owner_public_line, reviewer_public_line, payload_raw, envelope_raw)


def _result(*, evaluated_at_epoch_ms: int, owner_signature_verified: bool,
            reviewer_signature_verified: bool, exact_binding_verified: bool,
            freshness_verified: bool, registry_status: str,
            blockers: list[str]) -> dict[str, Any]:
    unsigned = {
        "schemaVersion": RESULT_SCHEMA,
        "status": "NO_GO",
        "evaluatedAtEpochMs": evaluated_at_epoch_ms,
        "ownerSignatureVerified": owner_signature_verified,
        "reviewerSignatureVerified": reviewer_signature_verified,
        "exactBindingVerified": exact_binding_verified,
        "freshnessVerified": freshness_verified,
        "registryStatus": registry_status,
        "replayState": "NOT_CHECKED",
        "trustedClockAttested": False,
        "replayRegistryChecked": False,
        "replayEligible": False,
        "hardenedExecutorAvailable": False,
        "blockers": blockers,
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
    return {**unsigned, "verificationId": "e4ovr_" + _hash(unsigned)}


def verify_owner_reviewer_artifacts(*, registry_path: Path,
                                    payload_path: Path,
                                    owner_signature_path: Path,
                                    owner_public_key_path: Path,
                                    envelope_path: Path,
                                    reviewer_signature_path: Path,
                                    reviewer_public_key_path: Path,
                                    evaluated_at_epoch_ms: int) -> dict[str, Any]:
    """Verify artifacts and return an evidence-only, always-NO_GO result."""
    evaluated = _epoch(evaluated_at_epoch_ms, "evaluatedAtEpochMs")
    try:
        (registry, payload, envelope, owner_signature, reviewer_signature,
         owner_public_line, reviewer_public_line, payload_raw,
         envelope_raw) = _load_and_validate(
            registry_path=registry_path, payload_path=payload_path,
            owner_signature_path=owner_signature_path,
            owner_public_key_path=owner_public_key_path,
            envelope_path=envelope_path,
            reviewer_signature_path=reviewer_signature_path,
            reviewer_public_key_path=reviewer_public_key_path)
    except VerificationInputError:
        return _result(
            evaluated_at_epoch_ms=evaluated,
            owner_signature_verified=False, reviewer_signature_verified=False,
            exact_binding_verified=False, freshness_verified=False,
            registry_status="INVALID_ARTIFACT", blockers=["ARTIFACT_INVALID"])

    owner_ok = _verify_ssh_signature(
        public_line=owner_public_line, principal=OWNER_ISSUER,
        namespace=OWNER_NAMESPACE, signature=owner_signature,
        message=payload_raw)
    reviewer_ok = _verify_ssh_signature(
        public_line=reviewer_public_line, principal=REVIEWER_ISSUER,
        namespace=REVIEWER_NAMESPACE, signature=reviewer_signature,
        message=envelope_raw)
    approval = payload["approval"]
    approved = approval["approvedAtEpochMs"]
    expires = approval["expiresAtEpochMs"]
    freshness_ok = approved - MAX_CLOCK_SKEW_MS <= evaluated <= expires
    blockers: list[str] = []
    if not owner_ok:
        blockers.append("OWNER_SIGNATURE_INVALID")
    if not reviewer_ok:
        blockers.append("REVIEWER_SIGNATURE_INVALID")
    if not freshness_ok:
        blockers.append("OWNER_WINDOW_NOT_CURRENT")
    blockers.extend((
        "TRUST_REGISTRY_NOT_AUTHENTICATED",
        "TRUSTED_CLOCK_NOT_ATTESTED",
        "REPLAY_REGISTRY_NOT_CHECKED",
        "HARDENED_EXECUTOR_NOT_AVAILABLE",
    ))
    return _result(
        evaluated_at_epoch_ms=evaluated,
        owner_signature_verified=owner_ok,
        reviewer_signature_verified=reviewer_ok,
        exact_binding_verified=True,
        freshness_verified=freshness_ok,
        registry_status=registry["status"], blockers=blockers)
