"""One-shot operator entrypoint for the authenticated E4 rehearsal.

The module binds the current public v12 ceremony to the hardened executor.  It
accepts the already-unlocked SSH decryption identity only on stdin, copies it
to a sealed anonymous memfd, verifies its public half, and never persists key
or plaintext bytes.  ``--preflight-only`` is read-only and never creates a
replay ledger, receipt ledger, container, or decryption process.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.e4_authoritative_gate_callbacks import E4AuthoritativeGateCallbacks
from core.e4_hardened_executor import (
    EphemeralFDKeySource,
    HardenedE4Executor,
    ImmutableEncryptedSnapshot,
    SubprocessDockerRuntime,
)
from core.e4_owner_reviewer_replay_registry import (
    SQLiteE4OwnerReviewerReplayRegistry,
)
from core.e4_rehearsal_receipt_consumption import (
    SQLiteE4RehearsalReceiptLedger,
)
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
MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"
SNAPSHOT = HANDOFF / "obsidian_exchange-cutover-20260810.dump.age"
PAYLOAD = HANDOFF / "e4-owner-decision-payload.v12.json"
OWNER_SIGNATURE = HANDOFF / "e4-owner-decision-payload.v12.json.sig"
ENVELOPE = HANDOFF / "e4-reviewer-review-envelope.v6.json"
REVIEWER_SIGNATURE = HANDOFF / "e4-reviewer-review-envelope.v6.json.sig"
PROMOTION = HANDOFF / "e4-trust-registry-promotion-payload.v3.json"
PROMOTION_SIGNATURE = HANDOFF / "e4-trust-registry-promotion-payload.v3.json.sig"
TIMESTAMP_EVIDENCE = HANDOFF / (
    "e4-owner-decision-payload.v12.json.sig.digicert-rfc3161-evidence.v1.json"
)
TIMESTAMP_REQUEST = HANDOFF / "e4-owner-decision-payload.v12.json.sig.tsq"
TIMESTAMP_RESPONSE = HANDOFF / "e4-owner-decision-payload.v12.json.sig.tsr"
PUBLIC_RECIPIENT = HANDOFF / "owner-ssh.pub"
REGISTRY = HANDOFF / "e4-owner-reviewer-trust-anchor-and-binding-candidate.v4.json"
OWNER_PUBLIC = HANDOFF / "owner-signing-v2.pub"
REVIEWER_PUBLIC = HANDOFF / "reviewer-signing-v2.pub"
TRUST_ROOT_PUBLIC = HANDOFF / "e4-trust-root.pub"
TSA_ROOT = HANDOFF / "DigiCertAssuredIDRootCA.crt.pem"
TSA_INTERMEDIATE = HANDOFF / "DigiCertTrustedG4TimeStampingRSA4096SHA2562025CA1.pem"
GATE_DIR = Path("/var/tmp/e4-v12-gate-1787451789312")
REPLAY_DB = GATE_DIR / "replay.sqlite3"
RECEIPT_DB = GATE_DIR / "receipt.sqlite3"
RESULT_PATH = HANDOFF / "e4-hardened-rehearsal-result.v12.json"
MAX_KEY_BYTES = 16 * 1024
EXPECTED_SNAPSHOT_SHA256 = (
    "47efc0dc293890243072bdf048d40cbcc1fee8fbe719e4b841fb5d156f658b3e"
)
EXPECTED_SNAPSHOT_REF_SHA256 = (
    "d56f226fb3c38cc40f7265d1d15c2c751211bb86ff1beba655f82f99d5d4b619"
)
EXPECTED_KEY_REF_SHA256 = (
    "c7e21692ac64774b4229807d5b11338df72f722247a1bcebb22d54667a102109"
)


class InvocationError(ValueError):
    """A fail-closed operator invocation error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise InvocationError(f"{path.name} root is invalid")
    return value


def _public_line(path: Path) -> str:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if len(lines) != 1 or not lines[0].startswith("ssh-ed25519 "):
        raise InvocationError("public recipient shape is invalid")
    return lines[0]


