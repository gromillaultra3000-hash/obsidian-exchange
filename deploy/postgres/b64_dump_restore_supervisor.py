#!/usr/bin/env python3
"""Dormant production supervisor gate for the bounded 064A dump/restore.

The deployed command is deliberately a preflight, not an activation path.  It
authenticates the exact disposable rehearsal (when an independently provisioned
two-person evidence package is present), revalidates the immutable rehearsal
closure and proves that production is still dormant through the existing
watchdog.  It never issues a credential, enables LOGIN, reads customer rows or
starts a dump/restore container.

The later activation slice must add a separately reviewed execution entrypoint;
this module intentionally exposes none.  Keeping that boundary explicit makes
an installed supervisor safe while owner/reviewer evidence is still absent.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
POSTGRES = Path(__file__).resolve().parent
sys.path.insert(0, str(POSTGRES))

import b64_064a_hardened_refresh as refresh  # noqa: E402


ROUTE = "E0/E0.3/B5.3/064A"
EVIDENCE_SCHEMA = \
    "obsidian-e0-3-bot-b5-3-064a-scram-source-adapter-rehearsal.v1"
EVIDENCE_RELATIVE_PATH = \
    "docs/e0-3-bot-b5-3-064a-scram-source-adapter-rehearsal.v1.json"
PLAN_RELATIVE_PATH = \
    "docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json"
EVIDENCE_SHA256 = \
    "d9e690aa77b0e58887417da718c2f5786c0616c7c9291937a4adb5c34bd87dfc"
REHEARSAL_PLAN_SHA256 = \
    "14d38a9fc0cc7c78014d16230553359939aad7d7a15abaf7c7cc8672c3c8d0c6"
REHEARSAL_RELEASE_COMMIT = \
    "abb22afc99e504cee29881d5e4b19ba15c0f343d"
PRODUCTION_IMAGE_ID = \
    "sha256:7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee"
PRODUCTION_SERVER_VERSION_NUM = 170011
MAX_JSON_BYTES = 1024 * 1024
MAX_ACCEPTANCE_LIFETIME_SECONDS = 24 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 60

ARTIFACT_PATHS = {
    "runner": "deploy/postgres/b64_064a_hardened_refresh.py",
    "dirtyScan": "deploy/postgres/check_b64_notification_migration.py",
    "catalogFingerprintSql":
        "deploy/postgres/b64_catalog_security_fingerprint.sql",
    "tableFingerprintSql": "deploy/postgres/b64_table_fingerprint.sql",
    "catalogComparator":
        "deploy/postgres/b64_compare_catalog_fingerprints.py",
    "tableComparator": "deploy/postgres/b64_compare_table_fingerprints.py",
    "bootstrapRolesSql": "deploy/postgres/bootstrap_roles.sql",
    "prepareDatabaseSql": "deploy/postgres/prepare_database.sql",
    "runtimePrivilegesSql": "deploy/postgres/runtime_privileges.sql",
    "snapshotReaderProvisionSql":
        "deploy/postgres/provision_b64_snapshot_reader.sql",
    "snapshotReaderRollbackSql":
        "deploy/postgres/rollback_b64_snapshot_reader.sql",
    "snapshotReaderVerifier":
        "deploy/postgres/verify_b64_snapshot_reader.py",
    "snapshotReaderDeployRunner":
        "deploy/postgres/deploy_b64_snapshot_reader.py",
    "snapshotReaderHbaManifest":
        "deploy/postgres/b64_snapshot_reader_hba.v1.json",
    "snapshotReaderHbaDeployRunner":
        "deploy/postgres/deploy_b64_snapshot_reader_hba.py",
    "snapshotReaderRuntime":
        "deploy/postgres/b64_snapshot_reader_runtime.py",
}

KEYRING_SCHEMA = "b64-064a-evidence-keyring.v2"
ACCEPTANCE_SCHEMA = "b64-064a-rehearsal-evidence-acceptance.v1"
SIGNATURE_DOMAIN = b"OBSIDIAN\0B64_064A_REHEARSAL_EVIDENCE\0V1\0"
KEY_ID_DOMAIN = b"OBSIDIAN-B64-064A-EVIDENCE-KEY\0V1\0"
SIGNER_ROLES = {"ACCOUNTABLE_OWNER", "INDEPENDENT_REVIEWER"}
MAX_KEYRING_LIFETIME_SECONDS = 7 * 24 * 60 * 60
NON_AUTHORITY = {
    "readerLoginAuthorized": False,
    "credentialIssuanceAuthorized": False,
    "productionRefreshAuthorized": False,
    "productionMutationAuthorized": False,
    "migrationAuthorized": False,
    "moneyActionAuthorized": False,
    "automaticRetryAuthorized": False,
    "actionAllowed": False,
}


class SupervisorError(RuntimeError):
    """Closed reason code safe for journald and machine receipts."""


def _safe_reason(exc: BaseException) -> str:
    if (isinstance(exc, SupervisorError)
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "UNEXPECTED_DUMP_RESTORE_SUPERVISOR_FAILURE"


def _canonical(value: Any) -> bytes:
    def walk(item: Any) -> None:
        if item is None or type(item) in (str, int, bool):
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if isinstance(item, dict) and all(type(key) is str for key in item):
            for child in item.values():
                walk(child)
            return
        raise SupervisorError("NONCANONICAL_JSON_VALUE")

    walk(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _exact(value: Any, expected: Any) -> bool:
    """Compare closed evidence without Python's bool/int equality aliasing."""
    if expected is None or type(expected) in (str, int, bool):
        return type(value) is type(expected) and value == expected
    if isinstance(expected, list):
        return (type(value) is list and len(value) == len(expected)
                and all(_exact(item, wanted)
                        for item, wanted in zip(value, expected)))
    if isinstance(expected, dict):
        return (isinstance(value, Mapping) and set(value) == set(expected)
                and all(_exact(value[key], wanted)
                        for key, wanted in expected.items()))
    return False


