#!/usr/bin/env python3
"""Fail-closed one-shot authorization boundary for a future 064A refresh.

This module deliberately separates evidence acceptance from production
activation.  An activation decision uses a distinct schema and Ed25519 domain,
binds one exact target/plan/limit set, and is consumed through a durable atomic
journal.  The generic runner requires an injected executor and reconciler so
the decision/replay state machine can be rehearsed without making production
contact.  No production executor is registered by this CLI.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

import b64_dump_restore_supervisor as supervisor


ROUTE = supervisor.ROUTE
PLAN_SCHEMA = "b64-064a-production-activation-plan.v2"
DECISION_SCHEMA = "b64-064a-production-activation-decision.v2"
EXECUTION_RECEIPT_SCHEMA = "b64-064a-production-activation-receipt.v2"
JOURNAL_SCHEMA = "b64-064a-production-activation-journal.v2"
EFFECTIVE_PLAN_SCHEMA = "b64-064a-production-effective-plan.v1"
SIGNATURE_DOMAIN = b"OBSIDIAN\0B64_064A_PRODUCTION_ACTIVATION\0V2\0"
ACTIVATION_KEYRING_SCHEMA = "b64-064a-activation-keyring.v1"
ACTIVATION_TRUST_ENVIRONMENT = "PRODUCTION_ACTIVATION_AUTHENTICATED"
ACTIVATION_KEY_ID_DOMAIN = b"OBSIDIAN-B64-064A-ACTIVATION-KEY\0V1\0"
MAX_DECISION_LIFETIME_SECONDS = 15 * 60
MAX_PLAN_AGE_SECONDS = 15 * 60
MAX_FUTURE_SKEW_SECONDS = 60
LEGACY_ACCEPTED_REHEARSAL_PLAN_SHA256 = \
    "14d38a9fc0cc7c78014d16230553359939aad7d7a15abaf7c7cc8672c3c8d0c6"
HARDENED_PLAN_RAW_SHA256 = \
    "6740ef78c396e86c7f4e66cb33cd225e7d3eac0b31c01bebd5ca4b35794c8d02"
EVIDENCE_ACCEPTANCE_SHA256 = \
    "b482504a2166b1e410e6a4b97829dbfcf818807b872f6ca73530a6d130dd54ba"
PRODUCTION_CONTAINER = "obsidian-postgres"
CONTRACT_CONTAINER_PATTERN = r"b64-hba-contract-[0-9]+"
PRODUCTION_IMAGE_ID = supervisor.PRODUCTION_IMAGE_ID
PRODUCTION_SYSTEM_IDENTIFIER = "7672203973020184609"
PRODUCTION_INTERLOCK_PATH = Path(
    "/run/lock/obsidian-b64-production-activation.lock"
)
PRODUCTION_ACTIVATION_ROOT = Path(
    "/var/lib/obsidian-exchange/b64-064a-activation"
)
PRODUCTION_JOURNAL_ROOT = PRODUCTION_ACTIVATION_ROOT / "journal"
PRODUCTION_RESOURCE_JOURNAL_ROOT = PRODUCTION_ACTIVATION_ROOT / "resources"
PRODUCTION_WORKSPACE_ROOT = PRODUCTION_ACTIVATION_ROOT / "workspace"
PRODUCTION_PROXY_ROOT = PRODUCTION_ACTIVATION_ROOT / "proxy"
SIGNER_ROLES = supervisor.SIGNER_ROLES
ARTIFACT_KEYS = {
    "activationEntrypoint", "activationExecutor", "hardenedRefresh",
    "snapshotReaderRuntime",
    "dumpRestoreSupervisor", "hardenedPlanRaw",
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_PATHS = {
    "activationEntrypoint": Path(__file__).resolve(),
    "activationExecutor": Path(__file__).with_name(
        "b64_064a_activation_executor.py"
    ),
    "hardenedRefresh": Path(__file__).with_name(
        "b64_064a_hardened_refresh.py"
    ),
    "snapshotReaderRuntime": Path(__file__).with_name(
        "b64_snapshot_reader_runtime.py"
    ),
    "dumpRestoreSupervisor": Path(__file__).with_name(
        "b64_dump_restore_supervisor.py"
    ),
    "hardenedPlanRaw": PROJECT_ROOT
    / "docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json",
}

_VERIFIED_ACTIVATION_SEAL = object()
_VERIFIED_RECOVERY_SEAL = object()


class _ExecutionCapabilityState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._execution_started = False
        self._lease_claimed = False

    def begin_execution(self) -> None:
        with self._lock:
            if self._execution_started:
                raise ActivationError(
                    "ACTIVATION_EXECUTION_CAPABILITY_REUSED"
                )
            self._execution_started = True

    def claim_lease(self) -> None:
        with self._lock:
            if not self._execution_started or self._lease_claimed:
                raise ActivationError(
                    "ACTIVATION_LEASE_CAPABILITY_INVALID"
                )
            self._lease_claimed = True

    @property
    def execution_started(self) -> bool:
        with self._lock:
            return self._execution_started

LIMITS = {
    "maximumRuns": 1,
    "credentialTtlSeconds": 180,
    "workDeadlineSeconds": 150,
    "cleanupReserveSeconds": 30,
    "overallDeadlineSeconds": 180,
    "maximumArchiveBytes": 16 * 1024 * 1024,
    "disposableRestoreRequired": True,
    "catalogEqualityRequired": True,
    "tableEqualityRequired": True,
    "postCloseDormantRequired": True,
    "automaticRetryAllowed": False,
}

CLOSE_REQUIREMENTS = {
    "credentialRevoked": True,
    "readerLoginDisabled": True,
    "readerCredentialAbsent": True,
    "readerSessionsZero": True,
    "sourceSessionClosed": True,
    "registeredWorkspaceAbsent": True,
    "dumpContainerAbsent": True,
    "restoreContainerAbsent": True,
    "containerTmpfsLifetimesEnded": True,
    "ambiguousOutcomeRequiresHold": True,
}

EXECUTION_PROFILE = {
    "sourceFingerprintPrincipal": "obsidian_b64_snapshot_reader",
    "sourceFingerprintInsideExportedSnapshot": True,
    "dumpNetwork": "NONE_WITH_EXACT_UNIX_PROXY",
    "proxyTarget": "127.0.0.1:5432_IN_ATTESTED_SOURCE_NETNS",
    "dumpEgressIsolated": True,
    "ambientDockerConfigurationAllowed": False,
    "freshActivationNonceOnEveryRuntimeResource": True,
    "outerWorkDeadlinePropagated": True,
    "durableExecutorResourceJournalRequired": True,
}

EFFECTIVE_EXECUTION = {
    "dumpNetwork": "NONE_WITH_EXACT_UNIX_PROXY",
    "dumpDatabaseEndpoint": "/run/b64/proxy/.s.PGSQL.5432",
    "proxyTarget": "127.0.0.1:5432_IN_ATTESTED_SOURCE_NETNS",
    "dumpContainerSharesSourceNetworkNamespace": False,
    "dumpEgressIsolated": True,
    "abnormalExitRecovery": "CLEANUP_ONLY_NO_EXECUTE_OR_LEASE",
    "automaticRetryAllowed": False,
}

PRODUCTION_AUTHORITY = {
    "environment": "PRODUCTION",
    "productionContactAuthorized": True,
    "readerLoginAuthorized": True,
    "credentialIssuanceAuthorized": True,
    "roleAuthenticationMutationAuthorized": True,
    "boundedDatabaseReadAuthorized": True,
    "productionRefreshAuthorized": True,
    "productionDatabaseDataMutationAuthorized": False,
    "disposableRestoreAuthorized": True,
    "migrationAuthorized": False,
    "moneyActionAuthorized": False,
    "telegramDeliveryAuthorized": False,
    "ambiguousSendingDispositionAuthorized": False,
    "automaticRetryAuthorized": False,
    "e4ExecutionAuthorized": False,
    "boundedActivationAllowed": True,
}

CONTRACT_AUTHORITY = {
    **PRODUCTION_AUTHORITY,
    "environment": "DISPOSABLE_CONTRACT",
    "productionContactAuthorized": False,
    "productionRefreshAuthorized": False,
}


class ActivationError(RuntimeError):
    """Closed reason code safe for secret-free receipts."""


def _reason(exc: BaseException) -> str:
    if (isinstance(exc, ActivationError)
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "UNEXPECTED_ACTIVATION_FAILURE"


def _canonical(value: Any) -> bytes:
    try:
        return supervisor._canonical(value)
    except supervisor.SupervisorError as exc:
        raise ActivationError(str(exc)) from exc


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def activation_key_id(public_key: bytes) -> str:
    if type(public_key) is not bytes or len(public_key) != 32:
        raise ActivationError("INVALID_ACTIVATION_PUBLIC_KEY")
    return "b64a_" + _sha(ACTIVATION_KEY_ID_DOMAIN + public_key)


def _exact(value: Any, expected: Any) -> bool:
    try:
        return supervisor._exact(value, expected)
    except BaseException:
        return False


def _digest(value: Any, code: str) -> str:
    try:
        return supervisor._digest(value, code)
    except supervisor.SupervisorError as exc:
        raise ActivationError(str(exc)) from exc


def _token(value: Any, code: str, *, minimum: int = 1,
           maximum: int = 128) -> str:
    if (type(value) is not str or not minimum <= len(value) <= maximum
            or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None):
        raise ActivationError(code)
    return value


def _container_id(value: Any, code: str) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ActivationError(code)
    return value


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        value = supervisor._decode_json(raw)
    except supervisor.SupervisorError as exc:
        raise ActivationError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ActivationError("INVALID_JSON_ROOT")
    return value


def _artifact_bytes_and_sha256(path: Path) -> tuple[bytes, str]:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise ActivationError("ACTIVATION_ARTIFACT_UNSAFE") from exc
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    size = 0
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or metadata.st_nlink != 1
                or not 1 <= metadata.st_size <= 2 * 1024 * 1024):
            raise ActivationError("ACTIVATION_ARTIFACT_UNSAFE")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > metadata.st_size:
                raise ActivationError("ACTIVATION_ARTIFACT_CHANGED")
            digest.update(chunk)
            chunks.append(chunk)
        if size != metadata.st_size:
            raise ActivationError("ACTIVATION_ARTIFACT_CHANGED")
    finally:
        os.close(descriptor)
    return b"".join(chunks), digest.hexdigest()


def verify_artifact_closure(plan: Mapping[str, Any]) -> None:
    artifacts = plan.get("artifactsSha256")
    if not isinstance(artifacts, Mapping) or set(artifacts) != ARTIFACT_KEYS:
        raise ActivationError("INVALID_ACTIVATION_ARTIFACT_SET")
    observed: dict[str, bytes] = {}
    for key, path in ARTIFACT_PATHS.items():
        raw, digest = _artifact_bytes_and_sha256(path)
        if digest != artifacts[key]:
            raise ActivationError("ACTIVATION_ARTIFACT_DRIFT")
        observed[key] = raw
    hardened_plan = _decode_json(observed["hardenedPlanRaw"])
    if (hardened_plan.get("schemaVersion")
            != "b64-064a-hardened-refresh-plan.v1"
            or hardened_plan.get("route") != ROUTE):
        raise ActivationError("HARDENED_PLAN_BINDING_MISMATCH")


def derive_execution_plan(
    *, run_nonce: str, artifacts_sha256: Mapping[str, str],
) -> dict[str, Any]:
    _token(run_nonce, "INVALID_RUN_NONCE", minimum=16, maximum=64)
    if set(artifacts_sha256) != ARTIFACT_KEYS:
        raise ActivationError("INVALID_ACTIVATION_ARTIFACT_SET")
    raw, digest = _artifact_bytes_and_sha256(ARTIFACT_PATHS["hardenedPlanRaw"])
    if digest != HARDENED_PLAN_RAW_SHA256:
        raise ActivationError("HARDENED_PLAN_BINDING_MISMATCH")
    compatibility_plan = _decode_json(raw)
    compatibility_plan["runNonce"] = run_nonce
    plan_artifacts = compatibility_plan.get("artifactsSha256")
    if not isinstance(plan_artifacts, dict):
        raise ActivationError("HARDENED_PLAN_BINDING_MISMATCH")
    plan_artifacts["runner"] = _digest(
        artifacts_sha256["hardenedRefresh"], "INVALID_ARTIFACT_DIGEST"
    )
    plan_artifacts["snapshotReaderRuntime"] = _digest(
        artifacts_sha256["snapshotReaderRuntime"],
        "INVALID_ARTIFACT_DIGEST",
    )
    effective_plan = json.loads(_canonical(compatibility_plan))
    effective_plan["schemaVersion"] = \
        "b64-064a-effective-hardened-refresh-plan.v1"
    effective_plan["client"]["networkForDump"] = "none"
    effective_plan["client"]["sourceNetworkNamespaceShared"] = False
    effective_plan["client"]["egressIsolationProven"] = True
    effective_plan["credentials"][
        "reconcileOnAbnormalSupervisorExit"
    ] = True
    effective_plan["effectiveExecution"] = dict(EFFECTIVE_EXECUTION)
    value = {
        "schemaVersion": EFFECTIVE_PLAN_SCHEMA,
        "route": ROUTE,
        "runNonce": run_nonce,
        "compatibilityHardenedPlanSha256": _sha(
            _canonical(compatibility_plan)
        ),
        "effectivePlan": effective_plan,
    }
    return validate_effective_execution_plan(value)


def validate_effective_execution_plan(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
            "schemaVersion", "route", "runNonce",
            "compatibilityHardenedPlanSha256",
            "effectivePlan"}:
        raise ActivationError("INVALID_EFFECTIVE_EXECUTION_PLAN")
    run_nonce = _token(
        value.get("runNonce"), "INVALID_RUN_NONCE", minimum=16,
        maximum=64,
    )
    effective = value.get("effectivePlan")
    if (value.get("schemaVersion") != EFFECTIVE_PLAN_SCHEMA
            or value.get("route") != ROUTE
            or not isinstance(effective, Mapping)
            or effective.get("schemaVersion")
            != "b64-064a-effective-hardened-refresh-plan.v1"
            or effective.get("route") != ROUTE
            or effective.get("runNonce") != run_nonce
            or not isinstance(
                effective.get("artifactsSha256"), Mapping
            )):
        raise ActivationError("INVALID_EFFECTIVE_EXECUTION_PLAN")
    client = effective.get("client")
    credentials = effective.get("credentials")
    if (not isinstance(client, Mapping)
            or client.get("networkForDump") != "none"
            or client.get("sourceNetworkNamespaceShared") is not False
            or client.get("egressIsolationProven") is not True
            or not isinstance(credentials, Mapping)
            or credentials.get("reconcileOnAbnormalSupervisorExit")
            is not True
            or not _exact(effective.get("effectiveExecution"),
                          EFFECTIVE_EXECUTION)):
        raise ActivationError("INVALID_EFFECTIVE_EXECUTION_PLAN")
    compatibility = _project_compatibility_hardened_plan(effective)
    if _digest(
            value.get("compatibilityHardenedPlanSha256"),
            "INVALID_COMPATIBILITY_PLAN_DIGEST",
            ) != _sha(_canonical(compatibility)):
        raise ActivationError("INVALID_EFFECTIVE_EXECUTION_PLAN")
    return json.loads(_canonical(dict(value)))


def _project_compatibility_hardened_plan(
    effective_plan: Mapping[str, Any],
) -> dict[str, Any]:
    compatibility = json.loads(_canonical(dict(effective_plan)))
    compatibility.pop("effectiveExecution", None)
    compatibility["schemaVersion"] = \
        "b64-064a-hardened-refresh-plan.v1"
    compatibility["client"]["networkForDump"] = \
        "container:ATTESTED_SOURCE_CONTAINER_ID"
    compatibility["client"]["sourceNetworkNamespaceShared"] = True
    compatibility["client"]["egressIsolationProven"] = False
    compatibility["credentials"][
        "reconcileOnAbnormalSupervisorExit"
    ] = False
    return compatibility


def compatibility_hardened_plan(
    effective_plan: Mapping[str, Any],
) -> dict[str, Any]:
    checked = validate_effective_execution_plan(effective_plan)
    return _project_compatibility_hardened_plan(checked["effectivePlan"])


def _load_keyring(
    keyring_raw: bytes, *, expected_sha256: str, now_epoch: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,  # noqa: F401
        )
    except ImportError as exc:
        raise ActivationError("ED25519_VERIFIER_UNAVAILABLE") from exc
    keyring = _decode_json(keyring_raw)
    if set(keyring) != {
        "schemaVersion", "route", "trustEnvironment", "registryVersion",
        "issuedAtEpoch", "expiresAtEpoch", "revokedKeys", "keys",
        "keyringSha256",
    } or keyring.get("schemaVersion") != ACTIVATION_KEYRING_SCHEMA \
            or keyring.get("route") != ROUTE \
            or keyring.get("trustEnvironment") \
            != ACTIVATION_TRUST_ENVIRONMENT:
        raise ActivationError("INVALID_ACTIVATION_KEYRING")
    unsigned = {key: keyring[key] for key in (
        "schemaVersion", "route", "trustEnvironment", "registryVersion",
        "issuedAtEpoch", "expiresAtEpoch", "revokedKeys", "keys",
    )}
    keyring_sha = _sha(_canonical(unsigned))
    if (_digest(keyring.get("keyringSha256"), "INVALID_KEYRING_DIGEST")
            != keyring_sha
            or _digest(expected_sha256, "INVALID_EXPECTED_KEYRING_DIGEST")
            != keyring_sha):
        raise ActivationError("ACTIVATION_KEYRING_DIGEST_MISMATCH")
    issued = keyring.get("issuedAtEpoch")
    expires = keyring.get("expiresAtEpoch")
    version = keyring.get("registryVersion")
    if (type(now_epoch) is not int or type(version) is not int or version <= 0
            or type(issued) is not int or type(expires) is not int
            or issued <= 0 or not issued < expires
            <= issued + supervisor.MAX_KEYRING_LIFETIME_SECONDS
            or issued > now_epoch + MAX_FUTURE_SKEW_SECONDS
            or not issued <= now_epoch < expires):
        raise ActivationError("ACTIVATION_KEYRING_TIME_INVALID")
    revoked = keyring.get("revokedKeys")
    if type(revoked) is not list or len(revoked) > 64:
        raise ActivationError("INVALID_ACTIVATION_REVOCATIONS")
    revoked_ids: set[str] = set()
    for item in revoked:
        if not isinstance(item, Mapping) or set(item) != {
                "keyId", "revokedAtEpoch", "reasonCode"}:
            raise ActivationError("INVALID_ACTIVATION_REVOCATION")
        key_id = _token(item.get("keyId"), "INVALID_REVOKED_KEY_ID")
        revoked_at = item.get("revokedAtEpoch")
        _token(item.get("reasonCode"), "INVALID_REVOCATION_REASON")
        if (key_id in revoked_ids or type(revoked_at) is not int
                or revoked_at <= 0
                or revoked_at > now_epoch + MAX_FUTURE_SKEW_SECONDS):
            raise ActivationError("INVALID_ACTIVATION_REVOCATION")
        revoked_ids.add(key_id)
    keys = keyring.get("keys")
    if type(keys) is not list or len(keys) != 2:
        raise ActivationError("INVALID_ACTIVATION_KEYRING")
    registry: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    domains: set[str] = set()
    public_keys: set[bytes] = set()
    for entry in keys:
        if not isinstance(entry, Mapping) or set(entry) != {
                "keyId", "identityId", "trustDomain", "role", "status",
                "publicKeyB64"}:
            raise ActivationError("INVALID_ACTIVATION_KEY")
        key_id = _token(entry.get("keyId"), "INVALID_KEY_ID")
        identity = _token(entry.get("identityId"), "INVALID_IDENTITY_ID")
        domain = _token(entry.get("trustDomain"), "INVALID_TRUST_DOMAIN")
        try:
            public_key = supervisor._decode_public_key(
                entry.get("publicKeyB64")
            )
        except supervisor.SupervisorError as exc:
            raise ActivationError(str(exc)) from exc
        if (key_id != activation_key_id(public_key)
                or key_id in registry or key_id in revoked_ids
                or identity in identities or domain in domains
                or public_key in public_keys
                or entry.get("role") not in SIGNER_ROLES
                or entry.get("status") != "ACTIVE"):
            raise ActivationError("ACTIVATION_SIGNERS_NOT_INDEPENDENT")
        registry[key_id] = dict(entry)
        identities.add(identity)
        domains.add(domain)
        public_keys.add(public_key)
    if {entry["role"] for entry in keys} != SIGNER_ROLES:
        raise ActivationError("ACTIVATION_SIGNER_ROLES_MISMATCH")
    return keyring, registry, keyring_sha


def build_plan(
    *, environment: str, run_nonce: str, created_at_epoch: int,
    container_id: str, image_id: str, system_identifier: str,
    artifacts_sha256: Mapping[str, str], container_name: str | None = None,
) -> dict[str, Any]:
    _token(run_nonce, "INVALID_RUN_NONCE", minimum=16, maximum=64)
    _container_id(container_id, "INVALID_TARGET_CONTAINER_ID")
    if type(created_at_epoch) is not int or created_at_epoch <= 0:
        raise ActivationError("INVALID_PLAN_TIME")
    if environment not in {"PRODUCTION", "DISPOSABLE_CONTRACT"}:
        raise ActivationError("INVALID_ACTIVATION_ENVIRONMENT")
    if set(artifacts_sha256) != ARTIFACT_KEYS:
        raise ActivationError("INVALID_ACTIVATION_ARTIFACT_SET")
    artifacts = {
        key: _digest(artifacts_sha256[key], "INVALID_ARTIFACT_DIGEST")
        for key in sorted(ARTIFACT_KEYS)
    }
    authority = (
        PRODUCTION_AUTHORITY if environment == "PRODUCTION"
        else CONTRACT_AUTHORITY
    )
    if environment == "PRODUCTION":
        if container_name not in {None, PRODUCTION_CONTAINER}:
            raise ActivationError("PRODUCTION_TARGET_BINDING_MISMATCH")
        if (image_id != PRODUCTION_IMAGE_ID
                or system_identifier != PRODUCTION_SYSTEM_IDENTIFIER):
            raise ActivationError("PRODUCTION_TARGET_BINDING_MISMATCH")
        bound_container_name = PRODUCTION_CONTAINER
    else:
        if (type(container_name) is not str
                or re.fullmatch(CONTRACT_CONTAINER_PATTERN, container_name)
                is None):
            raise ActivationError("CONTRACT_TARGET_BINDING_MISMATCH")
        bound_container_name = container_name
    expected_image = (
        PRODUCTION_IMAGE_ID if environment == "PRODUCTION" else image_id
    )
    expected_system = (
        PRODUCTION_SYSTEM_IDENTIFIER
        if environment == "PRODUCTION" else system_identifier
    )
    plan = {
        "schemaVersion": PLAN_SCHEMA,
        "route": ROUTE,
        "operation": "ONE_BOUNDED_READ_ONLY_REFRESH_TO_DISPOSABLE_RESTORE",
        "environment": environment,
        "runNonce": run_nonce,
        "createdAtEpoch": created_at_epoch,
        "legacyAcceptedRehearsalPlanSha256":
            LEGACY_ACCEPTED_REHEARSAL_PLAN_SHA256,
        "hardenedPlanRawSha256": HARDENED_PLAN_RAW_SHA256,
        "derivedExecutionPlanSha256": _sha(_canonical(
            derive_execution_plan(
                run_nonce=run_nonce, artifacts_sha256=artifacts,
            )
        )),
        "prerequisiteEvidenceAcceptanceSha256":
            EVIDENCE_ACCEPTANCE_SHA256,
        "target": {
            "containerName": bound_container_name,
            "containerId": container_id,
            "imageId": expected_image,
            "systemIdentifier": expected_system,
            "database": "obsidian_exchange",
            "readerRole": "obsidian_b64_snapshot_reader",
        },
        "limits": dict(LIMITS),
        "closeRequirements": dict(CLOSE_REQUIREMENTS),
        "executionProfile": dict(EXECUTION_PROFILE),
        "artifactsSha256": artifacts,
        "authority": dict(authority),
    }
    return validate_plan(plan, expected_environment=environment)


def validate_plan(
    value: Mapping[str, Any], *, expected_environment: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schemaVersion", "route", "operation", "environment", "runNonce",
        "createdAtEpoch", "legacyAcceptedRehearsalPlanSha256",
        "hardenedPlanRawSha256",
        "derivedExecutionPlanSha256",
        "prerequisiteEvidenceAcceptanceSha256", "target", "limits",
        "closeRequirements", "executionProfile", "artifactsSha256",
        "authority",
    }:
        raise ActivationError("INVALID_ACTIVATION_PLAN_SHAPE")
    if (value.get("schemaVersion") != PLAN_SCHEMA
            or value.get("route") != ROUTE
            or value.get("operation")
            != "ONE_BOUNDED_READ_ONLY_REFRESH_TO_DISPOSABLE_RESTORE"
            or value.get("environment") != expected_environment):
        raise ActivationError("INVALID_ACTIVATION_PLAN_IDENTITY")
    _token(value.get("runNonce"), "INVALID_RUN_NONCE", minimum=16,
           maximum=64)
    if type(value.get("createdAtEpoch")) is not int \
            or value["createdAtEpoch"] <= 0:
        raise ActivationError("INVALID_PLAN_TIME")
    if (value.get("legacyAcceptedRehearsalPlanSha256")
            != LEGACY_ACCEPTED_REHEARSAL_PLAN_SHA256
            or value.get("hardenedPlanRawSha256")
            != HARDENED_PLAN_RAW_SHA256
            or value.get("prerequisiteEvidenceAcceptanceSha256")
            != EVIDENCE_ACCEPTANCE_SHA256):
        raise ActivationError("ACTIVATION_PREREQUISITE_BINDING_MISMATCH")
    target = value.get("target")
    if not isinstance(target, Mapping) or set(target) != {
        "containerName", "containerId", "imageId", "systemIdentifier",
        "database", "readerRole",
    }:
        raise ActivationError("INVALID_ACTIVATION_TARGET")
    container_id = _container_id(
        target.get("containerId"), "INVALID_TARGET_CONTAINER_ID"
    )
    image_id = target.get("imageId")
    system_identifier = target.get("systemIdentifier")
    if (type(image_id) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
            or type(system_identifier) is not str
            or re.fullmatch(r"[0-9]{8,32}", system_identifier) is None
            or target.get("database") != "obsidian_exchange"
            or target.get("readerRole") != "obsidian_b64_snapshot_reader"):
        raise ActivationError("INVALID_ACTIVATION_TARGET")
    if expected_environment == "PRODUCTION":
        if (target.get("containerName") != PRODUCTION_CONTAINER
                or container_id == "0" * 64
                or image_id != PRODUCTION_IMAGE_ID
                or system_identifier != PRODUCTION_SYSTEM_IDENTIFIER):
            raise ActivationError("PRODUCTION_TARGET_BINDING_MISMATCH")
        authority = PRODUCTION_AUTHORITY
    elif expected_environment == "DISPOSABLE_CONTRACT":
        if (type(target.get("containerName")) is not str
                or re.fullmatch(
                    CONTRACT_CONTAINER_PATTERN, target["containerName"]
                ) is None or container_id == "0" * 64):
            raise ActivationError("CONTRACT_TARGET_BINDING_MISMATCH")
        authority = CONTRACT_AUTHORITY
    else:
        raise ActivationError("INVALID_ACTIVATION_ENVIRONMENT")
    if not _exact(value.get("limits"), LIMITS):
        raise ActivationError("INVALID_ACTIVATION_LIMITS")
    if not _exact(value.get("closeRequirements"), CLOSE_REQUIREMENTS):
        raise ActivationError("INVALID_ACTIVATION_CLOSE_REQUIREMENTS")
    if not _exact(value.get("executionProfile"), EXECUTION_PROFILE):
        raise ActivationError("INVALID_ACTIVATION_EXECUTION_PROFILE")
    artifacts = value.get("artifactsSha256")
    if not isinstance(artifacts, Mapping) or set(artifacts) != ARTIFACT_KEYS:
        raise ActivationError("INVALID_ACTIVATION_ARTIFACT_SET")
    for digest in artifacts.values():
        _digest(digest, "INVALID_ARTIFACT_DIGEST")
    derived_sha = _sha(_canonical(derive_execution_plan(
        run_nonce=value["runNonce"], artifacts_sha256=artifacts,
    )))
    if value.get("derivedExecutionPlanSha256") != derived_sha:
        raise ActivationError("DERIVED_EXECUTION_PLAN_BINDING_MISMATCH")
    if not _exact(value.get("authority"), authority):
        raise ActivationError("INVALID_ACTIVATION_AUTHORITY")
    return json.loads(_canonical(dict(value)))


@dataclass(frozen=True)
class VerifiedActivation:
    environment: str
    run_nonce: str
    plan_sha256: str
    decision_sha256: str
    keyring_sha256: str
    derived_execution_plan_sha256: str
    expires_at_epoch: int
    target: Mapping[str, Any]
    limits: Mapping[str, Any]
    _verification_seal: object
    _capability_state: _ExecutionCapabilityState


@dataclass(frozen=True)
class VerifiedRecovery:
    """Package-bound cleanup capability with no execute or lease authority."""

    environment: str
    run_nonce: str
    plan_sha256: str
    decision_sha256: str
    keyring_sha256: str
    derived_execution_plan_sha256: str
    decision_expires_at_epoch: int
    target: Mapping[str, Any]
    limits: Mapping[str, Any]
    _recovery_seal: object


def require_verified_execution_authorization(
    authorization: Any, *, expected_environment: str,
    require_started: bool = True,
) -> VerifiedActivation:
    """Accept only an object emitted by exact package verification.

    This is a process-local capability boundary, not a substitute for the
    signed decision or the durable journal.  It prevents legacy/direct helper
    calls from silently opting into the production mutation path.
    """
    if (not isinstance(authorization, VerifiedActivation)
            or authorization._verification_seal
            is not _VERIFIED_ACTIVATION_SEAL
            or authorization.environment != expected_environment
            or (require_started
                and not authorization._capability_state.execution_started)):
        raise ActivationError("ACTIVATION_EXECUTION_AUTHORIZATION_INVALID")
    return authorization


def claim_verified_production_lease(authorization: Any) -> None:
    verified = require_verified_execution_authorization(
        authorization, expected_environment="PRODUCTION"
    )
    verified._capability_state.claim_lease()


def require_verified_recovery_authorization(
    authorization: Any, *, expected_environment: str,
) -> VerifiedActivation | VerifiedRecovery:
    if (isinstance(authorization, VerifiedActivation)
            and authorization._verification_seal
            is _VERIFIED_ACTIVATION_SEAL
            and authorization.environment == expected_environment):
        return authorization
    if (isinstance(authorization, VerifiedRecovery)
            and authorization._recovery_seal is _VERIFIED_RECOVERY_SEAL
            and authorization.environment == expected_environment):
        return authorization
    raise ActivationError("ACTIVATION_RECOVERY_AUTHORIZATION_INVALID")


def verify_activation_decision(
    *, keyring_raw: bytes, decision_raw: bytes, activation_plan_raw: bytes,
    expected_keyring_sha256: str, expected_environment: str, now_epoch: int,
) -> VerifiedActivation:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:
        raise ActivationError("ED25519_VERIFIER_UNAVAILABLE") from exc
    keyring, registry, keyring_sha = _load_keyring(
        keyring_raw, expected_sha256=expected_keyring_sha256,
        now_epoch=now_epoch,
    )
    plan = validate_plan(
        _decode_json(activation_plan_raw),
        expected_environment=expected_environment,
    )
    verify_artifact_closure(plan)
    plan_sha = _sha(_canonical(plan))
    decision = _decode_json(decision_raw)
    expected_keys = {
        "schemaVersion", "route", "decision", "environment",
        "activationPlanSha256", "keyringSha256", "issuedAtEpoch",
        "expiresAtEpoch", "nonce", "limits", "authority",
        "decisionSha256", "signatures",
    }
    if set(decision) != expected_keys:
        raise ActivationError("INVALID_ACTIVATION_DECISION_SHAPE")
    unsigned_keys = (
        "schemaVersion", "route", "decision", "environment",
        "activationPlanSha256", "keyringSha256", "issuedAtEpoch",
        "expiresAtEpoch", "nonce", "limits", "authority",
    )
    unsigned = {key: decision[key] for key in unsigned_keys}
    authority = (
        PRODUCTION_AUTHORITY if expected_environment == "PRODUCTION"
        else CONTRACT_AUTHORITY
    )
    if (unsigned["schemaVersion"] != DECISION_SCHEMA
            or unsigned["route"] != ROUTE
            or unsigned["decision"]
            != "AUTHORIZE_ONE_BOUNDED_READ_ONLY_REFRESH"
            or unsigned["environment"] != expected_environment
            or unsigned["activationPlanSha256"] != plan_sha
            or unsigned["keyringSha256"] != keyring_sha
            or unsigned["nonce"] != plan["runNonce"]
            or not _exact(unsigned["limits"], LIMITS)
            or not _exact(unsigned["authority"], authority)):
        raise ActivationError("ACTIVATION_DECISION_BINDING_MISMATCH")
    issued = unsigned["issuedAtEpoch"]
    expires = unsigned["expiresAtEpoch"]
    if (type(issued) is not int or type(expires) is not int or issued <= 0
            or not issued < expires
            <= issued + MAX_DECISION_LIFETIME_SECONDS
            or plan["createdAtEpoch"] > issued
            or issued - plan["createdAtEpoch"] > MAX_PLAN_AGE_SECONDS
            or issued < keyring["issuedAtEpoch"]
            or expires > keyring["expiresAtEpoch"]
            or issued > now_epoch + MAX_FUTURE_SKEW_SECONDS
            or not issued <= now_epoch < expires):
        raise ActivationError("ACTIVATION_DECISION_TIME_INVALID")
    _token(unsigned["nonce"], "INVALID_ACTIVATION_NONCE", minimum=16,
           maximum=64)
    decision_sha = _sha(_canonical(unsigned))
    if decision.get("decisionSha256") != decision_sha:
        raise ActivationError("ACTIVATION_DECISION_DIGEST_MISMATCH")
    signatures = decision.get("signatures")
    if type(signatures) is not list or len(signatures) != 2:
        raise ActivationError("INVALID_ACTIVATION_SIGNATURE_SET")
    seen_roles: set[str] = set()
    seen_keys: set[str] = set()
    for signature in signatures:
        if not isinstance(signature, Mapping) or set(signature) != {
                "role", "keyId", "identityId", "signatureB64"}:
            raise ActivationError("INVALID_ACTIVATION_SIGNATURE")
        role = signature.get("role")
        key_id = signature.get("keyId")
        key = registry.get(key_id)
        if (role not in SIGNER_ROLES or role in seen_roles
                or key_id in seen_keys or key is None
                or key["role"] != role
                or key["identityId"] != signature.get("identityId")):
            raise ActivationError("ACTIVATION_SIGNATURE_BINDING_MISMATCH")
        try:
            public = supervisor._decode_public_key(key["publicKeyB64"])
            encoded_signature = supervisor._decode_signature(
                signature.get("signatureB64")
            )
            Ed25519PublicKey.from_public_bytes(public).verify(
                encoded_signature, SIGNATURE_DOMAIN + _canonical(unsigned),
            )
        except supervisor.SupervisorError as exc:
            raise ActivationError(str(exc)) from exc
        except BaseException as exc:
            raise ActivationError("ACTIVATION_SIGNATURE_INVALID") from exc
        seen_roles.add(role)
        seen_keys.add(key_id)
    if seen_roles != SIGNER_ROLES:
        raise ActivationError("ACTIVATION_SIGNER_ROLES_MISMATCH")
    return VerifiedActivation(
        environment=expected_environment,
        run_nonce=plan["runNonce"],
        plan_sha256=plan_sha,
        decision_sha256=decision_sha,
        keyring_sha256=keyring_sha,
        derived_execution_plan_sha256=plan[
            "derivedExecutionPlanSha256"
        ],
        expires_at_epoch=expires,
        target=dict(plan["target"]),
        limits=dict(plan["limits"]),
        _verification_seal=_VERIFIED_ACTIVATION_SEAL,
        _capability_state=_ExecutionCapabilityState(),
    )


def verify_cleanup_recovery(
    *, keyring_raw: bytes, decision_raw: bytes, activation_plan_raw: bytes,
    expected_keyring_sha256: str, expected_environment: str, now_epoch: int,
) -> VerifiedRecovery:
    """Verify an exact historical package for cleanup after expiry.

    Signature and time relationships are rechecked at the signed decision's
    issuance instant. The current time may be after both expiries, but cannot
    precede the signed issuance beyond the normal clock skew. The returned
    object is rejected by every execute and lease boundary.
    """
    decision = _decode_json(decision_raw)
    issued = decision.get("issuedAtEpoch")
    if (type(now_epoch) is not int or type(issued) is not int
            or now_epoch + MAX_FUTURE_SKEW_SECONDS < issued):
        raise ActivationError("ACTIVATION_RECOVERY_TIME_INVALID")
    verified = verify_activation_decision(
        keyring_raw=keyring_raw, decision_raw=decision_raw,
        activation_plan_raw=activation_plan_raw,
        expected_keyring_sha256=expected_keyring_sha256,
        expected_environment=expected_environment, now_epoch=issued,
    )
    return VerifiedRecovery(
        environment=verified.environment,
        run_nonce=verified.run_nonce,
        plan_sha256=verified.plan_sha256,
        decision_sha256=verified.decision_sha256,
        keyring_sha256=verified.keyring_sha256,
        derived_execution_plan_sha256=(
            verified.derived_execution_plan_sha256
        ),
        decision_expires_at_epoch=verified.expires_at_epoch,
        target=dict(verified.target), limits=dict(verified.limits),
        _recovery_seal=_VERIFIED_RECOVERY_SEAL,
    )


class ActivationExecutor(Protocol):
    production_contact: bool

    def execute(
        self, plan: Mapping[str, Any], authorization: VerifiedActivation,
        deadline: float,
    ) -> Mapping[str, Any]: ...

    def reconcile_resources(
        self, *, plan: Mapping[str, Any],
        authorization: VerifiedActivation | VerifiedRecovery,
    ) -> Mapping[str, Any]: ...


def _write_all(fd: int, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = os.write(fd, raw[offset:])
        if written <= 0:
            raise ActivationError("ACTIVATION_JOURNAL_SHORT_WRITE")
        offset += written


def _safe_open_root(path: Path) -> int:
    if not path.is_absolute():
        raise ActivationError("JOURNAL_ROOT_NOT_ABSOLUTE")
    try:
        fd = os.open(
            path, os.O_RDONLY | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(fd)
    except OSError as exc:
        raise ActivationError("JOURNAL_ROOT_UNSAFE") from exc
    if (metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700):
        os.close(fd)
        raise ActivationError("JOURNAL_ROOT_UNSAFE")
    return fd


def _acquire_production_interlock(
    authorization: VerifiedActivation | VerifiedRecovery,
) -> int:
    try:
        descriptor = os.open(
            PRODUCTION_INTERLOCK_PATH,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1):
            raise ActivationError("ACTIVATION_INTERLOCK_UNSAFE")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        evidence = _canonical({
            "schemaVersion": "b64-064a-production-activation-interlock.v1",
            "runNonce": authorization.run_nonce,
            "planSha256": authorization.plan_sha256,
            "decisionSha256": authorization.decision_sha256,
        }) + b"\n"
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        _write_all(descriptor, evidence)
        os.fsync(descriptor)
        return descriptor
    except BlockingIOError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise ActivationError("ACTIVATION_INTERLOCK_HELD") from exc
    except BaseException:
        if "descriptor" in locals():
            os.close(descriptor)
        raise


class ActivationJournal:
    def __init__(
        self, root: Path,
        authorization: VerifiedActivation | VerifiedRecovery,
    ):
        self.root = root
        self.authorization = authorization
        self.name = f"{authorization.run_nonce}.json"
        self.lock_name = f".{authorization.run_nonce}.lock"
        self.receipt_name = f"{authorization.run_nonce}.receipt.json"

    def acquire_execution_lock(self) -> int:
        directory_fd = _safe_open_root(self.root)
        descriptor = -1
        try:
            descriptor = os.open(
                self.lock_name, os.O_RDWR | os.O_CREAT
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600, dir_fd=directory_fd,
            )
            metadata = os.fstat(descriptor)
            if (not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_nlink != 1):
                raise ActivationError("ACTIVATION_LOCK_UNSAFE")
            try:
                fcntl.flock(
                    descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB
                )
            except BlockingIOError as exc:
                raise ActivationError("ACTIVATION_EXECUTION_LOCKED") from exc
            os.fsync(directory_fd)
            return descriptor
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            raise
        finally:
            os.close(directory_fd)

    def _read(self, directory_fd: int) -> dict[str, Any]:
        try:
            fd = os.open(
                self.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0), dir_fd=directory_fd,
            )
        except OSError as exc:
            raise ActivationError("ACTIVATION_JOURNAL_MISSING") from exc
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_nlink != 1 or not 1 <= metadata.st_size
                    <= 64 * 1024):
                raise ActivationError("ACTIVATION_JOURNAL_UNSAFE")
            raw = b""
            while len(raw) < metadata.st_size:
                chunk = os.read(fd, metadata.st_size - len(raw))
                if not chunk:
                    raise ActivationError("ACTIVATION_JOURNAL_SHORT_READ")
                raw += chunk
            if os.read(fd, 1):
                raise ActivationError("ACTIVATION_JOURNAL_GREW")
        finally:
            os.close(fd)
        value = _decode_json(raw)
        if (set(value) != {
                "schemaVersion", "route", "runNonce", "planSha256",
                "decisionSha256", "state", "attempt", "retryAllowed",
                "receiptSha256", "reasonCode"}
                or value.get("schemaVersion") != JOURNAL_SCHEMA
                or value.get("route") != ROUTE
                or value.get("runNonce") != self.authorization.run_nonce
                or value.get("planSha256") != self.authorization.plan_sha256
                or value.get("decisionSha256")
                != self.authorization.decision_sha256
                or value.get("state") not in {
                    "CLAIMED", "RUNNING", "CLOSED", "HOLD",
                    "RECONCILED_HOLD"}
                or value.get("attempt") != 1
                or value.get("retryAllowed") is not False
                or (value.get("receiptSha256") is not None
                    and _digest(value["receiptSha256"],
                                "INVALID_JOURNAL_RECEIPT_DIGEST")
                    != value["receiptSha256"])
                or (value.get("reasonCode") is not None
                    and _token(value["reasonCode"],
                               "INVALID_JOURNAL_REASON")
                    != value["reasonCode"])):
            raise ActivationError("ACTIVATION_JOURNAL_BINDING_MISMATCH")
        return value

    def _write_new(self, directory_fd: int, value: Mapping[str, Any]) -> None:
        raw = _canonical(dict(value)) + b"\n"
        try:
            fd = os.open(
                self.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600, dir_fd=directory_fd,
            )
        except FileExistsError as exc:
            raise ActivationError("ACTIVATION_REPLAY_OR_INCOMPLETE") from exc
        try:
            _write_all(fd, raw)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory_fd)

    def _replace(
        self, directory_fd: int, *, expected_state: set[str], state: str,
        receipt_sha256: str | None, reason_code: str | None,
    ) -> dict[str, Any]:
        current = self._read(directory_fd)
        if current["state"] not in expected_state:
            raise ActivationError("ACTIVATION_JOURNAL_STATE_CONFLICT")
        value = {
            **current,
            "state": state,
            "receiptSha256": receipt_sha256,
            "reasonCode": reason_code,
        }
        temporary = f".{self.name}.{secrets.token_hex(8)}.tmp"
        raw = _canonical(value) + b"\n"
        fd = -1
        try:
            fd = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600, dir_fd=directory_fd,
            )
            _write_all(fd, raw)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(
                temporary, self.name,
                src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        except BaseException:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass
            raise
        return value

    def claim(self) -> dict[str, Any]:
        directory_fd = _safe_open_root(self.root)
        try:
            value = {
                "schemaVersion": JOURNAL_SCHEMA,
                "route": ROUTE,
                "runNonce": self.authorization.run_nonce,
                "planSha256": self.authorization.plan_sha256,
                "decisionSha256": self.authorization.decision_sha256,
                "state": "CLAIMED",
                "attempt": 1,
                "retryAllowed": False,
                "receiptSha256": None,
                "reasonCode": None,
            }
            self._write_new(directory_fd, value)
            return value
        finally:
            os.close(directory_fd)

    def transition(
        self, *, expected_state: set[str], state: str,
        receipt_sha256: str | None = None,
        reason_code: str | None = None,
    ) -> dict[str, Any]:
        if state not in {"RUNNING", "CLOSED", "HOLD", "RECONCILED_HOLD"}:
            raise ActivationError("INVALID_JOURNAL_TRANSITION")
        if receipt_sha256 is not None:
            _digest(receipt_sha256, "INVALID_JOURNAL_RECEIPT_DIGEST")
        if reason_code is not None:
            _token(reason_code, "INVALID_JOURNAL_REASON")
        directory_fd = _safe_open_root(self.root)
        try:
            return self._replace(
                directory_fd, expected_state=expected_state, state=state,
                receipt_sha256=receipt_sha256, reason_code=reason_code,
            )
        finally:
            os.close(directory_fd)

    def inspect(self) -> dict[str, Any]:
        directory_fd = _safe_open_root(self.root)
        try:
            return self._read(directory_fd)
        finally:
            os.close(directory_fd)

    def write_receipt(self, receipt: Mapping[str, Any]) -> str:
        raw = _canonical(dict(receipt)) + b"\n"
        receipt_sha = _sha(raw[:-1])
        directory_fd = _safe_open_root(self.root)
        try:
            try:
                descriptor = os.open(
                    self.receipt_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600, dir_fd=directory_fd,
                )
            except FileExistsError as exc:
                raise ActivationError(
                    "ACTIVATION_RECEIPT_ALREADY_EXISTS"
                ) from exc
            try:
                _write_all(descriptor, raw)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return receipt_sha


def _validate_dormant_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "loginState": "DISABLED",
        "credentialState": "ABSENT",
        "activeSessions": 0,
        "customerRowsRead": False,
    }
    if not isinstance(value, Mapping) or not all(
            key in value and type(value[key]) is type(wanted)
            and value[key] == wanted for key, wanted in expected.items()):
        raise ActivationError("DORMANT_RECONCILIATION_FAILED")
    return dict(value)


def _validate_execution_receipt(
    value: Mapping[str, Any], *, authorization: VerifiedActivation,
) -> dict[str, Any]:
    expected_keys = {
        "schemaVersion", "route", "environment", "runNonce",
        "planSha256", "decisionSha256", "status", "archiveBytes",
        "archiveSha256", "catalogEquality", "tableEquality",
        "credentialIssued", "credentialRevoked", "sourceSessionClosed",
        "readerLoginState", "readerCredentialState", "readerActiveSessions",
        "registeredWorkspaceAbsent", "dumpContainerAbsent",
        "restoreContainerAbsent", "containerTmpfsLifetimesEnded",
        "productionDataRetained", "automaticRetryAllowed", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise ActivationError("INVALID_ACTIVATION_EXECUTION_RECEIPT")
    archive_bytes = value.get("archiveBytes")
    if (value.get("schemaVersion") != EXECUTION_RECEIPT_SCHEMA
            or value.get("route") != ROUTE
            or value.get("environment") != authorization.environment
            or value.get("runNonce") != authorization.run_nonce
            or value.get("planSha256") != authorization.plan_sha256
            or value.get("decisionSha256") != authorization.decision_sha256
            or value.get("status") != "COMPLETED_DORMANT_VERIFIED"
            or type(archive_bytes) is not int or not 0 < archive_bytes
            <= authorization.limits["maximumArchiveBytes"]
            or _digest(value.get("archiveSha256"),
                       "INVALID_ARCHIVE_DIGEST") != value["archiveSha256"]
            or any(value.get(key) is not True for key in (
                "catalogEquality", "tableEquality", "credentialIssued",
                "credentialRevoked", "sourceSessionClosed",
                "registeredWorkspaceAbsent", "dumpContainerAbsent",
                "restoreContainerAbsent", "containerTmpfsLifetimesEnded",
            ))
            or value.get("readerLoginState") != "DISABLED"
            or value.get("readerCredentialState") != "ABSENT"
            or type(value.get("readerActiveSessions")) is not int
            or value.get("readerActiveSessions") != 0
            or value.get("productionDataRetained") is not False
            or value.get("automaticRetryAllowed") is not False
            or value.get("actionAllowed") is not False):
        raise ActivationError("ACTIVATION_EXECUTION_NOT_CLOSED")
    return json.loads(_canonical(dict(value)))


def _validate_resource_reconcile_receipt(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "status", "loginState", "credentialState", "activeSessions",
        "workspaceAbsent", "proxyAbsent", "dumpAbsent", "restoreAbsent",
        "automaticRetryAllowed", "actionAllowed",
    }
    if (not isinstance(value, Mapping) or set(value) != expected
            or value.get("status") not in {
                "EXECUTOR_RESOURCES_RECONCILED_HOLD",
                "EXECUTOR_RESOURCES_ALREADY_CLOSED",
                "EXECUTOR_RESOURCES_ABSENT_NO_JOURNAL",
            }
            or value.get("loginState") != "DISABLED"
            or value.get("credentialState") != "ABSENT"
            or type(value.get("activeSessions")) is not int
            or value.get("activeSessions") != 0
            or any(value.get(name) is not True for name in (
                "workspaceAbsent", "proxyAbsent", "dumpAbsent",
                "restoreAbsent",
            ))
            or value.get("automaticRetryAllowed") is not False
            or value.get("actionAllowed") is not False):
        raise ActivationError("EXECUTOR_RESOURCE_RECONCILIATION_FAILED")
    return dict(value)


def run_once(
    *, keyring_raw: bytes, decision_raw: bytes, activation_plan_raw: bytes,
    expected_keyring_sha256: str, expected_environment: str, now_epoch: int,
    journal_root: Path, executor: ActivationExecutor,
    reconcile: Callable[[], Mapping[str, Any]],
    verify_dormant: Callable[[], Mapping[str, Any]],
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if expected_environment == "PRODUCTION":
        try:
            trusted_now, _clock_evidence = supervisor._trusted_now_epoch()
        except supervisor.SupervisorError as exc:
            raise ActivationError(str(exc)) from exc
        if (type(now_epoch) is not int
                or abs(trusted_now - now_epoch) > 1):
            raise ActivationError("ACTIVATION_TRUSTED_TIME_MISMATCH")
        now_epoch = trusted_now
    authorization = verify_activation_decision(
        keyring_raw=keyring_raw, decision_raw=decision_raw,
        activation_plan_raw=activation_plan_raw,
        expected_keyring_sha256=expected_keyring_sha256,
        expected_environment=expected_environment, now_epoch=now_epoch,
    )
    production_contact = getattr(executor, "production_contact", None)
    if ((expected_environment == "PRODUCTION"
         and production_contact is not True)
            or (expected_environment == "DISPOSABLE_CONTRACT"
                and production_contact is not False)):
        raise ActivationError("EXECUTOR_ENVIRONMENT_MISMATCH")
    if (expected_environment == "PRODUCTION"
            and journal_root != PRODUCTION_JOURNAL_ROOT):
        raise ActivationError("PRODUCTION_JOURNAL_ROOT_MISMATCH")
    if now_epoch >= authorization.expires_at_epoch:
        raise ActivationError("ACTIVATION_DECISION_TIME_INVALID")
    _validate_dormant_receipt(reconcile())
    _validate_dormant_receipt(verify_dormant())
    plan = validate_plan(
        _decode_json(activation_plan_raw),
        expected_environment=expected_environment,
    )
    journal = ActivationJournal(journal_root, authorization)
    execution_lock = journal.acquire_execution_lock()
    interlock_fd = -1
    try:
        if expected_environment == "PRODUCTION":
            interlock_fd = _acquire_production_interlock(authorization)
        journal.claim()
        journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
        authorization._capability_state.begin_execution()
        started = monotonic()
        work_deadline = (
            started + authorization.limits["workDeadlineSeconds"]
        )
        overall_deadline = (
            started + authorization.limits["overallDeadlineSeconds"]
        )
        try:
            receipt = _validate_execution_receipt(
                executor.execute(plan, authorization, work_deadline),
                authorization=authorization,
            )
            if monotonic() > work_deadline:
                raise ActivationError("ACTIVATION_WORK_DEADLINE_EXCEEDED")
            _validate_dormant_receipt(reconcile())
            _validate_dormant_receipt(verify_dormant())
            if monotonic() > overall_deadline:
                raise ActivationError(
                    "ACTIVATION_OVERALL_DEADLINE_EXCEEDED"
                )
        except BaseException as exc:
            reason = _reason(exc)
            try:
                _validate_resource_reconcile_receipt(
                    executor.reconcile_resources(
                        plan=plan, authorization=authorization,
                    )
                )
                _validate_dormant_receipt(reconcile())
                _validate_dormant_receipt(verify_dormant())
                if monotonic() > overall_deadline:
                    reason = "ACTIVATION_CLOSE_DEADLINE_EXCEEDED"
            except BaseException:
                reason = "ACTIVATION_CLOSE_UNCERTAIN"
            journal.transition(
                expected_state={"RUNNING"}, state="HOLD",
                reason_code=reason,
            )
            raise ActivationError(reason) from None
        try:
            receipt_sha = journal.write_receipt(receipt)
        except BaseException:
            try:
                _validate_resource_reconcile_receipt(
                    executor.reconcile_resources(
                        plan=plan, authorization=authorization,
                    )
                )
                _validate_dormant_receipt(reconcile())
                _validate_dormant_receipt(verify_dormant())
                reason = "ACTIVATION_RECEIPT_DURABILITY_FAILED"
            except BaseException:
                reason = "ACTIVATION_CLOSE_UNCERTAIN"
            journal.transition(
                expected_state={"RUNNING"}, state="HOLD",
                reason_code=reason,
            )
            raise ActivationError(reason) from None
        journal.transition(
            expected_state={"RUNNING"}, state="CLOSED",
            receipt_sha256=receipt_sha,
        )
    finally:
        if interlock_fd >= 0:
            os.close(interlock_fd)
        os.close(execution_lock)
    return {
        "schemaVersion": "b64-064a-production-activation-result.v1",
        "route": ROUTE,
        "status": "ACTIVATION_COMPLETED_DORMANT_VERIFIED",
        "environment": expected_environment,
        "runNonce": authorization.run_nonce,
        "planSha256": authorization.plan_sha256,
        "decisionSha256": authorization.decision_sha256,
        "receiptSha256": receipt_sha,
        "journalState": "CLOSED",
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }


def reconcile_incomplete(
    *, authorization: VerifiedActivation | VerifiedRecovery,
    journal_root: Path,
    activation_plan_raw: bytes, executor: ActivationExecutor,
    reconcile: Callable[[], Mapping[str, Any]],
    verify_dormant: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    authorization = require_verified_recovery_authorization(
        authorization, expected_environment=authorization.environment,
    )
    plan = validate_plan(
        _decode_json(activation_plan_raw),
        expected_environment=authorization.environment,
    )
    if _sha(_canonical(plan)) != authorization.plan_sha256:
        raise ActivationError("ACTIVATION_RECONCILE_PLAN_MISMATCH")
    production_contact = getattr(executor, "production_contact", None)
    if ((authorization.environment == "PRODUCTION"
         and production_contact is not True)
            or (authorization.environment == "DISPOSABLE_CONTRACT"
                and production_contact is not False)):
        raise ActivationError("EXECUTOR_ENVIRONMENT_MISMATCH")
    if (authorization.environment == "PRODUCTION"
            and journal_root != PRODUCTION_JOURNAL_ROOT):
        raise ActivationError("PRODUCTION_JOURNAL_ROOT_MISMATCH")
    journal = ActivationJournal(journal_root, authorization)
    execution_lock = journal.acquire_execution_lock()
    interlock_fd = -1
    try:
        if authorization.environment == "PRODUCTION":
            interlock_fd = _acquire_production_interlock(authorization)
        current = journal.inspect()
        if current["state"] not in {"CLAIMED", "RUNNING", "HOLD"}:
            raise ActivationError("ACTIVATION_RECONCILE_STATE_INVALID")
        try:
            _validate_resource_reconcile_receipt(
                executor.reconcile_resources(
                    plan=plan, authorization=authorization,
                )
            )
            _validate_dormant_receipt(reconcile())
            _validate_dormant_receipt(verify_dormant())
        except BaseException as exc:
            reason = _reason(exc)
            try:
                journal.transition(
                    expected_state={"CLAIMED", "RUNNING", "HOLD"},
                    state="HOLD", reason_code=reason,
                )
            except BaseException:
                reason = "ACTIVATION_RECONCILE_HOLD_UNCERTAIN"
            raise ActivationError(reason) from None
        journal.transition(
            expected_state={"CLAIMED", "RUNNING", "HOLD"},
            state="RECONCILED_HOLD",
            reason_code="ABNORMAL_EXIT_RECONCILED_NO_RETRY",
        )
    finally:
        if interlock_fd >= 0:
            os.close(interlock_fd)
        os.close(execution_lock)
    return {
        "status": "ACTIVATION_RECONCILED_HOLD",
        "runNonce": authorization.run_nonce,
        "loginState": "DISABLED",
        "credentialState": "ABSENT",
        "activeSessions": 0,
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }


def recover_incomplete_from_package(
    *, keyring_raw: bytes, decision_raw: bytes, activation_plan_raw: bytes,
    expected_keyring_sha256: str, expected_environment: str, now_epoch: int,
    journal_root: Path, executor: ActivationExecutor,
    reconcile: Callable[[], Mapping[str, Any]],
    verify_dormant: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    if expected_environment == "PRODUCTION":
        try:
            trusted_now, _clock_evidence = supervisor._trusted_now_epoch()
        except supervisor.SupervisorError as exc:
            raise ActivationError(str(exc)) from exc
        if type(now_epoch) is not int or abs(trusted_now - now_epoch) > 1:
            raise ActivationError("ACTIVATION_TRUSTED_TIME_MISMATCH")
        now_epoch = trusted_now
    recovery = verify_cleanup_recovery(
        keyring_raw=keyring_raw, decision_raw=decision_raw,
        activation_plan_raw=activation_plan_raw,
        expected_keyring_sha256=expected_keyring_sha256,
        expected_environment=expected_environment, now_epoch=now_epoch,
    )
    return reconcile_incomplete(
        authorization=recovery, journal_root=journal_root,
        activation_plan_raw=activation_plan_raw, executor=executor,
        reconcile=reconcile, verify_dormant=verify_dormant,
    )


def _safe_read(path: str) -> bytes:
    value = Path(path)
    if not value.is_absolute():
        raise ActivationError("INPUT_PATH_NOT_ABSOLUTE")
    try:
        fd = os.open(
            value, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or not 1 <= metadata.st_size <= 1024 * 1024):
            raise ActivationError("INPUT_FILE_UNSAFE")
        raw = b""
        while len(raw) < metadata.st_size:
            chunk = os.read(fd, metadata.st_size - len(raw))
            if not chunk:
                raise ActivationError("INPUT_FILE_SHORT_READ")
            raw += chunk
        return raw
    except OSError as exc:
        raise ActivationError("INPUT_FILE_UNSAFE") from exc
    finally:
        if "fd" in locals():
            os.close(fd)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--verify-package", action="store_true", required=True)
    value.add_argument("--keyring", required=True)
    value.add_argument("--decision", required=True)
    value.add_argument("--activation-plan", required=True)
    value.add_argument("--expected-keyring-sha256", required=True)
    value.add_argument(
        "--environment", choices=("PRODUCTION", "DISPOSABLE_CONTRACT"),
        required=True,
    )
    value.add_argument("--now", type=int, required=True)
    return value


def main() -> int:
    os.umask(0o077)
    try:
        args = parser().parse_args()
        verified = verify_activation_decision(
            keyring_raw=_safe_read(args.keyring),
            decision_raw=_safe_read(args.decision),
            activation_plan_raw=_safe_read(args.activation_plan),
            expected_keyring_sha256=args.expected_keyring_sha256,
            expected_environment=args.environment,
            now_epoch=args.now,
        )
        print(json.dumps({
            "receiptStatus": "OK",
            "route": ROUTE,
            "status": "ACTIVATION_PACKAGE_VERIFIED_EXECUTOR_ABSENT",
            "environment": verified.environment,
            "runNonce": verified.run_nonce,
            "planSha256": verified.plan_sha256,
            "decisionSha256": verified.decision_sha256,
            "productionExecutionAdapterPresent": False,
            "authorizationConsumed": False,
            "automaticRetryAllowed": False,
            "actionAllowed": False,
        }, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({
            "receiptStatus": "ERROR", "route": ROUTE,
            "status": "NO_GO", "reason": _reason(exc),
            "authorizationConsumed": False,
            "automaticRetryAllowed": False, "actionAllowed": False,
        }, sort_keys=True, separators=(",", ":")))
        return 3


if __name__ == "__main__":
    sys.exit(main())
