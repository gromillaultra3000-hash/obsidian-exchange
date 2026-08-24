"""Generate one fresh, fail-closed E4 owner decision payload.

The generator refreshes only the payload identity, approval window and replay
nonce.  It preserves all frozen snapshot, target and trust bindings from the
source payload and never creates a signature or execution authority.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


PAYLOAD_SCHEMA = "e4-owner-decision-payload.v1"
READY_STATUS = "READY_FOR_OFFLINE_OWNER_SIGNATURE"
MAX_AUTHORIZATION_MS = 15 * 60 * 1000
_PAYLOAD_ID = re.compile(
    r"^e4-owner-decision-payload-(?P<day>[0-9]{8})-"
    r"(?P<sequence>[0-9]{2})-(?P<epoch>[0-9]+)$")
_SOURCE_NAME = re.compile(r"^e4-owner-decision-payload\.v(?P<version>[0-9]+)\.json$")
_AUTHORITY_FALSE_FIELDS = (
    "authenticated",
    "ownerApproval",
    "independentReview",
    "rehearsalExecutionEligible",
    "executionAuthorized",
    "productionDatabaseContactAllowed",
    "productionNetworkAllowed",
    "productionCredentialsAllowed",
    "proposalApplicationAllowed",
    "persistentTargetAllowed",
    "automaticRetryAllowed",
    "containsSecrets",
    "containsConnectionMaterial",
    "promotionAllowed",
    "actionAllowed",
)
_APPROVAL_FALSE_FIELDS = (
    "productionDatabaseContactAllowed",
    "productionNetworkAllowed",
    "productionCredentialsAllowed",
    "proposalApplicationAllowed",
    "persistentTargetAllowed",
    "automaticRetryAllowed",
    "containsSecrets",
    "containsConnectionMaterial",
    "promotionAllowed",
    "actionAllowed",
)
_TOP_LEVEL_FIELDS = {
    "schemaVersion", "payloadId", "supersedes", "status", "stage",
    "route", "purpose", "authority", "trustAnchors", "trustedClock",
    "frozenBinding", "approval", "replay", "signaturePlan",
    "requiredBeforeHandoff", "forbiddenContents", "nextAction",
}
_FROZEN_FIELDS = {
    "planSchemaVersion", "planId", "planSourcePath", "planSourceSha256",
    "evidenceManifestPath", "evidenceManifestSha256", "stagedManifestPath",
    "stagedManifestSha256", "targetClass", "snapshotClass", "scope",
    "invocationLimit",
}
_APPROVAL_FIELDS = {
    "approvalRef", "planId", "targetRef", "targetFingerprintSha256",
    "snapshotSha256", "snapshotRefSha256", "keyRefSha256",
    "approvedAtEpochMs", "expiresAtEpochMs", "scope", "invocationLimit",
    *_APPROVAL_FALSE_FIELDS, "executionEffect",
}
_EXPECTED_FROZEN_BINDING = {
    "planSchemaVersion": "e4-full-snapshot-rehearsal-runner-plan.v1",
    "planId": "e4rrp_73040dd58161e760075b961004c173966291a8d33344f248cf6a43ec75893ffd",
    "planSourcePath": "relay/core/e4_rehearsal_runner_plan.py",
    "planSourceSha256": "eb70458a03fdb5b744f44f0fd390e78f17a65226e2a48b2c763db3ff2623cc2c",
    "evidenceManifestPath": (
        "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"),
    "evidenceManifestSha256": "2489745da1fd584c3d77965ebc7b4776ddad3115bcbea5dc7a623fc3d2981a03",
    "stagedManifestPath": (
        "E4-owner-handoff/e4-disconnected-snapshot-staging-manifest.staged.v1.json"),
    "stagedManifestSha256": "c9d94148fe163a284e8ad6df3640e4da9be1f2a090ea7d873e8a7d9bcab2594a",
    "targetClass": "ISOLATED_DISPOSABLE_POSTGRESQL",
    "snapshotClass": "PREEXISTING_ENCRYPTED_IMMUTABLE_SNAPSHOT_COPY",
    "scope": "ONE_E4_ISOLATED_FULL_SNAPSHOT_REHEARSAL",
    "invocationLimit": 1,
}
_EXPECTED_APPROVAL_BINDING = {
    "planId": _EXPECTED_FROZEN_BINDING["planId"],
    "targetRef": "e4-disposable-pg-20260822-02",
    "targetFingerprintSha256": "3545e043156cd9023d46a5ebaaa12f0c964ceea2887cea79c9703395a1588ad3",
    "snapshotSha256": "47efc0dc293890243072bdf048d40cbcc1fee8fbe719e4b841fb5d156f658b3e",
    "snapshotRefSha256": "d56f226fb3c38cc40f7265d1d15c2c751211bb86ff1beba655f82f99d5d4b619",
    "keyRefSha256": "c7e21692ac64774b4229807d5b11338df72f722247a1bcebb22d54667a102109",
    "scope": _EXPECTED_FROZEN_BINDING["scope"],
    "invocationLimit": 1,
}
_EXPECTED_TRUST_ANCHORS = {
    "registryId": "e4-owner-reviewer-anchors-20260822-v4",
    "registryProposalSha256": "3de9ccbeb67178f46af1be68a139712b8d6acbe6954d7eef340625d472af4bfe",
    "status": "CANDIDATE_NOT_AUTHORIZED",
    "trustRoot": {
        "issuerId": "e4-trust-root",
        "publicKeySha256": "5669b2922f49c3c661be658c969566ce256bf7874d3fd1790c31299a4c4519d0",
        "fingerprint": "SHA256:Ja+GZ9/o52eFmzZDztpju70RWmYpSvc0Fp+ayO1GcfM",
        "activationCandidateSha256": "7dc9c77b1a1a1e01a737e7d4d76f97953d4e8414aa183521e7aaadacbd329634",
        "active": False,
    },
    "owner": {
        "role": "ACCOUNTABLE_OWNER", "issuerId": "e4-owner-signing-v2",
        "trustRootId": "e4-owner-reviewer-anchors-20260822-v4",
        "publicKeySha256": "8ee7fb9b018e485b1e3cb9c0f36bb94ede78848af4323470a43adbd0bef71d63",
        "fingerprint": "SHA256:G4szs+1DvEQygs3LZS1LDNNRyBYLUHZuX0a7C/gRjII",
    },
    "reviewer": {
        "role": "INDEPENDENT_REVIEWER",
        "issuerId": "e4-independent-reviewer",
        "trustRootId": "e4-owner-reviewer-anchors-20260822-v4",
        "publicKeySha256": "79013979c27cae19fc304269fd390861cb7bdd561d2ca955b96eda8a9e29a095",
        "fingerprint": "SHA256:3YtNkuP+qf7PIcj9AmqSSTLr+Ocd4luwbeQSB8oRNq4",
    },
}
_EXPECTED_TRUSTED_CLOCK = {
    "provider": "DigiCert", "protocol": "RFC3161",
    "endpoint": "http://timestamp.digicert.com", "attestationRef": None,
    "attestationSha256": None, "verified": False,
}
_EXPECTED_SIGNATURE_PLAN = {
    "ownerNamespace": "e4-owner@obsidian-exchange.local",
    "reviewerNamespace": "e4-reviewer@obsidian-exchange.local",
    "ownerSignatureRef": None, "ownerSignatureSha256": None,
    "reviewerEnvelopeRef": None, "reviewerEnvelopeSha256": None,
    "reviewerSignatureRef": None, "reviewerSignatureSha256": None,
}
_EXPECTED_PUBLIC_CONTENT = {
    "purpose": (
        "Exact public payload for one bounded owner decision. This file is "
        "signable but is not an authorization receipt or execution command."),
    "requiredBeforeHandoff": [
        "Owner verifies the exact file bytes and owner-signing-v2 public-key fingerprint offline.",
        "Owner signs this exact file with the owner-signing-v2 private key and does not edit it afterward.",
        "DigiCert RFC 3161 timestamps the exact signed artifact or an exact digest-bound signature record; the token and public validation chain are retained.",
        "Independent reviewer verifies the owner signature, every frozen binding, immutable staging evidence, scope and expiry through a separate trust path.",
        "Reviewer creates and signs a separate review envelope bound to this exact payload digest.",
        "A real verifier accepts both signatures, trust anchors, freshness, trusted clock and replay state before any executor is eligible.",
    ],
    "forbiddenContents": [
        "private keys or signing seed material",
        "passwords or passphrases",
        "plaintext snapshot bytes",
        "production credentials or connection strings",
        "a self-generated eligible receipt or execution command",
    ],
    "nextAction": (
        "Verify this exact file offline, sign it with owner-signing-v2, and "
        "return only the public SSH signature plus the payload SHA-256. Do "
        "not run Docker, decrypt the snapshot or treat the signature alone "
        "as execution authority."),
}


class PayloadRefreshError(ValueError):
    """Raised when a source payload is unsafe or malformed."""


def _no_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PayloadRefreshError("source payload contains duplicate fields")
        value[key] = item
    return value


def _positive_epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PayloadRefreshError(f"{field} is invalid")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise PayloadRefreshError(f"source payload {field} fields are invalid")


def _load_source(path: Path) -> dict[str, Any]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024:
                raise PayloadRefreshError("source payload file is invalid")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read(64 * 1024 + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError as exc:
        raise PayloadRefreshError("source payload cannot be read") from exc
    if len(raw) > 64 * 1024:
        raise PayloadRefreshError("source payload is oversized")
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_no_duplicate_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                PayloadRefreshError("source payload contains non-finite JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PayloadRefreshError("source payload JSON is invalid") from exc
    if not isinstance(value, dict):
        raise PayloadRefreshError("source payload root is invalid")
    return value


def _validate_source(value: Mapping[str, Any]) -> tuple[str, int]:
    _exact_fields(value, _TOP_LEVEL_FIELDS, "top-level")
    if value.get("schemaVersion") != PAYLOAD_SCHEMA:
        raise PayloadRefreshError("source payload schema is invalid")
    if value.get("status") != READY_STATUS:
        raise PayloadRefreshError("source payload status is invalid")
    payload_id = value.get("payloadId")
    match = _PAYLOAD_ID.fullmatch(payload_id) if isinstance(payload_id, str) else None
    if match is None:
        raise PayloadRefreshError("source payload ID is invalid")
    authority = value.get("authority")
    if not isinstance(authority, Mapping):
        raise PayloadRefreshError("source payload authority is invalid")
    _exact_fields(
        authority, set(_AUTHORITY_FALSE_FIELDS) | {"executionEffect"},
        "authority")
    if any(
            authority.get(field) is not False
            for field in _AUTHORITY_FALSE_FIELDS):
        raise PayloadRefreshError("source payload authority is not fail-closed")
    if authority.get("executionEffect") != "NONE":
        raise PayloadRefreshError("source payload execution effect is invalid")
    approval = value.get("approval")
    replay = value.get("replay")
    frozen = value.get("frozenBinding")
    if not all(isinstance(item, Mapping)
               for item in (approval, replay, frozen)):
        raise PayloadRefreshError("source payload binding is invalid")
    _exact_fields(approval, _APPROVAL_FIELDS, "approval")
    _exact_fields(replay, {
        "nonceSha256", "singleUse", "retryAfterAmbiguousSubmitAllowed"},
        "replay")
    _exact_fields(frozen, _FROZEN_FIELDS, "frozen binding")
    if dict(frozen) != _EXPECTED_FROZEN_BINDING:
        raise PayloadRefreshError("source frozen binding differs")
    if any(approval.get(field) != expected
           for field, expected in _EXPECTED_APPROVAL_BINDING.items()):
        raise PayloadRefreshError("source approval binding differs")
    if approval.get("invocationLimit") != 1 \
            or replay.get("singleUse") is not True \
            or replay.get("retryAfterAmbiguousSubmitAllowed") is not False \
            or frozen.get("invocationLimit") != 1:
        raise PayloadRefreshError("source payload invocation limit is invalid")
    if any(approval.get(field) is not False
           for field in _APPROVAL_FALSE_FIELDS) \
            or approval.get("executionEffect") != "NONE":
        raise PayloadRefreshError("source approval is not fail-closed")
    approved = _positive_epoch(
        approval.get("approvedAtEpochMs"), "approvedAtEpochMs")
    expires = _positive_epoch(
        approval.get("expiresAtEpochMs"), "expiresAtEpochMs")
    if not approved < expires <= approved + MAX_AUTHORIZATION_MS:
        raise PayloadRefreshError("source payload lifetime is invalid")
    signature = value.get("signaturePlan")
    clock = value.get("trustedClock")
    anchors = value.get("trustAnchors")
    if not all(isinstance(item, Mapping)
               for item in (signature, clock, anchors)):
        raise PayloadRefreshError("source payload trust shape is invalid")
    _exact_fields(signature, {
        "ownerNamespace", "reviewerNamespace", "ownerSignatureRef",
        "ownerSignatureSha256", "reviewerEnvelopeRef",
        "reviewerEnvelopeSha256", "reviewerSignatureRef",
        "reviewerSignatureSha256"}, "signature plan")
    _exact_fields(clock, {
        "provider", "protocol", "endpoint", "attestationRef",
        "attestationSha256", "verified"}, "trusted clock")
    _exact_fields(anchors, {
        "registryId", "registryProposalSha256", "status", "trustRoot",
        "owner", "reviewer"}, "trust anchors")
    for role, fields in {
            "trustRoot": {"issuerId", "publicKeySha256", "fingerprint",
                          "activationCandidateSha256", "active"},
            "owner": {"role", "issuerId", "trustRootId", "publicKeySha256",
                      "fingerprint"},
            "reviewer": {"role", "issuerId", "trustRootId",
                         "publicKeySha256", "fingerprint"}}.items():
        role_value = anchors.get(role)
        if not isinstance(role_value, Mapping):
            raise PayloadRefreshError("source payload trust role is invalid")
        _exact_fields(role_value, fields, f"trust anchor {role}")
    if dict(anchors) != _EXPECTED_TRUST_ANCHORS:
        raise PayloadRefreshError("source trust anchors differ")
    if dict(clock) != _EXPECTED_TRUSTED_CLOCK:
        raise PayloadRefreshError("source trusted clock differs")
    if dict(signature) != _EXPECTED_SIGNATURE_PLAN:
        raise PayloadRefreshError("source signature plan differs")
    if value.get("stage") != "E4" or value.get("route") != (
            "E4_OWNER_GATED_FRESH_PRODUCTION_DISCONNECTED_REHEARSAL"):
        raise PayloadRefreshError("source stage or route differs")
    for field in ("purpose", "route", "nextAction"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise PayloadRefreshError(f"source payload {field} is invalid")
    for field in ("requiredBeforeHandoff", "forbiddenContents"):
        items = value.get(field)
        if not isinstance(items, list) or not items or any(
                not isinstance(item, str) or not item for item in items):
            raise PayloadRefreshError(f"source payload {field} is invalid")
    if any(value.get(field) != expected
           for field, expected in _EXPECTED_PUBLIC_CONTENT.items()):
        raise PayloadRefreshError("source public instructions differ")
    return payload_id, int(match.group("sequence"))


def refresh_owner_payload(*, source: Mapping[str, Any],
                          approved_at_epoch_ms: int,
                          nonce: bytes) -> dict[str, Any]:
    """Return a fresh payload while preserving every frozen binding."""
    previous_id, previous_sequence = _validate_source(source)
    approved = _positive_epoch(approved_at_epoch_ms, "approvedAtEpochMs")
    if not isinstance(nonce, bytes) or len(nonce) != 32:
        raise PayloadRefreshError("nonce must contain exactly 32 bytes")
    sequence = previous_sequence + 1
    if sequence > 99:
        raise PayloadRefreshError("payload sequence is exhausted")
    day = datetime.fromtimestamp(approved / 1000, tz=UTC).strftime("%Y%m%d")
    suffix = f"{day}-{sequence:02d}-{approved}"
    refreshed = copy.deepcopy(dict(source))
    refreshed["payloadId"] = "e4-owner-decision-payload-" + suffix
    refreshed["supersedes"] = previous_id
    refreshed["approval"]["approvalRef"] = "e4-approval-" + suffix
    refreshed["approval"]["approvedAtEpochMs"] = approved
    refreshed["approval"]["expiresAtEpochMs"] = (
        approved + MAX_AUTHORIZATION_MS)
    refreshed["replay"]["nonceSha256"] = hashlib.sha256(nonce).hexdigest()
    _validate_source(refreshed)
    return refreshed


def _default_output(source_path: Path) -> Path:
    match = _SOURCE_NAME.fullmatch(source_path.name)
    if match is None:
        raise PayloadRefreshError("source filename is invalid")
    version = int(match.group("version")) + 1
    return source_path.with_name(
        f"e4-owner-decision-payload.v{version}.json")


def _write_new(path: Path, value: Mapping[str, Any]) -> tuple[int, str]:
    raw = (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o644)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except FileExistsError as exc:
        raise PayloadRefreshError("output already exists") from exc
    except OSError as exc:
        raise PayloadRefreshError("output cannot be written") from exc
    return len(raw), hashlib.sha256(raw).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create one fresh non-authoritative E4 owner payload")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--now-epoch-ms", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        source = _load_source(args.source)
        now = (args.now_epoch_ms if args.now_epoch_ms is not None
               else time.time_ns() // 1_000_000)
        refreshed = refresh_owner_payload(
            source=source, approved_at_epoch_ms=now,
            nonce=os.urandom(32))
        output = args.output or _default_output(args.source)
        size, digest = _write_new(output, refreshed)
    except PayloadRefreshError as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"PAYLOAD={output}")
    print(f"SHA256={digest}")
    print(f"SIZE={size}")
    print(f"EXPIRES_AT_EPOCH_MS={refreshed['approval']['expiresAtEpochMs']}")
    print("AUTHORITY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