def _promotion(now: int) -> Mapping[str, Any]:
    return verify_authenticated_promotion(
        promotion_path=PROMOTION,
        promotion_signature_path=PROMOTION_SIGNATURE,
        trust_root_public_key_path=TRUST_ROOT_PUBLIC,
        registry_path=REGISTRY,
        payload_path=PAYLOAD,
        owner_signature_path=OWNER_SIGNATURE,
        owner_public_key_path=OWNER_PUBLIC,
        envelope_path=ENVELOPE,
        reviewer_signature_path=REVIEWER_SIGNATURE,
        reviewer_public_key_path=REVIEWER_PUBLIC,
        timestamp_evidence_path=TIMESTAMP_EVIDENCE,
        timestamp_request_path=TIMESTAMP_REQUEST,
        timestamp_response_path=TIMESTAMP_RESPONSE,
        timestamp_root_path=TSA_ROOT,
        timestamp_intermediate_path=TSA_INTERMEDIATE,
        evaluated_at_epoch_ms=now,
    )


def _snapshot_source() -> ImmutableEncryptedSnapshot:
    metadata = os.stat(SNAPSHOT, follow_symlinks=False)
    parent = os.stat(SNAPSHOT.parent, follow_symlinks=False)
    if metadata.st_dev != 0x801 or metadata.st_ino != 2412135 \
            or metadata.st_size != 460027 or metadata.st_nlink != 1:
        raise InvocationError("snapshot immutable handle differs")
    return ImmutableEncryptedSnapshot(
        path=SNAPSHOT,
        expected_sha256=EXPECTED_SNAPSHOT_SHA256,
        expected_device=0x801,
        expected_inode=2412135,
        expected_size_bytes=460027,
        expected_hardlink_count=1,
        expected_parent_device=parent.st_dev,
        expected_parent_inode=parent.st_ino,
        require_immutable=True,
    )


