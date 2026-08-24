"""Run the split-role E4 signing ceremony and rehearsal from Termux.

The owner and trust-root keys plus the encrypted snapshot identity stay on the
owner device.  The reviewer request must be transferred to a genuinely
independent device; the owner device refuses a co-resident reviewer private key.
Public artifacts travel over one host-key-checked SSH connection.  After a
no-replay preflight, the ciphertext is decrypted locally by age; only the exact
plaintext dump is returned as a bounded stream and is never persisted.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


HOME = Path.home()
KEY_DIR = HOME / "e4-key"
REMOTE = "root@185.236.228.19"
REMOTE_COMMAND = (
    "PYTHONPATH=/root/relay /usr/bin/python3 "
    "-m core.e4_owner_one_shot_server"
)
MAX_LINE_BYTES = 128 * 1024
MAX_KEY_BYTES = 16 * 1024
AUTHORIZATION_MS = 15 * 60 * 1000
OPERATIONAL_EXECUTION_ENABLED = False
TSA_POLICY = "2.16.840.1.114412.7.1"
EXPECTED_TSA_SHA256 = {
    "root": "b52fae9cd8dcf49285f0337cd815deca13fedd31f653bf07f61579451517e18c",
    "intermediate": "5e13de210e735b614d6ec948361aadef9dd6c0ef575382a75f57fd59e183b90e",
    "responder": "4aa03fa22cd75c84c55c938f828e676b9caecab33fe36d269aa334f146110a33",
}
EXPECTED_TSA_FILES = {
    "E4-owner-handoff/DigiCertAssuredIDRootCA.crt.pem": {
        "sha256": EXPECTED_TSA_SHA256["root"], "sizeBytes": 1350},
    "E4-owner-handoff/DigiCertTrustedG4TimeStampingRSA4096SHA2562025CA1.pem": {
        "sha256": EXPECTED_TSA_SHA256["intermediate"], "sizeBytes": 2386},
    "E4-owner-handoff/DigiCertSHA256RSA4096TimestampResponder20251.cer": {
        "sha256": EXPECTED_TSA_SHA256["responder"], "sizeBytes": 1777},
}
EXPECTED_HOST_FINGERPRINT = (
    "SHA256:QY5T7dl5kDMu7rvqx+Ndz91oFawIzt5JaaF4EsSQupc"
)
EXPECTED_PUBLIC_SHA256 = {
    "OWNER": "8ee7fb9b018e485b1e3cb9c0f36bb94ede78848af4323470a43adbd0bef71d63",
    "REVIEWER": "79013979c27cae19fc304269fd390861cb7bdd561d2ca955b96eda8a9e29a095",
    "TRUST_ROOT": "5669b2922f49c3c661be658c969566ce256bf7874d3fd1790c31299a4c4519d0",
}
PRIVATE_KEYS = {
    "OWNER": KEY_DIR / "owner-signing-v2",
    "TRUST_ROOT": HOME / "e4-trust-root-signing",
}
REVIEWER_PRIVATE = KEY_DIR / "reviewer-signing-v2"
PUBLIC_KEYS = {
    "OWNER": KEY_DIR / "owner-signing-v2.pub",
    "REVIEWER": KEY_DIR / "reviewer-signing-v2.pub",
    "TRUST_ROOT": HOME / "e4-trust-root-signing.pub",
}
NAMESPACES = {
    "OWNER": "e4-owner@obsidian-exchange.local",
    "REVIEWER": "e4-reviewer@obsidian-exchange.local",
    "TRUST_ROOT": "e4-trust-root",
}
PRINCIPALS = {
    "OWNER": "e4-owner-signing-v2",
    "REVIEWER": "e4-independent-reviewer",
    "TRUST_ROOT": "e4-trust-root",
}
RECIPIENT_KEY = KEY_DIR / "owner-ssh"
RECIPIENT_PUBLIC = KEY_DIR / "owner-ssh.pub"
EXPECTED_KEY_REF_SHA256 = (
    "c7e21692ac64774b4229807d5b11338df72f722247a1bcebb22d54667a102109"
)
EXPECTED_BINDING = {
    "planId": "e4rrp_73040dd58161e760075b961004c173966291a8d33344f248cf6a43ec75893ffd",
    "planSourceSha256": "eb70458a03fdb5b744f44f0fd390e78f17a65226e2a48b2c763db3ff2623cc2c",
    "evidenceManifestSha256": "2489745da1fd584c3d77965ebc7b4776ddad3115bcbea5dc7a623fc3d2981a03",
    "stagedManifestSha256": "c9d94148fe163a284e8ad6df3640e4da9be1f2a090ea7d873e8a7d9bcab2594a",
    "targetRef": "e4-disposable-pg-20260822-02",
    "targetFingerprintSha256": "3545e043156cd9023d46a5ebaaa12f0c964ceea2887cea79c9703395a1588ad3",
    "snapshotRefSha256": "d56f226fb3c38cc40f7265d1d15c2c751211bb86ff1beba655f82f99d5d4b619",
    "snapshotSha256": "47efc0dc293890243072bdf048d40cbcc1fee8fbe719e4b841fb5d156f658b3e",
    "keyRefSha256": EXPECTED_KEY_REF_SHA256,
    "immutableHandle": "fs-801-2412135",
    "scope": "ONE_E4_ISOLATED_FULL_SNAPSHOT_REHEARSAL",
    "invocationLimit": 1,
}


class HandoffError(ValueError):
    """A fail-closed local handoff error."""


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read(path: Path, maximum: int = MAX_KEY_BYTES) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise HandoffError(f"{path.name} has an invalid file shape")
        raw = os.read(fd, maximum + 1)
    finally:
        os.close(fd)
    if len(raw) > maximum:
        raise HandoffError(f"{path.name} is oversized")
    return raw


def _json(raw: bytes, field: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise HandoffError(f"{field} contains a duplicate field")
            value[key] = item
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda item: (_ for _ in ()).throw(
                               HandoffError(f"{field} contains a non-finite value")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"{field} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise HandoffError(f"{field} root is invalid")
    return value


def _decode(value: Any, field: str, maximum: int = 64 * 1024) -> bytes:
    if not isinstance(value, str):
        raise HandoffError(f"{field} is missing")
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise HandoffError(f"{field} base64 is invalid") from exc
    if not 0 < len(raw) <= maximum:
        raise HandoffError(f"{field} size is invalid")
    return raw


def _public_line(path: Path) -> str:
    try:
        lines = [line.strip() for line in _read(path, 4096).decode().splitlines()
                 if line.strip()]
    except UnicodeDecodeError as exc:
        raise HandoffError(f"{path.name} is not UTF-8") from exc
    if len(lines) != 1 or not lines[0].startswith("ssh-ed25519 "):
        raise HandoffError(f"{path.name} public-key shape is invalid")
    return " ".join(lines[0].split()[:2])


def _private_key_shape(path: Path) -> None:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() \
            or metadata.st_mode & 0o077 or not 0 < metadata.st_size <= MAX_KEY_BYTES:
        raise HandoffError(f"{path.name} ownership or permissions are unsafe")


def _verify_known_host() -> None:
    known_hosts = HOME / ".ssh" / "known_hosts"
    result = subprocess.run([
        "ssh-keygen", "-F", "185.236.228.19", "-f", str(known_hosts)],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
    fingerprints: list[str] = []
    for raw_line in result.stdout.decode("utf-8", errors="strict").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3 or parts[-2] != "ssh-ed25519":
            continue
        try:
            blob = base64.b64decode(parts[-1], validate=True)
        except ValueError as exc:
            raise HandoffError("known_hosts ED25519 entry is malformed") from exc
        encoded = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
        fingerprints.append("SHA256:" + encoded)
    if not fingerprints or any(
            item != EXPECTED_HOST_FINGERPRINT for item in fingerprints):
        raise HandoffError("known_hosts server fingerprint differs")


def _authority_false(value: Mapping[str, Any], field: str) -> None:
    authority = value.get("authority")
    if not isinstance(authority, Mapping) \
            or any(item is not False for item in authority.values()
                   if isinstance(item, bool)) \
            or authority.get("executionEffect") != "NONE":
        raise HandoffError(f"{field} authority is not fail-closed")


def _validate_payload(raw: bytes) -> dict[str, Any]:
    value = _json(raw, "owner payload")
    _authority_false(value, "owner payload")
    approval = value.get("approval")
    frozen = value.get("frozenBinding")
    release = value.get("executionRelease")
    if value.get("schemaVersion") != "e4-owner-decision-payload.v1" \
            or value.get("status") != "READY_FOR_OFFLINE_OWNER_SIGNATURE" \
            or not isinstance(approval, Mapping) \
            or not isinstance(frozen, Mapping) \
            or not isinstance(release, Mapping):
        raise HandoffError("owner payload shape is invalid")
    release_files = release.get("files")
    helper = release_files.get(
        "E4-owner-handoff/e4_one_shot_termux.py") \
        if isinstance(release_files, Mapping) else None
    local_helper = _read(Path(__file__).absolute(), MAX_LINE_BYTES)
    if not isinstance(helper, Mapping) \
            or helper.get("sha256") != _sha(local_helper) \
            or helper.get("sizeBytes") != len(local_helper):
        raise HandoffError("signed release does not bind this Termux helper")
    if any(release_files.get(path) != expected
           for path, expected in EXPECTED_TSA_FILES.items()):
        raise HandoffError("signed release does not bind the pinned TSA chain")
    exact = {
        "planId": approval.get("planId"),
        "targetRef": approval.get("targetRef"),
        "targetFingerprintSha256": approval.get("targetFingerprintSha256"),
        "snapshotRefSha256": approval.get("snapshotRefSha256"),
        "snapshotSha256": approval.get("snapshotSha256"),
        "keyRefSha256": approval.get("keyRefSha256"),
        "scope": approval.get("scope"),
        "invocationLimit": approval.get("invocationLimit"),
    }
    for field, item in exact.items():
        if item != EXPECTED_BINDING[field]:
            raise HandoffError(f"owner payload {field} binding differs")
    for field in ("planSourceSha256", "evidenceManifestSha256",
                  "stagedManifestSha256"):
        if frozen.get(field) != EXPECTED_BINDING[field]:
            raise HandoffError(f"owner frozen {field} binding differs")
    approved = approval.get("approvedAtEpochMs")
    expires = approval.get("expiresAtEpochMs")
    if isinstance(approved, bool) or not isinstance(approved, int) \
            or isinstance(expires, bool) or not isinstance(expires, int) \
            or expires - approved != AUTHORIZATION_MS:
        raise HandoffError("owner approval window is not exactly 15 minutes")
    if approval.get("executionEffect") != "NONE" \
            or any(item is not False for item in approval.values()
                   if isinstance(item, bool)):
        raise HandoffError("owner approval grants unexpected authority")
    return value


def _verify_ssh(*, role: str, message: bytes, signature: bytes) -> None:
    public = _public_line(PUBLIC_KEYS[role])
    with tempfile.TemporaryDirectory(prefix="e4-public-verify-") as directory:
        root = Path(directory)
        allowed = root / "allowed"
        sig = root / "signature"
        allowed.write_text(PRINCIPALS[role] + " " + public + "\n",
                           encoding="utf-8")
        sig.write_bytes(signature)
        result = subprocess.run([
            "ssh-keygen", "-Y", "verify", "-f", str(allowed),
            "-I", PRINCIPALS[role], "-n", NAMESPACES[role],
            "-s", str(sig)], input=message, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        raise HandoffError(f"{role} local signature verification failed")


def _validate_tsa(context: Mapping[str, Any], owner_raw: bytes,
                  owner_signature: bytes) -> bytes:
    payload = _decode(context.get("ownerPayloadB64"), "ownerPayloadB64")
    signature = _decode(context.get("ownerSignatureB64"), "ownerSignatureB64")
    evidence_raw = _decode(
        context.get("timestampEvidenceB64"), "timestampEvidenceB64")
    request = _decode(context.get("timestampRequestB64"), "timestampRequestB64")
    response = _decode(context.get("timestampResponseB64"),
                       "timestampResponseB64")
    root_cert = _decode(context.get("timestampRootB64"), "timestampRootB64")
    intermediate = _decode(context.get("timestampIntermediateB64"),
                           "timestampIntermediateB64")
    responder = _decode(
        context.get("timestampResponderB64"), "timestampResponderB64")
    if _sha(root_cert) != EXPECTED_TSA_SHA256["root"] \
            or _sha(intermediate) != EXPECTED_TSA_SHA256["intermediate"] \
            or _sha(responder) != EXPECTED_TSA_SHA256["responder"]:
        raise HandoffError("timestamp certificate chain is not pinned")
    if payload != owner_raw or signature != owner_signature:
        raise HandoffError("review context owner artifact binding differs")
    payload_value = _validate_payload(payload)
    _verify_ssh(role="OWNER", message=payload, signature=signature)
    evidence = _json(evidence_raw, "timestamp evidence")
    provider = evidence.get("provider")
    response_evidence = evidence.get("timestampResponse")
    chain = evidence.get("certificateChain")
    bound = evidence.get("boundArtifact")
    if not all(isinstance(item, Mapping)
               for item in (provider, response_evidence, chain, bound)) \
            or evidence.get("schemaVersion") \
            != "e4-rfc3161-timestamp-evidence.v1" \
            or evidence.get("status") != "CANDIDATE_NOT_AUTHORIZED" \
            or evidence.get("stage") != "E4" \
            or provider != {"name": "DigiCert", "protocol": "RFC3161",
                            "endpoint": "http://timestamp.digicert.com",
                            "policyOid": TSA_POLICY} \
            or evidence.get("verification", {}).get("status") != "VERIFIED" \
            or evidence.get("authority", {}).get("trustedClockAttested") is not True \
            or evidence.get("messageImprint", {}).get("value") != _sha(signature) \
            or evidence.get("timestampRequest", {}).get("sha256") != _sha(request) \
            or response_evidence.get("sha256") != _sha(response) \
            or bound.get("payloadSha256") != _sha(payload) \
            or bound.get("ownerSignatureSha256") != _sha(signature) \
            or chain.get("pinnedRoot", {}).get("sha256") \
            != EXPECTED_TSA_SHA256["root"] \
            or chain.get("timestampCa", {}).get("sha256") \
            != EXPECTED_TSA_SHA256["intermediate"] \
            or chain.get("tsaResponder", {}).get("sha256") \
            != EXPECTED_TSA_SHA256["responder"]:
        raise HandoffError("timestamp evidence binding differs")
    with tempfile.TemporaryDirectory(prefix="e4-public-tsa-") as directory:
        path = Path(directory)
        files = {
            "request": request, "response": response,
            "root": root_cert, "intermediate": intermediate,
            "responder.der": responder, "owner-signature": signature,
        }
        for name, raw in files.items():
            (path / name).write_bytes(raw)
        checks = []
        checks.append(subprocess.run([
            "openssl", "ts", "-verify", "-queryfile", str(path / "request"),
            "-in", str(path / "response"), "-CAfile", str(path / "root"),
            "-untrusted", str(path / "intermediate")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False))
        checks.append(subprocess.run([
            "openssl", "ts", "-verify", "-data",
            str(path / "owner-signature"), "-in", str(path / "response"),
            "-CAfile", str(path / "root"), "-untrusted",
            str(path / "intermediate")], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False))
        converted = subprocess.run([
            "openssl", "x509", "-inform", "DER", "-in",
            str(path / "responder.der"), "-out", str(path / "responder.pem")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        verified_responder = subprocess.run([
            "openssl", "verify", "-CAfile", str(path / "root"),
            "-untrusted", str(path / "intermediate"),
            str(path / "responder.pem")], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False) if converted.returncode == 0 \
            else converted
        token = subprocess.run([
            "openssl", "ts", "-reply", "-in", str(path / "response"),
            "-token_out", "-out", str(path / "token.der")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        token_certs = subprocess.run([
            "openssl", "pkcs7", "-inform", "DER", "-in",
            str(path / "token.der"), "-print_certs"], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False) if token.returncode == 0 else token
        detail = subprocess.run([
            "openssl", "ts", "-reply", "-in", str(path / "response"),
            "-text"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False)
        token_raw = (path / "token.der").read_bytes() \
            if token.returncode == 0 else b""
    if any(result.returncode != 0 or b"Verification: OK" not in (
            result.stdout + result.stderr) for result in checks) \
            or verified_responder.returncode != 0 \
            or token.returncode != 0 or token_certs.returncode != 0 \
            or detail.returncode != 0:
        raise HandoffError("local pinned RFC3161 verification failed")
    certificate_blocks = re.findall(
        rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        token_certs.stdout, re.DOTALL)
    token_certificate_digests: set[str] = set()
    for certificate in certificate_blocks:
        converted_cert = subprocess.run([
            "openssl", "x509", "-outform", "DER"], input=certificate,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if converted_cert.returncode == 0:
            token_certificate_digests.add(_sha(converted_cert.stdout))
    if EXPECTED_TSA_SHA256["responder"] not in token_certificate_digests \
            or response_evidence.get("tokenSha256") \
            != _sha(token_raw):
        raise HandoffError("timestamp responder certificate differs")
    detail_text = detail.stdout.decode("utf-8", errors="strict")
    policy = re.search(r"^Policy OID:\s*(\S+)$", detail_text, re.MULTILINE)
    serial = re.search(
        r"^Serial number:\s*(?:0x)?([0-9A-Fa-f]+)$", detail_text,
        re.MULTILINE)
    stamp = re.search(
        r"^Time stamp:\s*(.+ GMT)$", detail_text, re.MULTILINE)
    nonce = re.search(
        r"^Nonce:\s*(?:0x)?([0-9A-Fa-f]+)$", detail_text, re.MULTILINE)
    if not all((policy, serial, stamp, nonce)) or policy.group(1) != TSA_POLICY:
        raise HandoffError("timestamp policy, serial, time or nonce is invalid")
    generated = dt.datetime.strptime(
        stamp.group(1), "%b %d %H:%M:%S %Y GMT").replace(tzinfo=dt.UTC)
    generated_ms = int(generated.timestamp() * 1000)
    approval = payload_value["approval"]
    if not approval["approvedAtEpochMs"] <= generated_ms \
            <= approval["expiresAtEpochMs"] \
            or response_evidence.get("genTimeUtc") \
            != generated.strftime("%Y-%m-%dT%H:%M:%SZ") \
            or response_evidence.get("serialNumber") != serial.group(1).upper() \
            or response_evidence.get("nonce") != nonce.group(1).upper():
        raise HandoffError("timestamp freshness evidence differs")
    return evidence_raw


def _validate_review(raw: bytes, state: Mapping[str, bytes],
                     context: Mapping[str, Any]) -> None:
    value = _json(raw, "review envelope")
    _authority_false(value, "review envelope")
    if value.get("schemaVersion") != "e4-reviewer-review-envelope.v1" \
            or value.get("status") != "READY_FOR_OFFLINE_REVIEWER_SIGNATURE" \
            or value.get("disposition") != "REVIEW_PASS_NON_AUTHORITATIVE" \
            or value.get("binding") != EXPECTED_BINDING:
        raise HandoffError("review envelope shape or binding differs")
    owner = value.get("ownerPayload", {})
    timestamp = value.get("timestampEvidence", {})
    if owner.get("payloadSha256") != _sha(state["owner_raw"]) \
            or owner.get("ownerSignatureSha256") != _sha(state["owner_signature"]):
        raise HandoffError("review owner-artifact binding differs")
    evidence_raw = _validate_tsa(
        context, state["owner_raw"], state["owner_signature"])
    if timestamp.get("sha256") != _sha(evidence_raw) \
            or timestamp.get("boundSignatureSha256") \
            != _sha(state["owner_signature"]):
        raise HandoffError("review timestamp binding differs")
    state["timestamp_evidence"] = evidence_raw  # type: ignore[index]


def _validate_promotion(raw: bytes, state: Mapping[str, bytes]) -> None:
    value = _json(raw, "trust-root promotion")
    _authority_false(value, "trust-root promotion")
    bound = value.get("boundEvidence")
    frozen = value.get("frozenBinding")
    if value.get("schemaVersion") != "e4-trust-registry-promotion-payload.v1" \
            or value.get("status") != "READY_FOR_OFFLINE_TRUST_ROOT_SIGNATURE" \
            or not isinstance(bound, Mapping) or not isinstance(frozen, Mapping):
        raise HandoffError("trust-root promotion shape is invalid")
    expected_frozen = {
        key: EXPECTED_BINDING[key] for key in (
            "planId", "targetRef", "targetFingerprintSha256",
            "snapshotSha256", "keyRefSha256", "scope", "invocationLimit")}
    if dict(frozen) != expected_frozen:
        raise HandoffError("trust-root promotion frozen binding differs")
    expected_hashes = {
        "ownerPayloadSha256": _sha(state["owner_raw"]),
        "ownerSignatureSha256": _sha(state["owner_signature"]),
        "reviewerEnvelopeSha256": _sha(state["reviewer_raw"]),
        "reviewerSignatureSha256": _sha(state["reviewer_signature"]),
        "timestampEvidenceSha256": _sha(state["timestamp_evidence"]),
    }
    if any(bound.get(field) != item for field, item in expected_hashes.items()):
        raise HandoffError("trust-root promotion artifact binding differs")
    trust = value.get("trustRoot", {})
    if trust.get("publicKeySha256") != EXPECTED_PUBLIC_SHA256["TRUST_ROOT"] \
            or trust.get("offlineOriginAttested") is not True \
            or trust.get("privateKeyMustRemainOffline") is not True:
        raise HandoffError("trust-root identity binding differs")


def _sign(role: str, raw: bytes, *, private: Path | None = None) -> bytes:
    private = private or PRIVATE_KEYS[role]
    _private_key_shape(private)
    if _sha(_read(PUBLIC_KEYS[role], 4096)) != EXPECTED_PUBLIC_SHA256[role]:
        raise HandoffError(f"{role} public key digest differs")
    print(f"Введите passphrase: {private.name}", flush=True)
    result = subprocess.run([
        "ssh-keygen", "-Y", "sign", "-f", str(private),
        "-n", NAMESPACES[role]], input=raw, stdout=subprocess.PIPE,
        stderr=None, check=False)
    if result.returncode != 0 or not result.stdout.startswith(
            b"-----BEGIN SSH SIGNATURE-----"):
        raise HandoffError(f"{role} signing failed")
    _verify_ssh(role=role, message=raw, signature=result.stdout)
    return result.stdout


def _write_new(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise HandoffError(f"{path.name} cannot be created exclusively") from exc
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(fd, raw[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)


def _review_request_record(message: Mapping[str, Any], raw: bytes) -> dict[str, Any]:
    context = message.get("context")
    digest = message.get("artifactSha256")
    if not isinstance(context, Mapping) or digest != _sha(raw):
        raise HandoffError("independent reviewer request binding differs")
    return {
        "schemaVersion": "e4-independent-reviewer-request.v1",
        "role": "REVIEWER",
        "namespace": NAMESPACES["REVIEWER"],
        "principal": PRINCIPALS["REVIEWER"],
        "artifactName": message.get("artifactName"),
        "artifactSha256": digest,
        "publicKeySha256": EXPECTED_PUBLIC_SHA256["REVIEWER"],
        "contentB64": base64.b64encode(raw).decode("ascii"),
        "context": dict(context),
        "sameDeviceReviewerAllowed": False,
    }


def _review_response_signature(*, response_raw: bytes,
                               artifact_sha256: str, raw: bytes) -> bytes:
    response = _json(response_raw, "independent reviewer response")
    if set(response) != {
            "schemaVersion", "role", "artifactSha256", "signatureB64"} \
            or response.get("schemaVersion") \
            != "e4-independent-reviewer-response.v1" \
            or response.get("role") != "REVIEWER" \
            or response.get("artifactSha256") != artifact_sha256:
        raise HandoffError("independent reviewer response binding differs")
    signature = _decode(
        response.get("signatureB64"), "reviewer signature", MAX_KEY_BYTES)
    _verify_ssh(role="REVIEWER", message=raw, signature=signature)
    return signature


def _external_reviewer_signature(*, message: Mapping[str, Any], raw: bytes,
                                 state: dict[str, bytes]) -> bytes:
    if REVIEWER_PRIVATE.exists():
        raise HandoffError(
            "reviewer private key is present on the owner device; move the "
            "reviewer role to a genuinely independent device")
    context = message.get("context")
    if not isinstance(context, Mapping):
        raise HandoffError("review context is missing")
    _validate_review(raw, state, context)
    digest = _sha(raw)
    request_path = KEY_DIR / f"e4-review-request-{digest[:16]}.json"
    response_path = KEY_DIR / f"e4-review-response-{digest[:16]}.json"
    request = _review_request_record(message, raw)
    _write_new(request_path, (json.dumps(
        request, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n").encode())
    print("Нужна подпись независимого reviewer с другого устройства.", flush=True)
    print(f"Передайте файл: {request_path}", flush=True)
    print(f"Верните ответ в: {response_path}", flush=True)
    input("После безопасного переноса reviewer-ответа нажмите Enter: ")
    response_raw = _read(response_path, MAX_LINE_BYTES)
    return _review_response_signature(
        response_raw=response_raw, artifact_sha256=digest, raw=raw)


def _offline_reviewer(*, request_path: Path, response_path: Path,
                      reviewer_private: Path) -> int:
    if any(path.exists() for path in (*PRIVATE_KEYS.values(), RECIPIENT_KEY)):
        raise HandoffError(
            "owner, trust-root or decryption private material is present on "
            "the reviewer device")
    request = _json(_read(request_path, MAX_LINE_BYTES), "review request")
    if set(request) != {
            "schemaVersion", "role", "namespace", "principal", "artifactName",
            "artifactSha256", "publicKeySha256", "contentB64", "context",
            "sameDeviceReviewerAllowed"} \
            or request.get("schemaVersion") \
            != "e4-independent-reviewer-request.v1" \
            or request.get("role") != "REVIEWER" \
            or request.get("namespace") != NAMESPACES["REVIEWER"] \
            or request.get("principal") != PRINCIPALS["REVIEWER"] \
            or request.get("publicKeySha256") \
            != EXPECTED_PUBLIC_SHA256["REVIEWER"] \
            or request.get("sameDeviceReviewerAllowed") is not False:
        raise HandoffError("review request shape or reviewer identity differs")
    raw = _decode(request.get("contentB64"), "review content")
    if request.get("artifactSha256") != _sha(raw):
        raise HandoffError("review request artifact digest differs")
    context = request.get("context")
    if not isinstance(context, Mapping):
        raise HandoffError("review request context is missing")
    owner_raw = _decode(context.get("ownerPayloadB64"), "ownerPayloadB64")
    owner_signature = _decode(
        context.get("ownerSignatureB64"), "ownerSignatureB64")
    state: dict[str, bytes] = {
        "owner_raw": owner_raw, "owner_signature": owner_signature}
    _validate_review(raw, state, context)
    signature = _sign("REVIEWER", raw, private=reviewer_private)
    response = {
        "schemaVersion": "e4-independent-reviewer-response.v1",
        "role": "REVIEWER", "artifactSha256": _sha(raw),
        "signatureB64": base64.b64encode(signature).decode("ascii"),
    }
    _write_new(response_path, (json.dumps(
        response, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n").encode())
    print(f"Reviewer response: {response_path}", flush=True)
    print(f"SHA256: {_sha(response_path.read_bytes())}", flush=True)
    return 0


def _decrypt_snapshot(pipe: Any, message: Mapping[str, Any]) -> int:
    _private_key_shape(RECIPIENT_KEY)
    if _sha(_public_line(RECIPIENT_PUBLIC).encode()) \
            != EXPECTED_KEY_REF_SHA256:
        raise HandoffError("owner-ssh public recipient binding differs")
    challenge = message.get("challenge")
    ciphertext_length = message.get("ciphertextLength")
    plaintext_length = message.get("expectedPlaintextLength")
    plaintext_sha = message.get("expectedPlaintextSha256")
    if not isinstance(challenge, str) or len(challenge) != 64 \
            or ciphertext_length != 460027 \
            or message.get("ciphertextSha256") \
            != EXPECTED_BINDING["snapshotSha256"] \
            or plaintext_length != 459703 \
            or plaintext_sha \
            != "d61b888edabf3ff69cbbe861a5ea33f8b8f172b9a01e2a94f4bab82627dcf001" \
            or message.get("keyRefSha256") != EXPECTED_KEY_REF_SHA256:
        raise HandoffError("ciphertext stream binding differs")
    flags = getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0)
    ciphertext_fd = os.memfd_create("e4-ciphertext-snapshot", flags)
    plaintext_fd = os.memfd_create("e4-plaintext-snapshot", flags)
    os.fchmod(ciphertext_fd, 0o600)
    os.fchmod(plaintext_fd, 0o600)
    try:
        digest = hashlib.sha256()
        remaining = ciphertext_length
        while remaining:
            chunk = pipe.read(min(64 * 1024, remaining))
            if not chunk:
                raise HandoffError("ciphertext stream ended early")
            os.write(ciphertext_fd, chunk)
            digest.update(chunk)
            remaining -= len(chunk)
        if digest.hexdigest() != EXPECTED_BINDING["snapshotSha256"]:
            raise HandoffError("ciphertext stream digest mismatch")
        seals = (fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
                 fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        fcntl.fcntl(ciphertext_fd, fcntl.F_ADD_SEALS, seals)
        os.lseek(ciphertext_fd, 0, os.SEEK_SET)
        print("Введите passphrase: owner-ssh", flush=True)
        decrypted = subprocess.run([
            "age", "--decrypt", "--identity", str(RECIPIENT_KEY)],
            stdin=ciphertext_fd, stdout=plaintext_fd, stderr=None, check=False)
        if decrypted.returncode != 0:
            raise HandoffError("local age decryption failed")
        metadata = os.fstat(plaintext_fd)
        if metadata.st_size != plaintext_length:
            raise HandoffError("plaintext snapshot size differs")
        digest = hashlib.sha256()
        offset = 0
        while offset < metadata.st_size:
            chunk = os.pread(
                plaintext_fd, min(64 * 1024, metadata.st_size - offset), offset)
            if not chunk:
                raise HandoffError("plaintext memfd ended during digest")
            digest.update(chunk)
            offset += len(chunk)
        if digest.hexdigest() != plaintext_sha:
            raise HandoffError("plaintext snapshot digest differs")
        fcntl.fcntl(plaintext_fd, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(plaintext_fd, fcntl.F_GET_SEALS) & seals != seals:
            raise HandoffError("plaintext memfd seals were not applied")
        os.lseek(plaintext_fd, 0, os.SEEK_SET)
        return plaintext_fd
    except Exception:
        os.close(plaintext_fd)
        raise
    finally:
        os.close(ciphertext_fd)


def _send_json(pipe: Any, value: Mapping[str, Any]) -> None:
    raw = (json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")) + "\n").encode()
    pipe.write(raw)
    pipe.flush()


def _receive_json(pipe: Any) -> dict[str, Any]:
    raw = pipe.readline(MAX_LINE_BYTES + 1)
    if not raw:
        raise HandoffError("SSH ceremony ended before a final result")
    if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
        raise HandoffError("SSH ceremony message is oversized")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError("SSH ceremony protocol is invalid") from exc
    if not isinstance(value, dict):
        raise HandoffError("SSH ceremony protocol root is invalid")
    return value


def _stream_plaintext(pipe: Any, fd: int, challenge: str) -> None:
    length = os.fstat(fd).st_size
    if length != 459703:
        raise HandoffError("plaintext snapshot size is invalid")
    _send_json(pipe, {
        "type": "PLAINTEXT_STREAM", "length": length,
        "challenge": challenge,
        "ciphertextSha256": EXPECTED_BINDING["snapshotSha256"],
        "plaintextSha256": (
            "d61b888edabf3ff69cbbe861a5ea33f8b8f172b9a01e2a94f4bab82627dcf001")})
    offset = 0
    while offset < length:
        chunk = os.pread(fd, min(4096, length - offset), offset)
        if not chunk:
            raise HandoffError("plaintext snapshot memfd ended early")
        pipe.write(chunk)
        offset += len(chunk)
    pipe.flush()


def _owner_main() -> int:
    if not OPERATIONAL_EXECUTION_ENABLED:
        raise HandoffError(
            "one-shot execution is disabled pending offline owner/trust-root "
            "handoffs, trusted final-bundle time, durable cross-run replay "
            "authority and versioned teardown semantics")
    for command in ("ssh", "ssh-keygen", "openssl", "age"):
        if shutil.which(command) is None:
            raise HandoffError(f"{command} is unavailable in Termux")
    for path in (*PRIVATE_KEYS.values(), RECIPIENT_KEY):
        _private_key_shape(path)
    if REVIEWER_PRIVATE.exists():
        raise HandoffError(
            "reviewer private key must not be present on the owner device")
    _verify_known_host()
    print("Введите SSH-пароль сервера один раз.", flush=True)
    process = subprocess.Popen([
        "ssh", "-T", "-o", "StrictHostKeyChecking=yes",
        "-o", "HostKeyAlgorithms=ssh-ed25519",
        "-o", "UpdateHostKeys=no", REMOTE, REMOTE_COMMAND],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None)
    if process.stdin is None or process.stdout is None:
        raise HandoffError("SSH pipes could not be created")
    state: dict[str, bytes] = {}
    expected_role = "OWNER"
    plaintext_fd: int | None = None
    try:
        while True:
            message = _receive_json(process.stdout)
            kind = message.get("type")
            if kind == "HELLO":
                if message.get("protocol") != "e4-one-shot.v1":
                    raise HandoffError("server protocol version differs")
                print("SSH подтверждён; создан свежий 15-минутный payload.",
                      flush=True)
                continue
            if kind == "SIGN_REQUEST":
                role = message.get("role")
                if role != expected_role or role not in NAMESPACES \
                        or message.get("namespace") != NAMESPACES[role] \
                        or message.get("principal") != PRINCIPALS[role] \
                        or message.get("publicKeySha256") \
                        != EXPECTED_PUBLIC_SHA256[role]:
                    raise HandoffError("signing request identity or order differs")
                raw = _decode(message.get("contentB64"), "signing content")
                digest = message.get("artifactSha256")
                if digest != _sha(raw):
                    raise HandoffError("signing request digest differs")
                if role == "OWNER":
                    _validate_payload(raw)
                    state["owner_raw"] = raw
                elif role == "REVIEWER":
                    context = message.get("context")
                    if not isinstance(context, Mapping):
                        raise HandoffError("review context is missing")
                    _validate_review(raw, state, context)
                    state["reviewer_raw"] = raw
                else:
                    _validate_promotion(raw, state)
                    state["promotion_raw"] = raw
                if role == "REVIEWER":
                    signature = _external_reviewer_signature(
                        message=message, raw=raw, state=state)
                else:
                    signature = _sign(role, raw)
                state[role.lower() + "_signature"] = signature
                _send_json(process.stdin, {
                    "type": "SIGNATURE", "role": role,
                    "artifactSha256": digest,
                    "signatureB64": base64.b64encode(signature).decode("ascii")})
                expected_role = {
                    "OWNER": "REVIEWER", "REVIEWER": "TRUST_ROOT",
                    "TRUST_ROOT": "DONE"}[role]
                print(f"{role}: подпись локально проверена.", flush=True)
                continue
            if kind == "PREFLIGHT":
                if expected_role != "DONE" \
                        or message.get("status") != "READY_NO_REPLAY_CLAIMED" \
                        or message.get("targetAbsent") is not True \
                        or message.get("snapshotDigestVerified") is not True \
                        or message.get("keyRecipientPublicBindingVerified") is not True \
                        or message.get("replayClaimed") is not False:
                    raise HandoffError("server preflight is not fail-closed ready")
                print("Preflight готов: replay ещё не израсходован.", flush=True)
                continue
            if kind == "SNAPSHOT_STREAM":
                plaintext_fd = _decrypt_snapshot(process.stdout, message)
                _stream_plaintext(
                    process.stdin, plaintext_fd, str(message["challenge"]))
                print("Snapshot расшифрован локально; ключ серверу не передан.",
                      flush=True)
                print("Начинается изолированная репетиция.", flush=True)
                continue
            if kind == "FINAL":
                if message.get("status") \
                        != "NON_PRODUCTION_REHEARSAL_SOURCE_RETENTION_REVIEW" \
                        or message.get("replayClaimCount") != 1 \
                        or message.get("targetAbsentAfter") is not True \
                        or message.get("sourceCiphertextRetained") is not True \
                        or message.get("decryptionKeyReceivedByServer") is not False \
                        or message.get("productionContacted") is not False:
                    raise HandoffError("server final evidence is not accepted")
                print(json.dumps(message, ensure_ascii=False, sort_keys=True,
                                 indent=2), flush=True)
                raise HandoffError(
                    "v1 rehearsal remains incomplete: immutable source "
                    "ciphertext was retained and the frozen teardown gate "
                    "was not satisfied")
            if kind == "ERROR":
                raise HandoffError(
                    "server fail-closed: " + str(message.get("message", "unknown")))
            raise HandoffError("unexpected server protocol message")
    finally:
        if plaintext_fd is not None:
            os.close(plaintext_fd)
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        try:
            return_code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
            return_code = process.returncode
        if return_code not in (0, None) and sys.exc_info()[0] is None:
            raise HandoffError(f"SSH ceremony exited with status {return_code}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the split E4 ceremony")
    parser.add_argument("--review-request", type=Path)
    parser.add_argument("--review-response", type=Path)
    parser.add_argument("--reviewer-private", type=Path,
                        default=REVIEWER_PRIVATE)
    args = parser.parse_args(argv)
    if (args.review_request is None) != (args.review_response is None):
        raise HandoffError(
            "review request and response paths must be supplied together")
    if args.review_request is not None:
        return _offline_reviewer(
            request_path=args.review_request,
            response_path=args.review_response,
            reviewer_private=args.reviewer_private)
    return _owner_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"E4_ONE_SHOT_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