def _digest(value: Any, code: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise SupervisorError(code)
    return value


def _token(value: Any, code: str, maximum: int = 128) -> str:
    if (type(value) is not str or not 1 <= len(value) <= maximum
            or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None):
        raise SupervisorError(code)
    return value


def _nonce(value: Any) -> str:
    token = _token(value, "INVALID_ACCEPTANCE_NONCE", maximum=96)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except BaseException as exc:
        raise SupervisorError("INVALID_ACCEPTANCE_NONCE") from exc
    if (len(raw) < 16
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != token):
        raise SupervisorError("INVALID_ACCEPTANCE_NONCE")
    return token


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SupervisorError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_json_pairs,
            parse_float=lambda _value: (_ for _ in ()).throw(
                SupervisorError("JSON_FLOAT_FORBIDDEN")
            ),
            parse_constant=lambda _value: (_ for _ in ()).throw(
                SupervisorError("JSON_CONSTANT_FORBIDDEN")
            ),
        )
    except SupervisorError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise SupervisorError("INVALID_JSON_ROOT")
    _canonical(value)
    return value


def _safe_read(root: Path, relative: str) -> bytes:
    """Read one root-owned non-writable regular file without symlink traversal."""
    if not root.is_absolute() or not relative or relative.startswith("/"):
        raise SupervisorError("UNSAFE_INPUT_PATH")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SupervisorError("UNSAFE_INPUT_PATH")
    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    directory_fd = os.open(root, directory_flags)
    opened: list[int] = [directory_fd]
    try:
        root_stat = os.fstat(directory_fd)
        if root_stat.st_uid != 0 or stat.S_IMODE(root_stat.st_mode) & 0o022:
            raise SupervisorError("UNSAFE_INPUT_ROOT")
        for part in parts[:-1]:
            directory_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            opened.append(directory_fd)
            current = os.fstat(directory_fd)
            if current.st_uid != 0 or stat.S_IMODE(current.st_mode) & 0o022:
                raise SupervisorError("UNSAFE_INPUT_PARENT")
        fd = os.open(parts[-1], file_flags, dir_fd=directory_fd)
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                    or metadata.st_nlink != 1
                    or stat.S_IMODE(metadata.st_mode) & 0o022
                    or not 1 <= metadata.st_size <= MAX_JSON_BYTES):
                raise SupervisorError("UNSAFE_INPUT_FILE")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    raise SupervisorError("SHORT_INPUT_READ")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(fd, 1):
                raise SupervisorError("INPUT_GREW_DURING_READ")
            post = os.fstat(fd)
            if ((post.st_dev, post.st_ino, post.st_size, post.st_mtime_ns)
                    != (metadata.st_dev, metadata.st_ino,
                        metadata.st_size, metadata.st_mtime_ns)):
                raise SupervisorError("INPUT_CHANGED_DURING_READ")
            return b"".join(chunks)
        finally:
            os.close(fd)
    finally:
        for opened_fd in reversed(opened):
            os.close(opened_fd)