def _evidence_digest(check: str, facts: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        {"checkId": check, "facts": dict(facts)},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _prepare_public_inputs() -> dict[str, Any]:
    now = int(time.time() * 1000)
    payload = _json(PAYLOAD)
    approval_value = payload.get("approval")
    if not isinstance(approval_value, Mapping):
        raise InvocationError("owner approval is missing")
    if EXPECTED_SNAPSHOT_SHA256 != approval_value.get("snapshotSha256") \
            or EXPECTED_SNAPSHOT_REF_SHA256 != approval_value.get("snapshotRefSha256") \
            or EXPECTED_KEY_REF_SHA256 != approval_value.get("keyRefSha256"):
        raise InvocationError("owner snapshot/key binding differs")

    manifest_sha = _sha256(MANIFEST)
    plan = build_rehearsal_runner_plan(evidence_manifest_sha256=manifest_sha)
    target = approval_value["targetRef"]
    target_fingerprint = target_spec_fingerprint(target_ref=target)
    if plan["planId"] != approval_value.get("planId") \
            or target_fingerprint != approval_value.get("targetFingerprintSha256"):
        raise InvocationError("owner plan/target binding differs")

    normalized_recipient = _public_line(PUBLIC_RECIPIENT)
    if hashlib.sha256(normalized_recipient.encode()).hexdigest() \
            != EXPECTED_KEY_REF_SHA256:
        raise InvocationError("public recipient digest differs")

    verified = _promotion(now)
    if verified.get("status") != "VERIFIED" or verified.get("replayEligible") is not True:
        raise InvocationError("promotion is not replay-eligible")

    runtime = SubprocessDockerRuntime()
    if not runtime.target_absent(target_ref=target):
        raise InvocationError("disposable target is not absent")
    source = _snapshot_source()
    with source.open_verified(expected_sha256=EXPECTED_SNAPSHOT_SHA256):
        pass

    owner_approval = build_owner_approval(
        approval_ref=approval_value["approvalRef"],
        plan_id=approval_value["planId"],
        target_ref=target,
        target_fingerprint_sha256=target_fingerprint,
        snapshot_sha256=EXPECTED_SNAPSHOT_SHA256,
        snapshot_ref_sha256=EXPECTED_SNAPSHOT_REF_SHA256,
        key_ref_sha256=EXPECTED_KEY_REF_SHA256,
        approved_at_epoch_ms=approval_value["approvedAtEpochMs"],
        expires_at_epoch_ms=approval_value["expiresAtEpochMs"],
    )
    observed = int(time.time() * 1000)
    spec = target_spec(target_ref=target)
    facts = {
        "EXPLICIT_OWNER_APPROVAL": {
            "verificationId": verified["verificationId"],
            "promotionSha256": verified["promotionPayloadSha256"],
        },
        "DISPOSABLE_TARGET_IDENTITY_VERIFIED": {
            "targetFingerprintSha256": target_fingerprint,
        },
        "TARGET_ABSENT_BEFORE_START": {"targetAbsent": True},
        "NO_PRODUCTION_NETWORK_ROUTE": {
            "network": spec["network"], "publishedPorts": spec["publishedPorts"],
        },
        "NO_PRODUCTION_CREDENTIALS_OR_SECRETS": {
            "productionCredentialsAllowed": False, "publicRecipientOnly": True,
        },
        "ENCRYPTED_SNAPSHOT_COPY_DIGEST_VERIFIED": {
            "ciphertextSha256": EXPECTED_SNAPSHOT_SHA256,
            "immutableHandle": "fs-801-2412135",
        },
        "EVIDENCE_MANIFEST_VERIFIED": {"manifestSha256": manifest_sha},
        "TEARDOWN_TARGET_VERIFIED": {
            "ownedTargetTeardownRequired": True, "targetAbsentBefore": True,
        },
    }
    evidence = [build_precondition_evidence(
        plan_id=plan["planId"], target_ref=target,
        target_fingerprint_sha256=target_fingerprint,
        snapshot_sha256=EXPECTED_SNAPSHOT_SHA256,
        check_id=check, observed_at_epoch_ms=observed, outcome="PASS",
        evidence_sha256=_evidence_digest(check, facts[check]),
    ) for check in PRECONDITIONS]
    receipt = authorize_rehearsal_runner(
        plan=plan, target_ref=target,
        target_fingerprint_sha256=target_fingerprint,
        snapshot_sha256=EXPECTED_SNAPSHOT_SHA256,
        evidence=evidence, owner_approval=owner_approval,
        assessed_at_epoch_ms=observed,
    )
    if receipt["status"] != "ELIGIBLE":
        raise InvocationError("authorization receipt is not eligible")
    snapshot_ref = "sha256_" + EXPECTED_SNAPSHOT_REF_SHA256
    key_ref = "sha256_" + EXPECTED_KEY_REF_SHA256
    boundary = build_runner_boundary(
        plan=plan, receipt=receipt,
        snapshot_ref=snapshot_ref, key_ref=key_ref,
    )
    return {
        "now": observed, "verified": verified, "runtime": runtime,
        "source": source, "plan": plan, "ownerApproval": owner_approval,
        "receipt": receipt, "boundary": boundary,
        "snapshotRef": snapshot_ref, "keyRef": key_ref,
    }


def _key_memfd() -> int:
    input_stat = os.fstat(0)
    if not (stat.S_ISFIFO(input_stat.st_mode) or
            stat.S_ISSOCK(input_stat.st_mode)):
        raise InvocationError("key handoff stdin is not an ephemeral stream")
    flags = getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0)
    fd = os.memfd_create("e4-owner-ssh", flags)
    os.fchmod(fd, 0o600)
    total = 0
    while True:
        chunk = os.read(0, min(4096, MAX_KEY_BYTES + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_KEY_BYTES:
            os.close(fd)
            raise InvocationError("ephemeral key stream is oversized")
        os.write(fd, chunk)
    if total == 0:
        os.close(fd)
        raise InvocationError("ephemeral key stream is empty")
    os.lseek(fd, 0, os.SEEK_SET)
    path = f"/proc/{os.getpid()}/fd/{fd}"
    result = subprocess.run(
        ["/usr/bin/ssh-keygen", "-y", "-P", "", "-f", path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        pass_fds=(fd,), timeout=5, check=False,
    )
    expected = " ".join(_public_line(PUBLIC_RECIPIENT).split()[:2])
    actual = result.stdout.decode("utf-8", errors="strict").strip()
    if result.returncode != 0 or actual != expected:
        os.close(fd)
        raise InvocationError("ephemeral key does not match the staged recipient")
    os.lseek(fd, 0, os.SEEK_SET)
    if hasattr(fcntl, "F_ADD_SEALS"):
        seals = (fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
                 fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
    return fd


def _write_result(value: Mapping[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2)
               + "\n").encode()
    fd = os.open(RESULT_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    finally:
        os.close(fd)


def _execute() -> dict[str, Any]:
    if RESULT_PATH.exists() or REPLAY_DB.exists() or RECEIPT_DB.exists():
        raise InvocationError("one-shot state already exists; do not retry")
    key_fd = _key_memfd()
    try:
        values = _prepare_public_inputs()
        GATE_DIR.mkdir(mode=0o700, parents=False, exist_ok=True)
        os.chmod(GATE_DIR, 0o700)
        replay = SQLiteE4OwnerReviewerReplayRegistry(str(REPLAY_DB))
        receipt_ledger = SQLiteE4RehearsalReceiptLedger(str(RECEIPT_DB))
        gate = E4AuthoritativeGateCallbacks(
            promotion_path=PROMOTION,
            promotion_signature_path=PROMOTION_SIGNATURE,
            trust_root_public_key_path=TRUST_ROOT_PUBLIC,
            registry_path=REGISTRY,
            payload_path=PAYLOAD,
            owner_signature_path=OWNER_SIGNATURE,
            owner_public_key_path=OWNER_PUBLIC,
            envelope_path=ENVELOPE,
            reviewer_signature_path=REVIEWER_SIGNATURE,
            reviewer_public_key_path=REVIEWER_PUBLIC,
            timestamp_evidence_path=TIMESTAMP_EVIDENCE,
            timestamp_request_path=TIMESTAMP_REQUEST,
            timestamp_response_path=TIMESTAMP_RESPONSE,
            timestamp_root_path=TSA_ROOT,
            timestamp_intermediate_path=TSA_INTERMEDIATE,
            replay_registry=replay,
            receipt_ledger=receipt_ledger,
        )
        result = HardenedE4Executor(runtime=values["runtime"]).execute(
            plan=values["plan"], receipt=values["receipt"],
            owner_approval=values["ownerApproval"],
            boundary=values["boundary"], gate_provider=gate,
            snapshot_ref=values["snapshotRef"], key_ref=values["keyRef"],
            snapshot_source=values["source"],
            key_source=EphemeralFDKeySource(key_fd),
        )
        _write_result(result)
        return result
    finally:
        os.close(key_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one authenticated E4 rehearsal")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.preflight_only:
            values = _prepare_public_inputs()
            summary = {
                "status": "READY_NO_REPLAY_CLAIMED",
                "planId": values["plan"]["planId"],
                "receiptId": values["receipt"]["receiptId"],
                "boundaryId": values["boundary"]["boundaryId"],
                "promotionVerificationId": values["verified"]["verificationId"],
                "targetAbsent": True,
                "snapshotDigestVerified": True,
                "keyRecipientPublicBindingVerified": True,
                "replayClaimed": False,
                "executionEffect": "NONE",
            }
            print(json.dumps(summary, sort_keys=True))
            return 0
        result = _execute()
        print(json.dumps({
            "status": result["status"],
            "executionId": result["executionId"],
            "resultSha256": result["resultSha256"],
            "targetAbsentAfter": result["teardown"]["targetAbsentAfter"],
            "sourceCiphertextRetained": result["snapshot"]["sourceCiphertextRetained"],
            "productionContacted": result["production"]["contacted"],
        }, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"E4_FAIL_CLOSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
