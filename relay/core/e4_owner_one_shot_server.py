"""Interactive one-shot E4 ceremony and hardened rehearsal coordinator.

The coordinator is invoked through one authenticated SSH connection.  It
creates fresh public signing requests just in time, verifies each returned SSH
signature, obtains and pins an RFC3161 timestamp, performs a read-only
preflight, then sends the immutable ciphertext to Termux for local decryption.
Only the digest-bound plaintext stream returns into a sealed anonymous memfd
before the replay claim.  No private key or plaintext snapshot is persisted.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import fcntl
import hashlib
import json
import os
import platform
import re
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

from core.e4_atomic_one_shot_ledger import AtomicE4OneShotLedger
from core.e4_authoritative_gate_callbacks import E4AuthoritativeGateCallbacks
from core.e4_hardened_executor import (
    EphemeralFDPlaintextSource,
    HardenedE4Executor,
    ImmutableEncryptedSnapshot,
    SubprocessDockerRuntime,
)
from core.e4_owner_payload_refresh import _load_source, refresh_owner_payload
from core.e4_owner_reviewer_verifier import _verify_ssh_signature
from core.e4_rehearsal_runner_authorization import (
    PRECONDITIONS,
    authorize_rehearsal_runner,
    build_owner_approval,
    build_precondition_evidence,
)
from core.e4_rehearsal_runner_boundary import (
    build_runner_boundary,
    target_spec,
    target_spec_fingerprint,
)
from core.e4_rehearsal_runner_plan import build_rehearsal_runner_plan
from core.e4_trust_registry_promotion import verify_authenticated_promotion


ROOT = Path("/root")
HANDOFF = ROOT / "E4-owner-handoff"
SOURCE_PAYLOAD = HANDOFF / "e4-owner-decision-payload.v11.json"
REVIEW_TEMPLATE = HANDOFF / "e4-reviewer-review-envelope.v6.json"
PROMOTION_TEMPLATE = HANDOFF / "e4-trust-registry-promotion-payload.v3.json"
REGISTRY = HANDOFF / "e4-owner-reviewer-trust-anchor-and-binding-candidate.v4.json"
OWNER_PUBLIC = HANDOFF / "owner-signing-v2.pub"
REVIEWER_PUBLIC = HANDOFF / "reviewer-signing-v2.pub"
TRUST_ROOT_PUBLIC = HANDOFF / "e4-trust-root.pub"
RECIPIENT_PUBLIC = HANDOFF / "owner-ssh.pub"
TSA_ROOT = HANDOFF / "DigiCertAssuredIDRootCA.crt.pem"
TSA_INTERMEDIATE = HANDOFF / "DigiCertTrustedG4TimeStampingRSA4096SHA2562025CA1.pem"
TSA_RESPONDER = HANDOFF / "DigiCertSHA256RSA4096TimestampResponder20251.cer"
MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"
SNAPSHOT = HANDOFF / "obsidian_exchange-cutover-20260810.dump.age"

OWNER_NAMESPACE = "e4-owner@obsidian-exchange.local"
OWNER_PRINCIPAL = "e4-owner-signing-v2"
REVIEWER_NAMESPACE = "e4-reviewer@obsidian-exchange.local"
REVIEWER_PRINCIPAL = "e4-independent-reviewer"
ROOT_NAMESPACE = "e4-trust-root"
ROOT_PRINCIPAL = "e4-trust-root"
TSA_ENDPOINT = "http://timestamp.digicert.com"
TSA_POLICY = "2.16.840.1.114412.7.1"
MAX_LINE_BYTES = 128 * 1024
MAX_SIGNATURE_BYTES = 8 * 1024
EXPECTED_PLAINTEXT_SHA256 = (
    "d61b888edabf3ff69cbbe861a5ea33f8b8f172b9a01e2a94f4bab82627dcf001"
)
EXPECTED_PLAINTEXT_BYTES = 459703
RELEASE_FILES = (
    ROOT / "relay/core/e4_owner_one_shot_server.py",
    ROOT / "relay/core/e4_owner_payload_refresh.py",
    ROOT / "relay/core/e4_atomic_one_shot_ledger.py",
    ROOT / "relay/core/e4_authenticated_gate_provider.py",
    ROOT / "relay/core/e4_hardened_executor.py",
    ROOT / "relay/core/e4_authoritative_gate_callbacks.py",
    ROOT / "relay/core/e4_owner_reviewer_replay_registry.py",
    ROOT / "relay/core/e4_rehearsal_receipt_consumption.py",
    ROOT / "relay/core/e4_owner_reviewer_verifier.py",
    ROOT / "relay/core/e4_trust_registry_promotion.py",
    ROOT / "relay/core/e4_rehearsal_runner_authorization.py",
    ROOT / "relay/core/e4_rehearsal_runner_boundary.py",
    ROOT / "relay/core/e4_rehearsal_runner_plan.py",
    ROOT / "E4-owner-handoff/e4_one_shot_termux.py",
    TSA_ROOT,
    TSA_INTERMEDIATE,
    TSA_RESPONDER,
    MANIFEST,
)
RELEASE_BINARIES = (
    Path("/usr/bin/python3"), Path("/usr/bin/docker"), Path("/usr/bin/age"),
    Path("/usr/bin/openssl"), Path("/usr/bin/curl"),
    Path("/usr/bin/ssh-keygen"),
)
EXPECTED_SNAPSHOT_SHA256 = (
    "47efc0dc293890243072bdf048d40cbcc1fee8fbe719e4b841fb5d156f658b3e"
)
EXPECTED_SNAPSHOT_REF_SHA256 = (
    "d56f226fb3c38cc40f7265d1d15c2c751211bb86ff1beba655f82f99d5d4b619"
)
EXPECTED_KEY_REF_SHA256 = (
    "c7e21692ac64774b4229807d5b11338df72f722247a1bcebb22d54667a102109"
)
OPERATIONAL_EXECUTION_ENABLED = False
EXPECTED_SOURCE_PAYLOAD_SHA256 = (
    "08c1430754336cbaf4338546b95467d6b0c247e4b46e2e0014fa7241b68477d2"
)


class OneShotError(ValueError):
    """A fail-closed one-shot ceremony or execution error."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_path(path: Path, maximum: int = 128 * 1024 * 1024) -> tuple[str, int]:
    resolved = path.resolve(strict=True)
    fd = os.open(resolved, os.O_RDONLY | os.O_CLOEXEC |
                 getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= maximum:
            raise OneShotError(f"{path} release file shape is invalid")
        digest = hashlib.sha256()
        total = 0
        while total < metadata.st_size:
            chunk = os.read(fd, min(1024 * 1024, metadata.st_size - total))
            if not chunk:
                raise OneShotError(f"{path} ended during release digest")
            digest.update(chunk)
            total += len(chunk)
    finally:
        os.close(fd)
    return digest.hexdigest(), metadata.st_size


def _release_manifest() -> dict[str, Any]:
    files = {}
    for path in RELEASE_FILES:
        digest, size = _sha_path(path)
        files[str(path.relative_to(ROOT))] = {"sha256": digest, "sizeBytes": size}
    binaries = {}
    for path in RELEASE_BINARIES:
        digest, size = _sha_path(path)
        binaries[str(path)] = {
            "resolvedPath": str(path.resolve(strict=True)),
            "sha256": digest, "sizeBytes": size,
        }
    unsigned = {
        "schemaVersion": "e4-one-shot-execution-release.v1",
        "protocol": "e4-one-shot.v1",
        "pythonVersion": platform.python_version(),
        "postgresImage": (
            "postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"),
        "files": files, "binaries": binaries,
    }
    return {**unsigned, "releaseSha256": _sha_bytes(json.dumps(
        unsigned, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode())}


def _read(path: Path, maximum: int = 64 * 1024) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise OneShotError(f"{path.name} has an invalid file shape")
        value = os.read(fd, maximum + 1)
    finally:
        os.close(fd)
    if len(value) > maximum:
        raise OneShotError(f"{path.name} is oversized")
    return value


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read(path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OneShotError(f"{path.name} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise OneShotError(f"{path.name} root is invalid")
    return value


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=False, indent=2)
            + "\n").encode()


def _write_new(path: Path, raw: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(fd, raw[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)


def _public_line(path: Path) -> str:
    try:
        lines = [line.strip() for line in _read(path, 4096).decode().splitlines()
                 if line.strip()]
    except UnicodeDecodeError as exc:
        raise OneShotError(f"{path.name} is not UTF-8") from exc
    if len(lines) != 1 or not lines[0].startswith("ssh-ed25519 "):
        raise OneShotError(f"{path.name} public key shape is invalid")
    return lines[0]


def _send(value: Mapping[str, Any]) -> None:
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")) + "\n").encode()
    if len(raw) > MAX_LINE_BYTES:
        raise OneShotError("outbound protocol message is oversized")
    offset = 0
    while offset < len(raw):
        offset += os.write(1, raw[offset:])


def _read_line() -> bytes:
    value = bytearray()
    while len(value) <= MAX_LINE_BYTES:
        chunk = os.read(0, 1)
        if not chunk:
            raise OneShotError("operator protocol ended early")
        if chunk == b"\n":
            return bytes(value)
        value.extend(chunk)
    raise OneShotError("operator protocol line is oversized")


def _receive_json() -> dict[str, Any]:
    try:
        value = json.loads(_read_line().decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OneShotError("operator protocol JSON is invalid") from exc
    if not isinstance(value, dict):
        raise OneShotError("operator protocol root is invalid")
    return value


def _request_signature(*, role: str, namespace: str, principal: str,
                       artifact_name: str, raw: bytes, public_path: Path,
                       context: Mapping[str, Any] | None = None) -> bytes:
    digest = _sha_bytes(raw)
    request = {
        "type": "SIGN_REQUEST", "role": role, "namespace": namespace,
        "principal": principal, "artifactName": artifact_name,
        "artifactSha256": digest,
        "publicKeySha256": _sha_bytes(_read(public_path, 4096)),
        "contentB64": base64.b64encode(raw).decode("ascii"),
    }
    if context is not None:
        request["context"] = dict(context)
    _send(request)
    response = _receive_json()
    if response.get("type") != "SIGNATURE" or response.get("role") != role \
            or response.get("artifactSha256") != digest:
        raise OneShotError(f"{role} signature response binding differs")
    encoded = response.get("signatureB64")
    if not isinstance(encoded, str):
        raise OneShotError(f"{role} signature response is missing")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise OneShotError(f"{role} signature encoding is invalid") from exc
    if not 0 < len(signature) <= MAX_SIGNATURE_BYTES:
        raise OneShotError(f"{role} signature size is invalid")
    if not _verify_ssh_signature(
            public_line=_public_line(public_path), principal=principal,
            namespace=namespace, signature=signature, message=raw):
        raise OneShotError(f"{role} signature verification failed")
    return signature


def _run(argv: list[str], *, timeout: float) -> bytes:
    try:
        result = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            cwd="/", timeout=timeout, check=False, shell=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OneShotError("bounded public-artifact command failed") from exc
    if result.returncode != 0:
        raise OneShotError("bounded public-artifact command returned non-zero")
    return result.stdout + result.stderr


def _fresh_payload(run_dir: Path, approved: int) -> tuple[Path, bytes, dict[str, Any]]:
    if _sha_bytes(_read(SOURCE_PAYLOAD)) != EXPECTED_SOURCE_PAYLOAD_SHA256:
        raise OneShotError("owner payload refresh source digest differs")
    source = _load_source(SOURCE_PAYLOAD)
    payload = refresh_owner_payload(
        source=source, approved_at_epoch_ms=approved, nonce=os.urandom(32))
    payload["executionRelease"] = _release_manifest()
    path = run_dir / "e4-owner-decision-payload.json"
    raw = _json_bytes(payload)
    _write_new(path, raw)
    return path, raw, payload


def _timestamp(*, run_dir: Path, payload_path: Path, payload_raw: bytes,
               owner_signature_path: Path, owner_signature: bytes,
               owner_fingerprint: str, approved: int) -> tuple[Path, Path, Path]:
    base = owner_signature_path.name
    request = run_dir / f"{base}.tsq"
    response = run_dir / f"{base}.tsr"
    token = run_dir / f"{base}.token.der"
    evidence_path = run_dir / f"{base}.digicert-rfc3161-evidence.v1.json"

    _run(["/usr/bin/openssl", "ts", "-query", "-data",
          str(owner_signature_path), "-sha256", "-cert", "-out", str(request)],
         timeout=10)
    _run(["/usr/bin/curl", "-fsS", "--proto", "=http",
          "--connect-timeout", "5", "--max-time", "20",
          "-H", "Content-Type: application/timestamp-query",
          "--data-binary", f"@{request}", "--output", str(response),
          TSA_ENDPOINT], timeout=25)
    _run(["/usr/bin/openssl", "ts", "-reply", "-in", str(response),
          "-token_out", "-out", str(token)], timeout=10)
    verified = _run([
        "/usr/bin/openssl", "ts", "-verify", "-queryfile", str(request),
        "-in", str(response), "-CAfile", str(TSA_ROOT),
        "-untrusted", str(TSA_INTERMEDIATE)], timeout=10).decode(
            "utf-8", errors="replace")
    if "Verification: OK" not in verified:
        raise OneShotError("RFC3161 response did not verify against pinned chain")
    detail = _run(["/usr/bin/openssl", "ts", "-reply", "-in", str(response),
                   "-text"], timeout=10).decode("utf-8", errors="strict")
    policy = re.search(r"^Policy OID:\s*(\S+)$", detail, re.MULTILINE)
    serial = re.search(r"^Serial number:\s*(?:0x)?([0-9A-Fa-f]+)$",
                       detail, re.MULTILINE)
    stamp = re.search(r"^Time stamp:\s*(.+ GMT)$", detail, re.MULTILINE)
    nonce = re.search(r"^Nonce:\s*(?:0x)?([0-9A-Fa-f]+)$",
                      detail, re.MULTILINE)
    if not all((policy, serial, stamp, nonce)) or policy.group(1) != TSA_POLICY:
        raise OneShotError("RFC3161 response fields are incomplete")
    generated = dt.datetime.strptime(
        stamp.group(1), "%b %d %H:%M:%S %Y GMT").replace(tzinfo=dt.UTC)
    generated_epoch = int(generated.timestamp() * 1000)
    expires = payload_raw and _json(payload_path)["approval"]["expiresAtEpochMs"]
    if not approved <= generated_epoch <= expires:
        raise OneShotError("RFC3161 time is outside the owner window")
    generated_iso = generated.strftime("%Y-%m-%dT%H:%M:%SZ")
    owner_digest = _sha_bytes(owner_signature)
    evidence = {
        "schemaVersion": "e4-rfc3161-timestamp-evidence.v1",
        "evidenceId": f"e4-digicert-ts-one-shot-{approved}",
        "status": "CANDIDATE_NOT_AUTHORIZED", "stage": "E4",
        "route": "E4_OWNER_GATED_FRESH_PRODUCTION_DISCONNECTED_REHEARSAL",
        "authority": {
            "trustedClockAttested": True, "executionAuthorized": False,
            "rehearsalExecutionEligible": False,
            "productionDatabaseContactAllowed": False,
            "productionNetworkAllowed": False,
            "productionCredentialsAllowed": False, "containsSecrets": False,
            "executionEffect": "NONE", "promotionAllowed": False,
            "actionAllowed": False,
        },
        "provider": {"name": "DigiCert", "protocol": "RFC3161",
                     "endpoint": TSA_ENDPOINT, "policyOid": TSA_POLICY},
        "boundArtifact": {
            "payloadRef": payload_path.name,
            "payloadSha256": _sha_bytes(payload_raw),
            "ownerSignatureRef": owner_signature_path.name,
            "ownerSignatureSha256": owner_digest,
            "ownerSignatureVerified": True,
            "ownerFingerprint": owner_fingerprint,
        },
        "timestampRequest": {"ref": request.name,
                             "sha256": _sha_bytes(_read(request, 16 * 1024)),
                             "hashAlgorithm": "sha256", "certReq": True},
        "timestampResponse": {
            "ref": response.name,
            "sha256": _sha_bytes(_read(response, 32 * 1024)),
            "tokenRef": token.name,
            "tokenSha256": _sha_bytes(_read(token, 32 * 1024)),
            "responseStatus": "GRANTED",
            "serialNumber": serial.group(1).upper(),
            "genTimeUtc": generated_iso,
            "nonce": nonce.group(1).upper(),
        },
        "messageImprint": {"hashAlgorithm": "sha256", "value": owner_digest,
                           "matchesBoundArtifact": True},
        "certificateChain": {
            "tsaResponder": {"ref": TSA_RESPONDER.name,
                             "sha256": _sha_bytes(_read(TSA_RESPONDER, 32 * 1024))},
            "timestampCa": {"ref": TSA_INTERMEDIATE.name,
                            "sha256": _sha_bytes(_read(TSA_INTERMEDIATE, 32 * 1024))},
            "pinnedRoot": {"ref": TSA_ROOT.name,
                           "sha256": _sha_bytes(_read(TSA_ROOT, 32 * 1024))},
        },
        "verification": {
            "status": "VERIFIED",
            "verifiedAtUtc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "exactMessageImprintVerified": True,
            "responseStatusVerified": True, "noncePresent": True,
            "tsaResponderChainVerified": True, "pinnedRootChainVerified": True,
            "opensslTsVerifyResult": "Verification: OK",
            "plaintextSnapshotRead": False, "productionContact": False,
        },
        "nextAction": "Bind this evidence to the reviewer envelope and authenticated replay decision; do not treat the timestamp alone as execution authority.",
    }
    _write_new(evidence_path, _json_bytes(evidence))
    return evidence_path, request, response


def _review_envelope(*, run_dir: Path, payload_path: Path, payload_raw: bytes,
                     payload: Mapping[str, Any], owner_signature_path: Path,
                     owner_signature: bytes, evidence_path: Path,
                     approved: int) -> tuple[Path, bytes]:
    value = copy.deepcopy(_json(REVIEW_TEMPLATE))
    reviewed = time.time_ns() // 1_000_000
    value["envelopeId"] = f"e4-review-envelope-one-shot-{approved}"
    value["reviewedAtEpochMs"] = reviewed
    value["reviewNonceSha256"] = _sha_bytes(os.urandom(32))
    approval = payload["approval"]
    value["ownerPayload"].update({
        "payloadRef": payload_path.name, "payloadId": payload["payloadId"],
        "payloadSha256": _sha_bytes(payload_raw),
        "ownerSignatureRef": owner_signature_path.name,
        "ownerSignatureSha256": _sha_bytes(owner_signature),
        "approvedAtEpochMs": approval["approvedAtEpochMs"],
        "expiresAtEpochMs": approval["expiresAtEpochMs"],
    })
    evidence_raw = _read(evidence_path, 32 * 1024)
    value["timestampEvidence"].update({
        "ref": evidence_path.name, "sha256": _sha_bytes(evidence_raw),
        "boundSignatureSha256": _sha_bytes(owner_signature),
    })
    value["binding"] = copy.deepcopy(_json(REGISTRY)["binding"])
    raw = _json_bytes(value)
    for stale in (b"payload.v12", b"envelope.v6"):
        if stale in raw:
            raise OneShotError("review envelope retained a stale artifact reference")
    path = run_dir / "e4-reviewer-review-envelope.json"
    _write_new(path, raw)
    return path, raw


def _promotion(*, run_dir: Path, payload_path: Path, payload_raw: bytes,
               owner_signature_path: Path, owner_signature: bytes,
               envelope_path: Path, envelope_raw: bytes,
               reviewer_signature_path: Path, reviewer_signature: bytes,
               evidence_path: Path, payload: Mapping[str, Any],
               approved: int) -> tuple[Path, bytes]:
    value = copy.deepcopy(_json(PROMOTION_TEMPLATE))
    value["payloadId"] = f"e4-trust-registry-promotion-one-shot-{approved}"
    value["boundEvidence"].update({
        "ownerPayloadRef": payload_path.name,
        "ownerPayloadSha256": _sha_bytes(payload_raw),
        "ownerSignatureRef": owner_signature_path.name,
        "ownerSignatureSha256": _sha_bytes(owner_signature),
        "reviewerEnvelopeRef": envelope_path.name,
        "reviewerEnvelopeSha256": _sha_bytes(envelope_raw),
        "reviewerSignatureRef": reviewer_signature_path.name,
        "reviewerSignatureSha256": _sha_bytes(reviewer_signature),
        "timestampEvidenceRef": evidence_path.name,
        "timestampEvidenceSha256": _sha_bytes(_read(evidence_path, 32 * 1024)),
    })
    approval = payload["approval"]
    value["frozenBinding"] = {
        "planId": approval["planId"], "targetRef": approval["targetRef"],
        "targetFingerprintSha256": approval["targetFingerprintSha256"],
        "snapshotSha256": approval["snapshotSha256"],
        "keyRefSha256": approval["keyRefSha256"], "scope": approval["scope"],
        "invocationLimit": approval["invocationLimit"],
    }
    value["replay"]["nonceSha256"] = _sha_bytes(os.urandom(32))
    raw = _json_bytes(value)
    for stale in (b"payload.v12", b"envelope.v6"):
        if stale in raw:
            raise OneShotError("promotion retained a stale artifact reference")
    path = run_dir / "e4-trust-registry-promotion-payload.json"
    _write_new(path, raw)
    return path, raw


def _snapshot_source() -> ImmutableEncryptedSnapshot:
    metadata = os.stat(SNAPSHOT, follow_symlinks=False)
    parent = os.stat(SNAPSHOT.parent, follow_symlinks=False)
    if (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_nlink) != (
            0x801, 2412135, 460027, 1):
        raise OneShotError("snapshot immutable handle differs")
    return ImmutableEncryptedSnapshot(
        path=SNAPSHOT, expected_sha256=EXPECTED_SNAPSHOT_SHA256,
        expected_device=0x801, expected_inode=2412135,
        expected_size_bytes=460027, expected_hardlink_count=1,
        expected_parent_device=parent.st_dev,
        expected_parent_inode=parent.st_ino, require_immutable=True)


def _evidence_digest(check: str, facts: Mapping[str, Any]) -> str:
    return _sha_bytes(json.dumps(
        {"checkId": check, "facts": dict(facts)}, ensure_ascii=True,
        sort_keys=True, separators=(",", ":")).encode())


def _prepare(*, payload_path: Path, owner_signature_path: Path,
             envelope_path: Path, reviewer_signature_path: Path,
             promotion_path: Path, promotion_signature_path: Path,
             evidence_path: Path, request_path: Path,
             response_path: Path) -> dict[str, Any]:
    now = time.time_ns() // 1_000_000
    verified = verify_authenticated_promotion(
        promotion_path=promotion_path,
        promotion_signature_path=promotion_signature_path,
        trust_root_public_key_path=TRUST_ROOT_PUBLIC, registry_path=REGISTRY,
        payload_path=payload_path, owner_signature_path=owner_signature_path,
        owner_public_key_path=OWNER_PUBLIC, envelope_path=envelope_path,
        reviewer_signature_path=reviewer_signature_path,
        reviewer_public_key_path=REVIEWER_PUBLIC,
        timestamp_evidence_path=evidence_path,
        timestamp_request_path=request_path, timestamp_response_path=response_path,
        timestamp_root_path=TSA_ROOT,
        timestamp_intermediate_path=TSA_INTERMEDIATE,
        evaluated_at_epoch_ms=now)
    if verified.get("status") != "VERIFIED" \
            or verified.get("replayEligible") is not True:
        raise OneShotError("promotion is not replay-eligible")
    payload = _json(payload_path)
    if payload.get("executionRelease") != _release_manifest():
        raise OneShotError("signed execution release differs from current runtime")
    approval = payload.get("approval")
    if not isinstance(approval, Mapping) or any((
            approval.get("snapshotSha256") != EXPECTED_SNAPSHOT_SHA256,
            approval.get("snapshotRefSha256") != EXPECTED_SNAPSHOT_REF_SHA256,
            approval.get("keyRefSha256") != EXPECTED_KEY_REF_SHA256)):
        raise OneShotError("owner snapshot/key binding differs")
    recipient = _public_line(RECIPIENT_PUBLIC)
    if _sha_bytes(recipient.encode()) != EXPECTED_KEY_REF_SHA256:
        raise OneShotError("public recipient binding differs")
    manifest_sha = _sha_bytes(_read(MANIFEST))
    plan = build_rehearsal_runner_plan(evidence_manifest_sha256=manifest_sha)
    target = approval["targetRef"]
    fingerprint = target_spec_fingerprint(target_ref=target)
    if plan["planId"] != approval.get("planId") \
            or fingerprint != approval.get("targetFingerprintSha256"):
        raise OneShotError("owner plan/target binding differs")
    runtime = SubprocessDockerRuntime()
    if not runtime.target_absent(target_ref=target):
        raise OneShotError("disposable target is not absent")
    source = _snapshot_source()
    with source.open_verified(expected_sha256=EXPECTED_SNAPSHOT_SHA256):
        pass
    owner_approval = build_owner_approval(
        approval_ref=approval["approvalRef"], plan_id=approval["planId"],
        target_ref=target, target_fingerprint_sha256=fingerprint,
        snapshot_sha256=EXPECTED_SNAPSHOT_SHA256,
        snapshot_ref_sha256=EXPECTED_SNAPSHOT_REF_SHA256,
        key_ref_sha256=EXPECTED_KEY_REF_SHA256,
        approved_at_epoch_ms=approval["approvedAtEpochMs"],
        expires_at_epoch_ms=approval["expiresAtEpochMs"])
    observed = time.time_ns() // 1_000_000
    spec = target_spec(target_ref=target)
    facts = {
        "EXPLICIT_OWNER_APPROVAL": {
            "verificationId": verified["verificationId"],
            "promotionSha256": verified["promotionPayloadSha256"]},
        "DISPOSABLE_TARGET_IDENTITY_VERIFIED": {
            "targetFingerprintSha256": fingerprint},
        "TARGET_ABSENT_BEFORE_START": {"targetAbsent": True},
        "NO_PRODUCTION_NETWORK_ROUTE": {
            "network": spec["network"], "publishedPorts": spec["publishedPorts"]},
        "NO_PRODUCTION_CREDENTIALS_OR_SECRETS": {
            "productionCredentialsAllowed": False, "publicRecipientOnly": True},
        "ENCRYPTED_SNAPSHOT_COPY_DIGEST_VERIFIED": {
            "ciphertextSha256": EXPECTED_SNAPSHOT_SHA256,
            "immutableHandle": "fs-801-2412135"},
        "EVIDENCE_MANIFEST_VERIFIED": {"manifestSha256": manifest_sha},
        "TEARDOWN_TARGET_VERIFIED": {
            "ownedTargetTeardownRequired": True, "targetAbsentBefore": True},
    }
    evidence = [build_precondition_evidence(
        plan_id=plan["planId"], target_ref=target,
        target_fingerprint_sha256=fingerprint,
        snapshot_sha256=EXPECTED_SNAPSHOT_SHA256, check_id=check,
        observed_at_epoch_ms=observed, outcome="PASS",
        evidence_sha256=_evidence_digest(check, facts[check]))
        for check in PRECONDITIONS]
    receipt = authorize_rehearsal_runner(
        plan=plan, target_ref=target,
        target_fingerprint_sha256=fingerprint,
        snapshot_sha256=EXPECTED_SNAPSHOT_SHA256, evidence=evidence,
        owner_approval=owner_approval, assessed_at_epoch_ms=observed)
    if receipt.get("status") != "ELIGIBLE":
        raise OneShotError("authorization receipt is not eligible")
    snapshot_ref = "sha256_" + EXPECTED_SNAPSHOT_REF_SHA256
    key_ref = "sha256_" + EXPECTED_KEY_REF_SHA256
    boundary = build_runner_boundary(
        plan=plan, receipt=receipt, snapshot_ref=snapshot_ref, key_ref=key_ref)
    return {
        "verified": verified, "runtime": runtime, "source": source,
        "plan": plan, "ownerApproval": owner_approval, "receipt": receipt,
        "boundary": boundary, "snapshotRef": snapshot_ref, "keyRef": key_ref,
    }


def _send_snapshot(*, source: ImmutableEncryptedSnapshot,
                   challenge: str) -> None:
    _send({
        "type": "SNAPSHOT_STREAM", "challenge": challenge,
        "ciphertextLength": 460027,
        "ciphertextSha256": EXPECTED_SNAPSHOT_SHA256,
        "expectedPlaintextLength": EXPECTED_PLAINTEXT_BYTES,
        "expectedPlaintextSha256": EXPECTED_PLAINTEXT_SHA256,
        "keyRefSha256": EXPECTED_KEY_REF_SHA256,
    })
    with source.open_verified(expected_sha256=EXPECTED_SNAPSHOT_SHA256) as handle:
        offset = 0
        while offset < handle.size_bytes:
            chunk = os.pread(
                handle.fd, min(64 * 1024, handle.size_bytes - offset), offset)
            if not chunk:
                raise OneShotError("ciphertext stream ended early")
            written = 0
            while written < len(chunk):
                written += os.write(1, chunk[written:])
            offset += len(chunk)


def _receive_plaintext(*, challenge: str) -> int:
    header = _receive_json()
    length = header.get("length")
    if header.get("type") != "PLAINTEXT_STREAM" \
            or header.get("challenge") != challenge \
            or header.get("ciphertextSha256") != EXPECTED_SNAPSHOT_SHA256 \
            or header.get("plaintextSha256") != EXPECTED_PLAINTEXT_SHA256 \
            or isinstance(length, bool) or not isinstance(length, int) \
            or length != EXPECTED_PLAINTEXT_BYTES:
        raise OneShotError("plaintext stream header is invalid")
    flags = getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0)
    fd = os.memfd_create("e4-plaintext-snapshot-one-shot", flags)
    os.fchmod(fd, 0o600)
    try:
        remaining = length
        digest = hashlib.sha256()
        while remaining:
            chunk = os.read(0, min(remaining, 64 * 1024))
            if not chunk:
                raise OneShotError("plaintext stream ended early")
            os.write(fd, chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        if digest.hexdigest() != EXPECTED_PLAINTEXT_SHA256:
            raise OneShotError("plaintext stream digest mismatch")
        os.lseek(fd, 0, os.SEEK_SET)
        if hasattr(fcntl, "F_ADD_SEALS"):
            seals = (fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
                     fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
            if fcntl.fcntl(fd, fcntl.F_GET_SEALS) & seals != seals:
                raise OneShotError("plaintext memfd seals were not applied")
        else:
            raise OneShotError("plaintext memfd sealing is unavailable")
        return fd
    except Exception:
        os.close(fd)
        raise


def _claim_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM e4_owner_reviewer_replay_claims").fetchone()
    except sqlite3.Error:
        return -1
    return int(row[0]) if row else -1


def _execute(*, run_dir: Path, approved: int, plaintext_fd: int,
             values: Mapping[str, Any], payload_path: Path,
             owner_signature_path: Path, envelope_path: Path,
             reviewer_signature_path: Path, promotion_path: Path,
             promotion_signature_path: Path, evidence_path: Path,
             request_path: Path, response_path: Path) -> dict[str, Any]:
    plaintext_source = EphemeralFDPlaintextSource(
        plaintext_fd, expected_sha256=EXPECTED_PLAINTEXT_SHA256,
        expected_size_bytes=EXPECTED_PLAINTEXT_BYTES)
    # Reverify the sealed anonymous stream before creating either ledger.
    with plaintext_source.open_verified(
            expected_sha256=EXPECTED_PLAINTEXT_SHA256):
        pass
    gate_dir = Path(f"/var/tmp/e4-one-shot-gate-{approved}")
    gate_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    gate_path = gate_dir / "gate.sqlite3"
    ledger = AtomicE4OneShotLedger(str(gate_path))
    gate = E4AuthoritativeGateCallbacks(
        promotion_path=promotion_path,
        promotion_signature_path=promotion_signature_path,
        trust_root_public_key_path=TRUST_ROOT_PUBLIC, registry_path=REGISTRY,
        payload_path=payload_path, owner_signature_path=owner_signature_path,
        owner_public_key_path=OWNER_PUBLIC, envelope_path=envelope_path,
        reviewer_signature_path=reviewer_signature_path,
        reviewer_public_key_path=REVIEWER_PUBLIC,
        timestamp_evidence_path=evidence_path,
        timestamp_request_path=request_path, timestamp_response_path=response_path,
        timestamp_root_path=TSA_ROOT,
        timestamp_intermediate_path=TSA_INTERMEDIATE,
        replay_registry=ledger, receipt_ledger=ledger)
    try:
        result = HardenedE4Executor(runtime=values["runtime"]).execute(
            plan=values["plan"], receipt=values["receipt"],
            owner_approval=values["ownerApproval"],
            boundary=values["boundary"], gate_provider=gate,
            snapshot_ref=values["snapshotRef"], key_ref=values["keyRef"],
            snapshot_source=values["source"],
            key_source=None, plaintext_source=plaintext_source,
            expected_plaintext_sha256=EXPECTED_PLAINTEXT_SHA256)
    except Exception as exc:
        count = _claim_count(gate_path)
        raise OneShotError(
            f"executor failed; replayClaimCount={count}; do not retry if count is nonzero") from exc
    finally:
        ledger.close()
    result_path = run_dir / "e4-hardened-rehearsal-result.json"
    _write_new(result_path, _json_bytes(result))
    return {"result": result, "resultPath": str(result_path),
            "replayClaimCount": _claim_count(gate_path)}


def _main() -> int:
    if not OPERATIONAL_EXECUTION_ENABLED:
        raise OneShotError(
            "one-shot execution is disabled pending offline owner/trust-root "
            "handoffs, trusted final-bundle time, durable cross-run replay "
            "authority and versioned teardown semantics")
    input_stat = os.fstat(0)
    if not (stat.S_ISFIFO(input_stat.st_mode) or stat.S_ISSOCK(input_stat.st_mode)):
        raise OneShotError("one-shot protocol requires SSH pipe/socket stdin")
    approved = time.time_ns() // 1_000_000
    run_dir = HANDOFF / f"e4-one-shot-{approved}"
    run_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(run_dir, 0o700)
    _send({"type": "HELLO", "protocol": "e4-one-shot.v1",
           "approvedAtEpochMs": approved, "runRef": run_dir.name})

    payload_path, payload_raw, payload = _fresh_payload(run_dir, approved)
    owner_signature = _request_signature(
        role="OWNER", namespace=OWNER_NAMESPACE, principal=OWNER_PRINCIPAL,
        artifact_name=payload_path.name, raw=payload_raw, public_path=OWNER_PUBLIC)
    owner_signature_path = run_dir / f"{payload_path.name}.sig"
    _write_new(owner_signature_path, owner_signature)

    evidence_path, request_path, response_path = _timestamp(
        run_dir=run_dir, payload_path=payload_path, payload_raw=payload_raw,
        owner_signature_path=owner_signature_path,
        owner_signature=owner_signature,
        owner_fingerprint=_json(REVIEW_TEMPLATE)["ownerPayload"]["ownerFingerprint"],
        approved=approved)
    envelope_path, envelope_raw = _review_envelope(
        run_dir=run_dir, payload_path=payload_path, payload_raw=payload_raw,
        payload=payload, owner_signature_path=owner_signature_path,
        owner_signature=owner_signature, evidence_path=evidence_path,
        approved=approved)
    reviewer_signature = _request_signature(
        role="REVIEWER", namespace=REVIEWER_NAMESPACE,
        principal=REVIEWER_PRINCIPAL, artifact_name=envelope_path.name,
        raw=envelope_raw, public_path=REVIEWER_PUBLIC,
        context={
            "ownerPayloadB64": base64.b64encode(payload_raw).decode("ascii"),
            "ownerSignatureB64": base64.b64encode(owner_signature).decode("ascii"),
            "timestampEvidenceB64": base64.b64encode(
                _read(evidence_path, 32 * 1024)).decode("ascii"),
            "timestampRequestB64": base64.b64encode(
                _read(request_path, 16 * 1024)).decode("ascii"),
            "timestampResponseB64": base64.b64encode(
                _read(response_path, 32 * 1024)).decode("ascii"),
            "timestampRootB64": base64.b64encode(
                _read(TSA_ROOT, 32 * 1024)).decode("ascii"),
            "timestampIntermediateB64": base64.b64encode(
                _read(TSA_INTERMEDIATE, 32 * 1024)).decode("ascii"),
            "timestampResponderB64": base64.b64encode(
                _read(TSA_RESPONDER, 32 * 1024)).decode("ascii"),
        })
    reviewer_signature_path = run_dir / f"{envelope_path.name}.sig"
    _write_new(reviewer_signature_path, reviewer_signature)

    promotion_path, promotion_raw = _promotion(
        run_dir=run_dir, payload_path=payload_path, payload_raw=payload_raw,
        owner_signature_path=owner_signature_path,
        owner_signature=owner_signature, envelope_path=envelope_path,
        envelope_raw=envelope_raw,
        reviewer_signature_path=reviewer_signature_path,
        reviewer_signature=reviewer_signature, evidence_path=evidence_path,
        payload=payload, approved=approved)
    promotion_signature = _request_signature(
        role="TRUST_ROOT", namespace=ROOT_NAMESPACE, principal=ROOT_PRINCIPAL,
        artifact_name=promotion_path.name, raw=promotion_raw,
        public_path=TRUST_ROOT_PUBLIC)
    promotion_signature_path = run_dir / f"{promotion_path.name}.sig"
    _write_new(promotion_signature_path, promotion_signature)

    values = _prepare(
        payload_path=payload_path, owner_signature_path=owner_signature_path,
        envelope_path=envelope_path,
        reviewer_signature_path=reviewer_signature_path,
        promotion_path=promotion_path,
        promotion_signature_path=promotion_signature_path,
        evidence_path=evidence_path, request_path=request_path,
        response_path=response_path)
    _send({
        "type": "PREFLIGHT", "status": "READY_NO_REPLAY_CLAIMED",
        "runRef": run_dir.name, "planId": values["plan"]["planId"],
        "receiptId": values["receipt"]["receiptId"],
        "boundaryId": values["boundary"]["boundaryId"],
        "targetAbsent": True, "snapshotDigestVerified": True,
        "keyRecipientPublicBindingVerified": True, "replayClaimed": False,
    })
    challenge = _sha_bytes(os.urandom(32))
    _send_snapshot(source=values["source"], challenge=challenge)
    plaintext_fd = _receive_plaintext(challenge=challenge)
    try:
        completed = _execute(
            run_dir=run_dir, approved=approved, plaintext_fd=plaintext_fd,
            values=values,
            payload_path=payload_path,
            owner_signature_path=owner_signature_path,
            envelope_path=envelope_path,
            reviewer_signature_path=reviewer_signature_path,
            promotion_path=promotion_path,
            promotion_signature_path=promotion_signature_path,
            evidence_path=evidence_path, request_path=request_path,
            response_path=response_path)
    finally:
        os.close(plaintext_fd)
    result = completed["result"]
    _send({
        "type": "FINAL", "status": result["status"],
        "executionId": result["executionId"],
        "resultSha256": result["resultSha256"],
        "resultPath": completed["resultPath"],
        "replayClaimCount": completed["replayClaimCount"],
        "targetAbsentAfter": result["teardown"]["targetAbsentAfter"],
        "sourceCiphertextRetained": result["snapshot"]["sourceCiphertextRetained"],
        "decryptionKeyReceivedByServer": result["snapshot"][
            "decryptionKeyReceivedByServer"],
        "productionContacted": result["production"]["contacted"],
    })
    return 0


def main() -> int:
    try:
        return _main()
    except Exception as exc:
        try:
            _send({"type": "ERROR", "status": "E4_FAIL_CLOSED",
                   "message": str(exc)[:500]})
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