def _artifact_closure_sha256(plan: Mapping[str, Any]) -> str:
    closure = [
        {"key": key, "path": ARTIFACT_PATHS[key],
         "sha256": plan["artifactsSha256"][key]}
        for key in sorted(ARTIFACT_PATHS)
    ]
    return _sha256(_canonical(closure))


def validate_exact_rehearsal(
    *, evidence_root: Path, rehearsal_root: Path,
) -> dict[str, Any]:
    evidence_raw = _safe_read(evidence_root, EVIDENCE_RELATIVE_PATH)
    if _sha256(evidence_raw) != EVIDENCE_SHA256:
        raise SupervisorError("REHEARSAL_EVIDENCE_DIGEST_MISMATCH")
    evidence = _decode_json(evidence_raw)
    if (evidence.get("schemaVersion") != EVIDENCE_SCHEMA
            or evidence.get("route") != ["E0", "E0.3", "B5.3", "064A"]
            or evidence.get("status")
            != "VERIFIED_DISPOSABLE_DORMANT_DEPLOY_ALLOWED"
            or evidence.get("productionActivationStatus")
            != "BLOCKED_NAMED_PREREQUISITES"):
        raise SupervisorError("REHEARSAL_EVIDENCE_STATUS_MISMATCH")
    plan_binding = evidence.get("artifacts", {}).get("frozenPlan", {})
    if (plan_binding != {"path": PLAN_RELATIVE_PATH,
                         "sha256": REHEARSAL_PLAN_SHA256}):
        raise SupervisorError("REHEARSAL_PLAN_BINDING_MISMATCH")
    rehearsal = evidence.get("rehearsal")
    if (not isinstance(rehearsal, Mapping)
            or rehearsal.get("result")
            != "PostgreSQL B64 short-lived two-FD exported snapshot lifecycle: OK"
            or any(rehearsal.get(key) is not True for key in (
                "realPgDump", "exportedSnapshotUsed", "pgRestoreListValidated",
                "anonymousArchive", "hbaRolledBack", "containerAbsentAfter",
                "volumeAbsentAfter", "oneShotDumpContainerAbsentAfter",
                "helperProcessesAbsentAfter",
            ))
            or any(rehearsal.get(key) is not False for key in (
                "customerRowsRead", "credentialExposed",
            ))):
        raise SupervisorError("REHEARSAL_RESULT_MISMATCH")
    observation = evidence.get("productionObservation")
    if (not isinstance(observation, Mapping)
            or observation.get("readerRoleLoginState") != "DISABLED"
            or observation.get("readerCredentialState") != "ABSENT"
            or observation.get("readerActiveSessions") != 0
            or observation.get("hbaIsolationStatus") != "EXACT"
            or any(observation.get(key) is not False for key in (
                "databaseMutation", "hbaMutation", "serviceRestartOrReload",
            ))):
        raise SupervisorError("REHEARSAL_PRODUCTION_OBSERVATION_MISMATCH")
    plan_raw = _safe_read(rehearsal_root, PLAN_RELATIVE_PATH)
    if _sha256(plan_raw) != REHEARSAL_PLAN_SHA256:
        raise SupervisorError("REHEARSAL_PLAN_DIGEST_MISMATCH")
    plan = _decode_json(plan_raw)
    try:
        refresh.validate_plan(plan)
    except BaseException as exc:
        raise SupervisorError("REHEARSAL_PLAN_VALIDATION_FAILED") from exc
    if set(plan.get("artifactsSha256", {})) != set(ARTIFACT_PATHS):
        raise SupervisorError("REHEARSAL_ARTIFACT_SET_MISMATCH")
    for key, relative in ARTIFACT_PATHS.items():
        artifact_raw = _safe_read(rehearsal_root, relative)
        if _sha256(artifact_raw) != plan["artifactsSha256"][key]:
            raise SupervisorError("REHEARSAL_ARTIFACT_DIGEST_MISMATCH")
    evidence_artifacts = evidence.get("artifacts", {})
    for evidence_key, plan_key in (
        ("runner", "runner"), ("runtime", "snapshotReaderRuntime"),
    ):
        if evidence_artifacts.get(evidence_key, {}).get("sha256") \
                != plan["artifactsSha256"][plan_key]:
            raise SupervisorError("REHEARSAL_EVIDENCE_ARTIFACT_MISMATCH")
    return {
        "evidenceSha256": EVIDENCE_SHA256,
        "planSha256": REHEARSAL_PLAN_SHA256,
        "artifactClosureSha256": _artifact_closure_sha256(plan),
        "artifactCount": len(ARTIFACT_PATHS),
        "rehearsalReleaseCommit": REHEARSAL_RELEASE_COMMIT,
        "plan": plan,
    }


def _decode_public_key(value: Any) -> bytes:
    token = _token(value, "INVALID_PUBLIC_KEY", maximum=64)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except BaseException as exc:
        raise SupervisorError("INVALID_PUBLIC_KEY") from exc
    if (len(raw) != 32
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != token):
        raise SupervisorError("INVALID_PUBLIC_KEY")
    return raw


def _decode_signature(value: Any) -> bytes:
    token = _token(value, "INVALID_SIGNATURE", maximum=96)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except BaseException as exc:
        raise SupervisorError("INVALID_SIGNATURE") from exc
    if (len(raw) != 64
            or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != token):
        raise SupervisorError("INVALID_SIGNATURE")
    return raw


def _key_id(public_key: bytes) -> str:
    return "b64e_" + _sha256(KEY_ID_DOMAIN + public_key)


def verify_authenticated_acceptance(
    *, keyring_raw: bytes, acceptance_raw: bytes,
    expected_keyring_sha256: str, exact: Mapping[str, Any], now_epoch: int,
) -> dict[str, Any]:
    """Verify independent signatures accepting evidence only, never activation."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise SupervisorError("ED25519_VERIFIER_UNAVAILABLE") from exc
    keyring = _decode_json(keyring_raw)
    if set(keyring) != {
        "schemaVersion", "route", "trustEnvironment", "registryVersion",
        "issuedAtEpoch", "expiresAtEpoch", "revokedKeys", "keys",
        "keyringSha256",
    } or keyring.get("schemaVersion") != KEYRING_SCHEMA \
            or keyring.get("route") != ROUTE \
            or keyring.get("trustEnvironment") != "PRODUCTION_AUTHENTICATED":
        raise SupervisorError("INVALID_EVIDENCE_KEYRING")
    unsigned_keyring = {key: keyring[key] for key in (
        "schemaVersion", "route", "trustEnvironment", "registryVersion",
        "issuedAtEpoch", "expiresAtEpoch", "revokedKeys", "keys",
    )}
    keyring_sha = _sha256(_canonical(unsigned_keyring))
    if (_digest(keyring.get("keyringSha256"), "INVALID_KEYRING_DIGEST")
            != keyring_sha
            or _digest(expected_keyring_sha256, "INVALID_EXPECTED_KEYRING_DIGEST")
            != keyring_sha):
        raise SupervisorError("EVIDENCE_KEYRING_DIGEST_MISMATCH")
    registry_version = keyring.get("registryVersion")
    keyring_issued = keyring.get("issuedAtEpoch")
    keyring_expires = keyring.get("expiresAtEpoch")
    if (type(registry_version) is not int or registry_version <= 0
            or type(keyring_issued) is not int
            or type(keyring_expires) is not int or keyring_issued <= 0
            or not keyring_issued < keyring_expires
            <= keyring_issued + MAX_KEYRING_LIFETIME_SECONDS
            or keyring_issued > now_epoch + MAX_FUTURE_SKEW_SECONDS
            or not keyring_issued <= now_epoch < keyring_expires):
        raise SupervisorError("EVIDENCE_KEYRING_TIME_INVALID")
    revoked_keys = keyring.get("revokedKeys")
    if type(revoked_keys) is not list or len(revoked_keys) > 64:
        raise SupervisorError("INVALID_EVIDENCE_REVOCATIONS")
    revoked_ids: set[str] = set()
    for revocation in revoked_keys:
        if (not isinstance(revocation, Mapping) or set(revocation) != {
                "keyId", "revokedAtEpoch", "reasonCode",
        }):
            raise SupervisorError("INVALID_EVIDENCE_REVOCATION")
        revoked_id = _token(
            revocation.get("keyId"), "INVALID_REVOKED_KEY_ID",
        )
        revoked_at = revocation.get("revokedAtEpoch")
        _token(revocation.get("reasonCode"), "INVALID_REVOCATION_REASON")
        if (revoked_id in revoked_ids or type(revoked_at) is not int
                or revoked_at <= 0
                or revoked_at > now_epoch + MAX_FUTURE_SKEW_SECONDS):
            raise SupervisorError("INVALID_EVIDENCE_REVOCATION")
        revoked_ids.add(revoked_id)
    keys = keyring.get("keys")
    if type(keys) is not list or len(keys) != 2:
        raise SupervisorError("INVALID_EVIDENCE_KEYRING")
    registry: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    domains: set[str] = set()
    public_keys: set[bytes] = set()
    for entry in keys:
        if (not isinstance(entry, Mapping) or set(entry) != {
                "keyId", "identityId", "trustDomain", "role", "status",
                "publicKeyB64",
        }):
            raise SupervisorError("INVALID_EVIDENCE_KEY")
        key_id = _token(entry.get("keyId"), "INVALID_KEY_ID")
        identity = _token(entry.get("identityId"), "INVALID_IDENTITY_ID")
        domain = _token(entry.get("trustDomain"), "INVALID_TRUST_DOMAIN")
        public_key = _decode_public_key(entry.get("publicKeyB64"))
        if (key_id != _key_id(public_key)
                or key_id in registry or key_id in revoked_ids
                or identity in identities or domain in domains
                or public_key in public_keys
                or entry.get("role") not in SIGNER_ROLES
                or entry.get("status") != "ACTIVE"):
            raise SupervisorError("EVIDENCE_SIGNERS_NOT_INDEPENDENT")
        registry[key_id] = dict(entry)
        identities.add(identity)
        domains.add(domain)
        public_keys.add(public_key)
    if {entry["role"] for entry in keys} != SIGNER_ROLES:
        raise SupervisorError("EVIDENCE_SIGNER_ROLES_MISMATCH")

    acceptance = _decode_json(acceptance_raw)
    expected_keys = {
        "schemaVersion", "route", "decision", "evidenceSha256",
        "planSha256", "artifactClosureSha256", "keyringSha256",
        "issuedAtEpoch", "expiresAtEpoch", "nonce", "authority",
        "acceptanceSha256", "signatures",
    }
    if not isinstance(acceptance, Mapping) or set(acceptance) != expected_keys:
        raise SupervisorError("INVALID_EVIDENCE_ACCEPTANCE")
    unsigned = {key: acceptance[key] for key in (
        "schemaVersion", "route", "decision", "evidenceSha256",
        "planSha256", "artifactClosureSha256", "keyringSha256",
        "issuedAtEpoch", "expiresAtEpoch", "nonce", "authority",
    )}
    if (unsigned["schemaVersion"] != ACCEPTANCE_SCHEMA
            or unsigned["route"] != ROUTE
            or unsigned["decision"]
            != "ACCEPT_EXACT_DISPOSABLE_REHEARSAL_EVIDENCE_ONLY"
            or unsigned["evidenceSha256"] != exact["evidenceSha256"]
            or unsigned["planSha256"] != exact["planSha256"]
            or unsigned["artifactClosureSha256"]
            != exact["artifactClosureSha256"]
            or unsigned["keyringSha256"] != keyring_sha
            or not _exact(unsigned["authority"], NON_AUTHORITY)):
        raise SupervisorError("EVIDENCE_ACCEPTANCE_BINDING_MISMATCH")
    issued = unsigned["issuedAtEpoch"]
    expires = unsigned["expiresAtEpoch"]
    if (type(now_epoch) is not int or type(issued) is not int
            or type(expires) is not int or issued <= 0
            or not issued < expires <= issued + MAX_ACCEPTANCE_LIFETIME_SECONDS
            or issued > now_epoch + MAX_FUTURE_SKEW_SECONDS
            or not issued <= now_epoch < expires):
        raise SupervisorError("EVIDENCE_ACCEPTANCE_TIME_INVALID")
    _nonce(unsigned["nonce"])
    acceptance_sha = _sha256(_canonical(unsigned))
    if acceptance.get("acceptanceSha256") != acceptance_sha:
        raise SupervisorError("EVIDENCE_ACCEPTANCE_DIGEST_MISMATCH")
    signatures = acceptance.get("signatures")
    if type(signatures) is not list or len(signatures) != 2:
        raise SupervisorError("INVALID_EVIDENCE_SIGNATURE_SET")
    seen_roles: set[str] = set()
    seen_keys: set[str] = set()
    for signature in signatures:
        if not isinstance(signature, Mapping) or set(signature) != {
                "role", "keyId", "identityId", "signatureB64",
        }:
            raise SupervisorError("INVALID_EVIDENCE_SIGNATURE")
        role = signature.get("role")
        key_id = signature.get("keyId")
        key = registry.get(key_id)
        if (role not in SIGNER_ROLES or role in seen_roles or key_id in seen_keys
                or key is None or key["role"] != role
                or key["identityId"] != signature.get("identityId")):
            raise SupervisorError("EVIDENCE_SIGNATURE_BINDING_MISMATCH")
        try:
            Ed25519PublicKey.from_public_bytes(
                _decode_public_key(key["publicKeyB64"])
            ).verify(
                _decode_signature(signature.get("signatureB64")),
                SIGNATURE_DOMAIN + _canonical(unsigned),
            )
        except SupervisorError:
            raise
        except BaseException as exc:
            raise SupervisorError("EVIDENCE_SIGNATURE_INVALID") from exc
        seen_roles.add(role)
        seen_keys.add(key_id)
    if seen_roles != SIGNER_ROLES:
        raise SupervisorError("EVIDENCE_SIGNER_ROLES_MISMATCH")
    return {
        "status": "AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED",
        "acceptanceSha256": acceptance_sha,
        "keyringSha256": keyring_sha,
        "keyringRegistryVersion": registry_version,
        "revocationSnapshotChecked": True,
        "signerRoles": sorted(seen_roles),
        "readerActivationAuthorized": False,
        "productionRefreshAuthorized": False,
        "actionAllowed": False,
    }


def _run_json(command: Sequence[str], *, timeout: int) -> dict[str, Any]:
    environment = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C",
        "PYTHONPATH": "",
    }
    completed = subprocess.run(
        list(command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=timeout,
        env=environment,
    )
    if completed.returncode != 0 or completed.stderr:
        raise SupervisorError("DORMANT_WATCHDOG_PREFLIGHT_FAILED")
    try:
        value = json.loads(completed.stdout.decode("utf-8"))
    except BaseException as exc:
        raise SupervisorError("DORMANT_WATCHDOG_OUTPUT_INVALID") from exc
    if not isinstance(value, dict):
        raise SupervisorError("DORMANT_WATCHDOG_OUTPUT_INVALID")
    return value


def _trusted_now_epoch() -> tuple[int, dict[str, Any]]:
    """Use the production systemd-synchronized UTC clock as bounded time."""
    marker_path = Path("/run/systemd/timesync/synchronized")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        marker_fd = os.open(marker_path, flags)
    except OSError as exc:
        raise SupervisorError("TRUSTED_TIME_SYNC_MARKER_ABSENT") from exc
    try:
        marker = os.fstat(marker_fd)
        if (not stat.S_ISREG(marker.st_mode) or marker.st_size != 0
                or stat.S_IMODE(marker.st_mode) & 0o022):
            raise SupervisorError("TRUSTED_TIME_SYNC_MARKER_UNSAFE")
    finally:
        os.close(marker_fd)
    before = time.time()
    completed = subprocess.run(
        ["/usr/bin/timedatectl", "show", "--property=NTPSynchronized",
         "--property=Timezone"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False, timeout=5,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    after = time.time()
    if completed.returncode != 0 or completed.stderr or after < before \
            or after - before > 5:
        raise SupervisorError("TRUSTED_TIME_STATUS_UNAVAILABLE")
    try:
        properties = dict(
            line.split("=", 1)
            for line in completed.stdout.decode("ascii").splitlines()
            if "=" in line
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise SupervisorError("TRUSTED_TIME_STATUS_INVALID") from exc
    if properties != {"Timezone": "Etc/UTC", "NTPSynchronized": "yes"}:
        raise SupervisorError("TRUSTED_TIME_NOT_SYNCHRONIZED_UTC")
    observed = int((before + after) / 2)
    if marker.st_mtime > after + MAX_FUTURE_SKEW_SECONDS:
        raise SupervisorError("TRUSTED_TIME_SYNC_MARKER_FROM_FUTURE")
    return observed, {
        "source": "SYSTEMD_TIMESYNCD_SYNCHRONIZED_UTC",
        "ntpSynchronized": True,
        "timezone": "Etc/UTC",
        "syncMarkerMtimeEpoch": int(marker.st_mtime),
        "observedAtEpoch": observed,
    }


def production_preflight(
    *, evidence_root: Path, rehearsal_root: Path, runtime_root: Path,
    keyring_relative: str | None = None,
    acceptance_relative: str | None = None,
    authentication_root: Path | None = None,
    expected_keyring_sha256: str | None = None,
    now_epoch: int | None = None,
) -> dict[str, Any]:
    exact = validate_exact_rehearsal(
        evidence_root=evidence_root, rehearsal_root=rehearsal_root,
    )
    if now_epoch is None:
        trusted_now, trusted_time = _trusted_now_epoch()
    else:
        if type(now_epoch) is not int:
            raise SupervisorError("INVALID_INJECTED_TRUSTED_TIME")
        trusted_now = now_epoch
        trusted_time = {
            "source": "INJECTED_TEST_CLOCK", "ntpSynchronized": None,
            "timezone": "Etc/UTC", "syncMarkerMtimeEpoch": None,
            "observedAtEpoch": trusted_now,
        }
    plan = exact.pop("plan")
    version = subprocess.run(
        refresh.compile_client_preflight(plan), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=30,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    if (version.returncode != 0 or version.stderr
            or version.stdout.decode("utf-8", "strict").strip()
            != refresh.PG_DUMP_VERSION):
        raise SupervisorError("PINNED_CLIENT_PREFLIGHT_FAILED")
    watchdog_path = runtime_root / \
        "deploy/postgres/b64_snapshot_reader_watchdog.py"
    python_path = runtime_root / "relay-venv/bin/python"
    if not python_path.exists():
        python_path = Path("/opt/obsidian-exchange/relay-venv/bin/python")
    watchdog = _run_json([
        str(python_path), str(watchdog_path),
        "--expected-image-id", PRODUCTION_IMAGE_ID,
        "--expected-server-version-num", str(PRODUCTION_SERVER_VERSION_NUM),
        "--require-dormant",
    ], timeout=30)
    if (watchdog.get("status") != "DORMANT_VERIFIED"
            or watchdog.get("roleLoginState") != "DISABLED"
            or watchdog.get("credentialState") != "ABSENT"
            or watchdog.get("authorityIncreased") is not False
            or watchdog.get("customerRowsRead") is not False
            or watchdog.get("serverVersionNum") != PRODUCTION_SERVER_VERSION_NUM
            or watchdog.get("container", {}).get("imageId")
            != PRODUCTION_IMAGE_ID):
        raise SupervisorError("PRODUCTION_DORMANT_STATE_MISMATCH")

    blockers: list[str] = []
    authentication: dict[str, Any] | None = None
    auth_inputs = (
        authentication_root, keyring_relative, acceptance_relative,
        expected_keyring_sha256,
    )
    if all(item is None for item in auth_inputs):
        blockers.append("AUTHENTICATED_REHEARSAL_EVIDENCE_ABSENT")
    elif any(item is None for item in auth_inputs):
        raise SupervisorError("INCOMPLETE_AUTHENTICATION_INPUTS")
    else:
        assert authentication_root is not None
        assert keyring_relative is not None
        assert acceptance_relative is not None
        assert expected_keyring_sha256 is not None
        authentication = verify_authenticated_acceptance(
            keyring_raw=_safe_read(authentication_root, keyring_relative),
            acceptance_raw=_safe_read(authentication_root, acceptance_relative),
            expected_keyring_sha256=expected_keyring_sha256,
            exact=exact, now_epoch=trusted_now,
        )
    blockers.append("PRODUCTION_READER_ACTIVATION_SEPARATELY_AUTHORIZED_FALSE")
    authenticated = authentication is not None
    return {
        "schemaVersion": "b64-064a-dump-restore-supervisor-preflight.v1",
        "route": ROUTE,
        "status": (
            "DORMANT_SUPERVISOR_VERIFIED_AUTHENTICATED_EVIDENCE"
            if authenticated else "DORMANT_SUPERVISOR_VERIFIED_AUTH_PENDING"
        ),
        "exactRehearsal": exact,
        "authenticatedEvidence": authentication,
        "trustedTime": trusted_time,
        "production": {
            "watchdogStatus": "DORMANT_VERIFIED",
            "containerId": watchdog["container"]["containerId"],
            "imageId": watchdog["container"]["imageId"],
            "serverVersionNum": watchdog["serverVersionNum"],
            "readerLoginState": "DISABLED",
            "readerCredentialState": "ABSENT",
            "customerRowsRead": False,
            "productionMutation": False,
        },
        "supervisor": {
            "deployedMode": "DORMANT_PREFLIGHT_ONLY",
            "pinnedClientVersion": refresh.PG_DUMP_VERSION,
            "dumpRestoreExecutionEntrypointPresent": False,
            "credentialIssuerInvoked": False,
            "dumpInvoked": False,
            "restoreInvoked": False,
        },
        "blockers": blockers,
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--rehearsal-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path,
                        default=Path("/opt/obsidian-exchange"))
    parser.add_argument("--authentication-root", type=Path)
    parser.add_argument("--keyring-relative")
    parser.add_argument("--acceptance-relative")
    parser.add_argument("--expected-keyring-sha256")
    parser.add_argument("--require-authenticated-evidence", action="store_true")
    args = parser.parse_args()
    try:
        receipt = production_preflight(
            evidence_root=args.evidence_root,
            rehearsal_root=args.rehearsal_root,
            runtime_root=args.runtime_root,
            authentication_root=args.authentication_root,
            keyring_relative=args.keyring_relative,
            acceptance_relative=args.acceptance_relative,
            expected_keyring_sha256=args.expected_keyring_sha256,
        )
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        if (args.require_authenticated_evidence
                and receipt["authenticatedEvidence"] is None):
            return 1
        return 0
    except BaseException as exc:
        print(json.dumps({
            "schemaVersion": "b64-064a-dump-restore-supervisor-preflight.v1",
            "route": ROUTE, "status": "NO_GO", "reason": _safe_reason(exc),
            "automaticRetryAllowed": False, "actionAllowed": False,
        }, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.exit(main())
