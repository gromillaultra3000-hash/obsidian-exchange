#!/usr/bin/env python3
"""Hermetic lifecycle contract for the future hardened 064A refresh.

This module deliberately has no production adapter.  It makes the dangerous
parts injectable so cleanup, inode binding, command construction and evidence
validation can be exercised without Docker, PostgreSQL or production data.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import fcntl
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


ROUTE = "E0/E0.3/B5.3/064A"
PLAN_SCHEMA = "b64-064a-hardened-refresh-plan.v1"
RECEIPT_SCHEMA = "b64-064a-hardened-refresh-receipt.v1"
IMAGE_INDEX = "sha256:18cfe3ef5e6815560c98237d6216d1e5119702fb0f3894c8785dd58b8bbe5d73"
IMAGE_CHILD = "sha256:7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee"
IMAGE_CONFIG = "sha256:1bea307dfb3ee30541a7acf7de14b58bcd6948da98e5d31a04c627c4d35ec64b"
IMAGE_REF = f"docker.io/library/postgres@{IMAGE_CHILD}"
IMAGE_SOURCE_REVISION = "2603e26e245e558218728ee14e0a42dcb020dc7f"
PG_DUMP_VERSION = "pg_dump (PostgreSQL) 17.11"
RUNNER_ROLE = "obsidian_b64_snapshot_reader"
SNAPSHOT_READER_PROFILE = "FROZEN_001_023_SOURCE_PROFILE"
SNAPSHOT_READER_INVENTORY_SHA256 = \
    "cd65edefff6708dcb58b33fa554f8c19895f3312271819cce5eace9a276d7893"
SOURCE_CONTAINER = "obsidian-postgres"
SOURCE_DATABASE = "obsidian_exchange"
TRANSIENT_NAMES = (
    "source-table-fingerprint.json",
    "source-catalog-fingerprint.json",
    "snapshot.dump",
    "restore-table-fingerprint.json",
    "restore-catalog-fingerprint.json",
    "dump-stderr.bin",
)
ARTIFACT_KEYS = (
    "runner",
    "dirtyScan",
    "catalogFingerprintSql",
    "tableFingerprintSql",
    "catalogComparator",
    "tableComparator",
    "bootstrapRolesSql",
    "prepareDatabaseSql",
    "runtimePrivilegesSql",
    "snapshotReaderProvisionSql",
    "snapshotReaderRollbackSql",
    "snapshotReaderVerifier",
    "snapshotReaderDeployRunner",
    "snapshotReaderHbaManifest",
    "snapshotReaderHbaDeployRunner",
    "snapshotReaderRuntime",
)
AUTHORITY = {
    "productionMutationAuthorized": False,
    "productionExpandAuthorized": False,
    "deploymentAuthorized": False,
    "restartAuthorized": False,
    "cutoverAuthorized": False,
    "telegramDeliveryAuthorized": False,
    "ambiguousSendingDispositionAuthorized": False,
    "automaticRetryAuthorized": False,
    "e4ExecutionAuthorized": False,
    "actionAllowed": False,
}
REQUIRED_CREDENTIAL_SEALS = (
    fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
    fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
)
MAX_CREDENTIAL_BYTES = 512


class HardenedRefreshError(RuntimeError):
    """A safe, closed reason code; never include sensitive exception text."""


class SourceAdapter(Protocol):
    production_contact: bool

    def open(self, plan: Mapping[str, Any], secret_fd: int, deadline: float) \
            -> tuple[Mapping[str, Any], str]: ...
    def close(self) -> Mapping[str, Any]: ...


class DumpAdapter(Protocol):
    production_contact: bool

    def run(self, plan: Mapping[str, Any], snapshot: str,
            source_container_id: str, credential_not_after_epoch: int,
            archive_fd: int, secret_fd: int, deadline: float) \
            -> Mapping[str, Any]: ...
    def cleanup(self, expected_container_id: str | None) \
            -> Mapping[str, Any]: ...


class RestoreAdapter(Protocol):
    production_contact: bool

    def verify(self, plan: Mapping[str, Any], archive_fd: int,
               workspace_fd: int, source_fingerprints: Mapping[str, Any],
               deadline: float) -> Mapping[str, Any]: ...
    def cleanup(self, expected_container_id: str | None) \
            -> Mapping[str, Any]: ...


def _canonical(value: Any) -> bytes:
    def check(item: Any) -> None:
        if item is None or type(item) in (str, int, bool):
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for child in item.values():
                check(child)
            return
        raise HardenedRefreshError("NONCANONICAL_VALUE")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _exact(value: Any, expected: Any) -> bool:
    """Compare closed evidence without Python's bool/int equality aliasing."""
    if type(expected) in (str, int, bool) or expected is None:
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


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any, code: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise HardenedRefreshError(code)
    return value


def _token(value: Any, code: str, maximum: int = 96) -> str:
    if (type(value) is not str or not 16 <= len(value) <= maximum
            or not re.fullmatch(r"[A-Za-z0-9_-]+", value)):
        raise HardenedRefreshError(code)
    return value


def _container_id(value: Any, code: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise HardenedRefreshError(code)
    return value


def _exported_snapshot(value: Any) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or not re.fullmatch(r"[0-9A-Fa-f:-]+", value)):
        raise HardenedRefreshError("INVALID_EXPORTED_SNAPSHOT")
    return value


def _validate_credential_owner_fd(fd: int) -> os.stat_result:
    try:
        metadata = os.fstat(fd)
        seals = fcntl.fcntl(fd, fcntl.F_GET_SEALS)
        descriptor_flags = fcntl.fcntl(fd, fcntl.F_GETFD)
    except (OSError, TypeError, ValueError) as exc:
        raise HardenedRefreshError("INVALID_CREDENTIAL_FD") from exc
    if (not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 0
            or not 1 <= metadata.st_size <= MAX_CREDENTIAL_BYTES
            or seals & REQUIRED_CREDENTIAL_SEALS
               != REQUIRED_CREDENTIAL_SEALS
            or descriptor_flags & fcntl.FD_CLOEXEC == 0):
        raise HardenedRefreshError("INVALID_CREDENTIAL_FD")
    return metadata


def build_plan(*, run_nonce: str, artifact_sha256: Mapping[str, str],
               registry_observed_at: str) -> dict[str, Any]:
    """Build the one closed, non-authorizing local runbook plan."""
    _token(run_nonce, "INVALID_RUN_NONCE")
    if set(artifact_sha256) != set(ARTIFACT_KEYS):
        raise HardenedRefreshError("INVALID_ARTIFACT_SET")
    artifacts = {key: _digest(artifact_sha256[key], "INVALID_ARTIFACT_DIGEST")
                 for key in ARTIFACT_KEYS}
    plan = {
        "schemaVersion": PLAN_SCHEMA,
        "route": ROUTE,
        "operation": "ONE_BOUNDED_READ_ONLY_SOURCE_TO_DISPOSABLE_RESTORE",
        "runNonce": run_nonce,
        "registryObservation": {
            "observedAt": registry_observed_at,
            "tag": "docker.io/library/postgres:17.11-alpine3.24",
            "indexDigest": IMAGE_INDEX,
            "linuxAmd64ChildDigest": IMAGE_CHILD,
            "configDigest": IMAGE_CONFIG,
            "sourceRevision": IMAGE_SOURCE_REVISION,
            "versionAnnotation": "17.11-alpine3.24",
            "freshRevalidationRequiredAtAuthorization": True,
            "digestPinDoesNotProveFutureSecurity": True,
        },
        "client": {
            "imageRef": IMAGE_REF,
            "platform": "linux/amd64",
            "expectedPgDumpVersion": PG_DUMP_VERSION,
            "minimumVersionNum": 170011,
            "pullPolicy": "never",
            "networkForVersionPreflight": "none",
            "networkForDump": "container:ATTESTED_SOURCE_CONTAINER_ID",
            "sourceNetworkNamespaceShared": True,
            "egressIsolationProven": False,
            "readOnlyRootFilesystem": True,
            "uidGid": "70:70",
            "capDropAll": True,
            "noNewPrivileges": True,
        },
        "source": {
            "container": SOURCE_CONTAINER,
            "database": SOURCE_DATABASE,
            "host": "127.0.0.1",
            "port": 5432,
            "principal": RUNNER_ROLE,
            "expectedServerMajor": 17,
            "expectedTableCount": 54,
            "expectedColumnCount": 423,
            "expectedColumnCatalogSha256":
                "adf9ef068c9778f3173bac3d824606ab4796b67f5647df770cbbc8be4ad53f99",
            "expectedSequenceCount": 29,
            "sequencePrivilegeProfile": "SELECT_ONLY_FOR_PG_DUMP_STATE",
            "requireNoRoleMemberships": True,
            "requireNoRlsTables": True,
            "requireNoLargeObjects": True,
            "transaction": "REPEATABLE READ READ ONLY",
            "dormantPrincipalProvisioningImplemented": True,
            "activePrincipalProvisioningImplemented": True,
            "requireContainerIdBinding": True,
            "runtimeFrozenPlanBindingRequired": True,
            "sourceSystemIdentifierAttested": True,
            "sourceNetnsInodeAttested": True,
        },
        "command": {
            "lockWaitTimeoutMs": 5000,
            "overallDeadlineSeconds": 180,
            "maximumArchiveBytes": 16 * 1024 * 1024,
            "maximumStderrBytes": 64 * 1024,
            "format": "custom",
            "publicSchemaOnly": True,
            "largeObjectsExcluded": True,
            "dumpNoOwnerOptionPresent": True,
            "dumpNoPrivilegesOptionPresent": True,
            "restoreNoOwnerRequired": True,
            "restoreNoPrivilegesRequired": True,
            "noPasswordPrompt": True,
            "noSyncForbidden": True,
            "warningPolicy": "FAIL_CLOSED_ON_ANY_STDERR_OR_WARNING",
            "helperAbsoluteLeaseDeadline": True,
            "transactionTimeoutBoundToLease": True,
            "closeProtocolNonblockingDeadline": True,
        },
        "credentials": {
            "transport": "TWO_INDEPENDENT_SEALED_MEMFD_PGPASS_FDS",
            "sourcePassfilePath": "/proc/self/fd/INHERITED",
            "dumpPassfilePath": "/run/b64/pgpass",
            "secretInArgv": False,
            "secretInEnvironment": False,
            "secretInLogsOrReceipt": False,
            "plaintextPasswordSentToServer": False,
            "requiredAuthenticationMethod": "scram-sha-256",
            "scramIterationsFromExactServerSetting": True,
            "ambientLibpqEnvironmentForbidden": True,
            "serializedByAdvisoryLock": True,
            "mutationUsesAdvisoryLockBackend": True,
            "lockBackendIdleExpiryBoundToLease": True,
            "reconcileOnAbnormalSupervisorExit": False,
            "watchdogRequiredBeforeProductionActivation": True,
            "revokeTerminatesAllDedicatedRoleSessions": True,
            "revokePrecedesBroadPostVerification": True,
            "passfileMode": "0600",
            "memfdSealsRequired": True,
            "dumpTmpfsOnly": True,
        },
        "artifactsSha256": artifacts,
        "transients": list(TRANSIENT_NAMES),
        "cleanup": {
            "alwaysFinally": True,
            "inodeBoundAbsenceVerificationRequired": True,
            "dumpContainerIdBound": True,
            "restoreContainerIdBound": True,
            "absenceReceiptRequired": True,
            "absenceScope": "REGISTERED_WORKSPACE_PATHS_AND_ID_BOUND_CONTAINERS_ONLY",
            "uncertainCleanupForbidsRetry": True,
        },
        "authentication": {
            "exactRunbookHashBindingRequired": True,
            "productionRegistryRequired": True,
            "trustedTimeRequired": True,
            "freshRevocationRequired": True,
            "durableAtomicReplayRequired": True,
            "freshOwnerAndIndependentReviewerRequired": True,
            "implementedByThisModule": False,
        },
        "authority": dict(AUTHORITY),
    }
    validate_plan(plan)
    return plan


def validate_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schemaVersion", "route", "operation", "runNonce",
        "registryObservation", "client", "source", "command", "credentials",
        "artifactsSha256", "transients", "cleanup", "authentication", "authority",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise HardenedRefreshError("INVALID_PLAN_SHAPE")
    if (value.get("schemaVersion") != PLAN_SCHEMA or value.get("route") != ROUTE
            or value.get("operation") != "ONE_BOUNDED_READ_ONLY_SOURCE_TO_DISPOSABLE_RESTORE"):
        raise HardenedRefreshError("INVALID_PLAN_IDENTITY")
    _token(value.get("runNonce"), "INVALID_RUN_NONCE")
    registry = value.get("registryObservation")
    if not isinstance(registry, Mapping) or not _exact(registry, {
        "observedAt": registry.get("observedAt"),
        "tag": "docker.io/library/postgres:17.11-alpine3.24",
        "indexDigest": IMAGE_INDEX,
        "linuxAmd64ChildDigest": IMAGE_CHILD,
        "configDigest": IMAGE_CONFIG,
        "sourceRevision": IMAGE_SOURCE_REVISION,
        "versionAnnotation": "17.11-alpine3.24",
        "freshRevalidationRequiredAtAuthorization": True,
        "digestPinDoesNotProveFutureSecurity": True,
    }) or type(registry.get("observedAt")) is not str or not re.fullmatch(
            r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ", registry["observedAt"]):
        raise HardenedRefreshError("INVALID_REGISTRY_OBSERVATION")
    if not _exact(value.get("client"), {
        "imageRef": IMAGE_REF, "platform": "linux/amd64",
        "expectedPgDumpVersion": PG_DUMP_VERSION, "minimumVersionNum": 170011,
        "pullPolicy": "never", "networkForVersionPreflight": "none",
        "networkForDump": "container:ATTESTED_SOURCE_CONTAINER_ID",
        "sourceNetworkNamespaceShared": True, "egressIsolationProven": False,
        "readOnlyRootFilesystem": True, "uidGid": "70:70",
        "capDropAll": True, "noNewPrivileges": True,
    }):
        raise HardenedRefreshError("INVALID_CLIENT_PROFILE")
    if not _exact(value.get("source"), {
        "container": SOURCE_CONTAINER, "database": SOURCE_DATABASE,
        "host": "127.0.0.1", "port": 5432, "principal": RUNNER_ROLE,
        "expectedServerMajor": 17, "expectedTableCount": 54,
        "expectedColumnCount": 423,
        "expectedColumnCatalogSha256":
            "adf9ef068c9778f3173bac3d824606ab4796b67f5647df770cbbc8be4ad53f99",
        "expectedSequenceCount": 29,
        "sequencePrivilegeProfile": "SELECT_ONLY_FOR_PG_DUMP_STATE",
        "requireNoRoleMemberships": True, "requireNoRlsTables": True,
        "requireNoLargeObjects": True,
        "transaction": "REPEATABLE READ READ ONLY",
        "dormantPrincipalProvisioningImplemented": True,
        "activePrincipalProvisioningImplemented": True,
        "requireContainerIdBinding": True,
        "runtimeFrozenPlanBindingRequired": True,
        "sourceSystemIdentifierAttested": True,
        "sourceNetnsInodeAttested": True,
    }):
        raise HardenedRefreshError("INVALID_SOURCE_PROFILE")
    if not _exact(value.get("command"), {
        "lockWaitTimeoutMs": 5000, "overallDeadlineSeconds": 180,
        "maximumArchiveBytes": 16 * 1024 * 1024,
        "maximumStderrBytes": 64 * 1024, "format": "custom",
        "publicSchemaOnly": True, "largeObjectsExcluded": True,
        "dumpNoOwnerOptionPresent": True,
        "dumpNoPrivilegesOptionPresent": True,
        "restoreNoOwnerRequired": True, "restoreNoPrivilegesRequired": True,
        "noPasswordPrompt": True,
        "noSyncForbidden": True,
        "warningPolicy": "FAIL_CLOSED_ON_ANY_STDERR_OR_WARNING",
        "helperAbsoluteLeaseDeadline": True,
        "transactionTimeoutBoundToLease": True,
        "closeProtocolNonblockingDeadline": True,
    }):
        raise HardenedRefreshError("INVALID_COMMAND_PROFILE")
    if not _exact(value.get("credentials"), {
        "transport": "TWO_INDEPENDENT_SEALED_MEMFD_PGPASS_FDS",
        "sourcePassfilePath": "/proc/self/fd/INHERITED",
        "dumpPassfilePath": "/run/b64/pgpass", "secretInArgv": False,
        "secretInEnvironment": False, "secretInLogsOrReceipt": False,
        "plaintextPasswordSentToServer": False,
        "requiredAuthenticationMethod": "scram-sha-256",
        "scramIterationsFromExactServerSetting": True,
        "ambientLibpqEnvironmentForbidden": True,
        "serializedByAdvisoryLock": True,
        "mutationUsesAdvisoryLockBackend": True,
        "lockBackendIdleExpiryBoundToLease": True,
        "reconcileOnAbnormalSupervisorExit": False,
        "watchdogRequiredBeforeProductionActivation": True,
        "revokeTerminatesAllDedicatedRoleSessions": True,
        "revokePrecedesBroadPostVerification": True,
        "passfileMode": "0600", "memfdSealsRequired": True,
        "dumpTmpfsOnly": True,
    }):
        raise HardenedRefreshError("INVALID_CREDENTIAL_PROFILE")
    artifacts = value.get("artifactsSha256")
    if not isinstance(artifacts, Mapping) or set(artifacts) != set(ARTIFACT_KEYS):
        raise HardenedRefreshError("INVALID_ARTIFACT_SET")
    for digest in artifacts.values():
        _digest(digest, "INVALID_ARTIFACT_DIGEST")
    if value.get("transients") != list(TRANSIENT_NAMES):
        raise HardenedRefreshError("INVALID_TRANSIENT_INVENTORY")
    if not _exact(value.get("cleanup"), {
        "alwaysFinally": True, "inodeBoundAbsenceVerificationRequired": True,
        "dumpContainerIdBound": True, "restoreContainerIdBound": True,
        "absenceReceiptRequired": True,
        "absenceScope": "REGISTERED_WORKSPACE_PATHS_AND_ID_BOUND_CONTAINERS_ONLY",
        "uncertainCleanupForbidsRetry": True,
    }):
        raise HardenedRefreshError("INVALID_CLEANUP_PROFILE")
    if not _exact(value.get("authentication"), {
        "exactRunbookHashBindingRequired": True,
        "productionRegistryRequired": True, "trustedTimeRequired": True,
        "freshRevocationRequired": True, "durableAtomicReplayRequired": True,
        "freshOwnerAndIndependentReviewerRequired": True,
        "implementedByThisModule": False,
    }):
        raise HardenedRefreshError("INVALID_AUTHENTICATION_PROFILE")
    if not _exact(value.get("authority"), AUTHORITY):
        raise HardenedRefreshError("INVALID_AUTHORITY")
    return json.loads(_canonical(dict(value)))


def compile_client_preflight(plan: Mapping[str, Any]) -> list[str]:
    validate_plan(plan)
    return [
        "docker", "run", "--rm", "--pull=never", "--platform=linux/amd64",
        "--network=none", "--read-only", "--user=70:70", "--cap-drop=ALL",
        "--security-opt=no-new-privileges=true", "--pids-limit=32",
        "--memory=128m", "--cpus=1", IMAGE_REF, "pg_dump", "--version",
    ]


def compile_dump_command(plan: Mapping[str, Any], snapshot: str,
                         source_container_id: str, *,
                         transaction_timeout_ms: int,
                         lease_not_after_epoch: int) -> list[str]:
    checked = validate_plan(plan)
    checked_snapshot = _exported_snapshot(snapshot)
    source_id = _container_id(source_container_id, "INVALID_SOURCE_CONTAINER_ID")
    if (type(transaction_timeout_ms) is not int
            or not 1 <= transaction_timeout_ms
            <= checked["command"]["overallDeadlineSeconds"] * 1000):
        raise HardenedRefreshError("INVALID_DUMP_TRANSACTION_TIMEOUT")
    now_epoch = int(time.time())
    if (type(lease_not_after_epoch) is not int
            or not 1 <= lease_not_after_epoch - now_epoch
            <= checked["command"]["overallDeadlineSeconds"] + 1
            or transaction_timeout_ms
            > (lease_not_after_epoch - now_epoch) * 1000):
        raise HardenedRefreshError("INVALID_DUMP_LEASE_DEADLINE")
    wrapper = (
        "umask 077; NOW=$(date +%s); "
        "REMAINING=$((B64_LEASE_NOT_AFTER_EPOCH-NOW)); "
        "test \"$REMAINING\" -gt 0; "
        "IFS= read -r B64_PASSLINE || test -n \"$B64_PASSLINE\"; "
        "test -n \"$B64_PASSLINE\"; "
        "printf '%s\\n' \"$B64_PASSLINE\" > /run/b64/pgpass; "
        "unset B64_PASSLINE; "
        "exec timeout -s KILL \"${REMAINING}s\" pg_dump \"$@\""
    )
    return [
        "docker", "run", "-i", "--rm", "--pull=never", "--platform=linux/amd64",
        "--name=b64-064a-pgdump-one-shot",
        "--label=org.obsidian.route=e0-e0.3-b5.3-064a",
        f"--label=org.obsidian.run-nonce={checked['runNonce']}",
        f"--network=container:{source_id}", "--read-only", "--user=70:70",
        "--cap-drop=ALL", "--security-opt=no-new-privileges=true",
        "--pids-limit=64", "--memory=256m", "--cpus=1",
        "--tmpfs=/run/b64:rw,noexec,nosuid,nodev,size=64k,mode=0700,uid=70,gid=70",
        "--env=PGPASSFILE=/run/b64/pgpass", "--env=LC_ALL=C",
        f"--env=PGOPTIONS=-c transaction_timeout={transaction_timeout_ms}ms",
        f"--env=B64_LEASE_NOT_AFTER_EPOCH={lease_not_after_epoch}",
        IMAGE_REF, "sh", "-euc", wrapper, "b64-pg-dump",
        "--dbname=postgresql://obsidian_b64_snapshot_reader@127.0.0.1:5432/"
        "obsidian_exchange?sslmode=disable&require_auth=scram-sha-256&"
        "connect_timeout=5&target_session_attrs=any",
        "--format=custom", "--no-owner",
        "--no-privileges", "--no-password", "--lock-wait-timeout=5000",
        "--schema=public", "--no-large-objects", "--strict-names",
        f"--snapshot={checked_snapshot}",
    ]


def validate_source_attestation(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "database", "serverMajor", "clusterSha256", "transactionReadOnly",
        "transactionIsolation", "snapshotReaderVerifierStatus",
        "snapshotReaderProfile", "snapshotReaderInventorySha256",
        "aclVerifiedInExportingTransaction", "exclusiveDatabaseConnectivity",
        "hbaFirstMatchAttested", "roleCredentialAuthenticated",
        "credentialExpiryBound", "credentialNotAfterEpoch",
        "credentialRevocationPending",
        "sourceTableFingerprints", "sourceTableFingerprintSha256",
        "sourceCatalogFingerprints", "sourceCatalogFingerprintSha256",
        "sourceSystemIdentifier",
        "sourceContainerId", "sourceContainerImageSha256",
        "sessionUser", "currentUser", "roleCanLogin", "roleSuperuser",
        "roleCreateDb", "roleCreateRole", "roleInherit", "roleReplication",
        "roleBypassRls", "roleConnectionLimit", "roleSettingsMatch",
        "roleMemberships", "databaseConnect", "databaseCreate", "databaseTemp",
        "schemaUsage", "schemaCreate", "publicTables", "selectablePublicTables",
        "publicColumns", "columnCatalogSha256",
        "publicSequences", "selectablePublicSequences", "rlsTables", "largeObjects",
        "tableWritePrivileges", "sequenceUsageOrUpdatePrivileges",
        "userFunctionExecutePrivileges", "otherSchemaPrivileges",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise HardenedRefreshError("INVALID_SOURCE_ATTESTATION_SHAPE")
    if (value["database"] != SOURCE_DATABASE or value["serverMajor"] != 17
            or _container_id(value["sourceContainerId"], "INVALID_SOURCE_CONTAINER_ID")
            != value["sourceContainerId"]
            or _digest(value["sourceContainerImageSha256"], "INVALID_SOURCE_IMAGE_DIGEST")
            != value["sourceContainerImageSha256"]
            or _digest(value["clusterSha256"], "INVALID_CLUSTER_DIGEST") != value["clusterSha256"]
            or value["transactionReadOnly"] is not True
            or value["transactionIsolation"] != "repeatable read"
            or value["snapshotReaderVerifierStatus"] != "match"
            or value["snapshotReaderProfile"] != SNAPSHOT_READER_PROFILE
            or value["snapshotReaderInventorySha256"]
            != SNAPSHOT_READER_INVENTORY_SHA256
            or any(value[key] is not True for key in (
                "aclVerifiedInExportingTransaction",
                "exclusiveDatabaseConnectivity", "hbaFirstMatchAttested",
                "roleCredentialAuthenticated", "credentialExpiryBound",
                "credentialRevocationPending"))
            or type(value["credentialNotAfterEpoch"]) is not int
            or not 1 <= value["credentialNotAfterEpoch"] - int(time.time())
               <= 181
            or value["sessionUser"] != RUNNER_ROLE or value["currentUser"] != RUNNER_ROLE
            or value["roleCanLogin"] is not True
            or type(value["roleConnectionLimit"]) is not int
            or value["roleConnectionLimit"] != 2
            or value["roleSettingsMatch"] is not True
            or any(value[key] is not False for key in (
                "roleSuperuser", "roleCreateDb", "roleCreateRole", "roleInherit",
                "roleReplication",
                "roleBypassRls", "databaseCreate", "databaseTemp", "schemaCreate"))
            or value["roleMemberships"] != [] or value["databaseConnect"] is not True
            or value["schemaUsage"] is not True
            or type(value["publicTables"]) is not int or value["publicTables"] != 54
            or type(value["publicColumns"]) is not int
            or value["publicColumns"] != 423
            or value["columnCatalogSha256"]
            != "adf9ef068c9778f3173bac3d824606ab4796b67f5647df770cbbc8be4ad53f99"
            or type(value["selectablePublicTables"]) is not int
            or value["selectablePublicTables"] != value["publicTables"]
            or type(value["publicSequences"]) is not int
            or value["publicSequences"] != 29
            or type(value["selectablePublicSequences"]) is not int
            or value["selectablePublicSequences"] != value["publicSequences"]
            or any(type(value[key]) is not int or value[key] != 0 for key in (
                "rlsTables", "largeObjects", "tableWritePrivileges",
                "sequenceUsageOrUpdatePrivileges", "userFunctionExecutePrivileges",
                "otherSchemaPrivileges"))):
        raise HardenedRefreshError("LEAST_PRIVILEGE_ATTESTATION_FAILED")
    tables = value["sourceTableFingerprints"]
    catalog = value["sourceCatalogFingerprints"]
    if (type(tables) is not list or len(tables) != 54
            or type(catalog) is not list or len(catalog) != 13
            or type(value["sourceSystemIdentifier"]) is not str
            or re.fullmatch(r"[0-9]{8,32}", value["sourceSystemIdentifier"])
            is None):
        raise HardenedRefreshError("SOURCE_FINGERPRINT_ATTESTATION_FAILED")
    for row in tables:
        if (type(row) is not list or len(row) != 3
                or type(row[0]) is not str or type(row[1]) is not int
                or row[1] < 0 or type(row[2]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", row[2]) is None):
            raise HardenedRefreshError(
                "SOURCE_FINGERPRINT_ATTESTATION_FAILED"
            )
    for row in catalog:
        if (type(row) is not list or len(row) != 4
                or row[0] != "b64-catalog-security-fingerprint.v2"
                or type(row[1]) is not str or type(row[2]) is not int
                or row[2] < 0 or type(row[3]) is not str
                or re.fullmatch(r"[0-9a-f]{64}", row[3]) is None):
            raise HardenedRefreshError(
                "SOURCE_FINGERPRINT_ATTESTATION_FAILED"
            )
    if (_sha_bytes(_canonical(tables))
            != value["sourceTableFingerprintSha256"]
            or _sha_bytes(_canonical(catalog))
            != value["sourceCatalogFingerprintSha256"]):
        raise HardenedRefreshError("SOURCE_FINGERPRINT_ATTESTATION_FAILED")
    return json.loads(_canonical(dict(value)))


def _file_digest(fd: int) -> tuple[int, str]:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return size, digest.hexdigest()


def _safe_error(exc: BaseException) -> str:
    trusted_error_module = exc.__class__.__module__ in {
        __name__, "b64_064a_activation_executor",
        "b64_snapshot_reader_runtime",
    }
    if (trusted_error_module
            and isinstance(exc, RuntimeError)
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        return "CANCELLED"
    return "UNEXPECTED_FAILURE"


def _execute_bound(plan: Mapping[str, Any], workspace_parent: Path, *,
                   source: SourceAdapter, dump: DumpAdapter,
                   restore: RestoreAdapter, source_secret_fd: int,
                   dump_secret_fd: int,
                   expected_contact: tuple[bool, bool, bool],
                   absolute_deadline: float | None = None,
                   monotonic: Callable[[], float] = time.monotonic,
                   fault_hook: Callable[[str], None] | None = None,
                   workspace_registered:
                   Callable[[int, int], None] | None = None) \
        -> dict[str, Any]:
    plan_bytes = _canonical(validate_plan(plan))
    checked = json.loads(plan_bytes)
    plan_sha256 = _sha_bytes(plan_bytes)
    observed_contact = tuple(
        getattr(adapter, "production_contact", None)
        for adapter in (source, dump, restore)
    )
    if observed_contact != expected_contact:
        raise HardenedRefreshError("ADAPTER_CONTACT_PROFILE_MISMATCH")
    source_secret_owner_fd = -1
    dump_secret_owner_fd = -1
    try:
        source_secret_owner_fd = os.dup(source_secret_fd)
        source_secret_stat = _validate_credential_owner_fd(
            source_secret_owner_fd
        )
        dump_secret_owner_fd = os.dup(dump_secret_fd)
        dump_secret_stat = _validate_credential_owner_fd(
            dump_secret_owner_fd
        )
    except BaseException:
        for owned_fd in (source_secret_owner_fd, dump_secret_owner_fd):
            if owned_fd >= 0:
                os.close(owned_fd)
        raise
    if ((source_secret_stat.st_dev, source_secret_stat.st_ino)
            == (dump_secret_stat.st_dev, dump_secret_stat.st_ino)):
        os.close(source_secret_owner_fd)
        os.close(dump_secret_owner_fd)
        raise HardenedRefreshError("CREDENTIAL_FDS_NOT_INDEPENDENT")
    parent_flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(workspace_parent, parent_flags)
    except BaseException:
        os.close(source_secret_owner_fd)
        os.close(dump_secret_owner_fd)
        raise
    directory_fd = -1
    archive_fd = -1
    workspace_created = False
    workspace_inode: tuple[int, int] | None = None
    workspace_binding_fd = -1
    workspace_name = f"b64-064a-{checked['runNonce']}"
    registered: dict[str, tuple[int, int, int, int]] = {}
    error_code: str | None = None
    result_status = "FAILED"
    archive_size = 0
    archive_sha: str | None = None
    equality_sha: str | None = None
    source_closed = False
    credential_revocation_attested = False
    source_invoked = False
    source_container_id: str | None = None
    dump_container_id: str | None = None
    restore_container_id: str | None = None
    dump_invoked = False
    restore_invoked = False
    dump_cleanup = {"containerId": None, "containerAbsent": False,
                    "tmpfsReleased": False}
    restore_cleanup = {"containerId": None, "containerAbsent": False,
                       "tmpfsReleased": False}
    cleanup_uncertain = False
    workspace_absent = False
    started = monotonic()
    local_deadline = started + checked["command"]["overallDeadlineSeconds"]
    if absolute_deadline is not None:
        if (type(absolute_deadline) is not float
                or not started < absolute_deadline <= local_deadline + 1):
            raise HardenedRefreshError("INVALID_ABSOLUTE_DEADLINE")
        deadline = min(local_deadline, absolute_deadline)
    else:
        deadline = local_deadline

    def trip(stage: str) -> None:
        if monotonic() > deadline:
            raise HardenedRefreshError("OVERALL_DEADLINE_EXCEEDED")
        if fault_hook is not None:
            fault_hook(stage)

    def adapter_plan() -> dict[str, Any]:
        return json.loads(plan_bytes)

    def ensure_plan_unchanged(candidate: Mapping[str, Any]) -> None:
        if _canonical(candidate) != plan_bytes:
            raise HardenedRefreshError("ADAPTER_MUTATED_PLAN")

    def close_guarded(fd: int) -> bool:
        try:
            os.close(fd)
            return True
        except BaseException:
            return False

    def cleanup_result(adapter: Any, expected_id: str | None,
                       invoked: bool, target_safe: bool) -> dict[str, Any]:
        nonlocal cleanup_uncertain
        if not invoked:
            if expected_id is not None:
                cleanup_uncertain = True
                return {"containerId": expected_id, "containerAbsent": False,
                        "tmpfsReleased": False}
            return {"containerId": None, "containerAbsent": True,
                    "tmpfsReleased": True}
        if invoked and not target_safe:
            cleanup_uncertain = True
            return {"containerId": expected_id, "containerAbsent": False,
                    "tmpfsReleased": False}
        try:
            observed = adapter.cleanup(expected_id)
        except BaseException:
            cleanup_uncertain = True
            return {"containerId": expected_id, "containerAbsent": False,
                    "tmpfsReleased": False}
        observed_id = observed.get("containerId") if isinstance(observed, Mapping) else None
        id_is_exact = (observed_id is None if expected_id is None else (
            type(observed_id) is str
            and re.fullmatch(r"[0-9a-f]{64}", observed_id) is not None
            and observed_id == expected_id))
        if (not isinstance(observed, Mapping)
                or set(observed) != {"containerId", "containerAbsent", "tmpfsReleased"}
                or not id_is_exact
                or type(observed.get("containerAbsent")) is not bool
                or type(observed.get("tmpfsReleased")) is not bool
                or (invoked and expected_id is None)):
            cleanup_uncertain = True
            return {"containerId": expected_id, "containerAbsent": False,
                    "tmpfsReleased": False}
        return dict(observed)

    try:
        parent_stat = os.fstat(parent_fd)
        if (parent_stat.st_uid != os.geteuid()
                or stat.S_IMODE(parent_stat.st_mode) != 0o700):
            raise HardenedRefreshError("UNSAFE_WORKSPACE_PARENT")
        os.mkdir(workspace_name, 0o700, dir_fd=parent_fd)
        workspace_created = True
        trip("WORKSPACE_CREATED_UNBOUND")
        directory_fd = os.open(workspace_name, parent_flags, dir_fd=parent_fd)
        directory_stat = os.fstat(directory_fd)
        if directory_stat.st_uid != os.geteuid() or stat.S_IMODE(directory_stat.st_mode) != 0o700:
            raise HardenedRefreshError("UNSAFE_WORKSPACE")
        workspace_inode = (directory_stat.st_dev, directory_stat.st_ino)
        workspace_binding_fd = os.dup(directory_fd)
        if workspace_registered is not None:
            workspace_registered(*workspace_inode)
        trip("WORKSPACE_CREATED")
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        for name in TRANSIENT_NAMES:
            fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                close_guarded(fd)
                raise HardenedRefreshError("UNSAFE_TRANSIENT_INODE")
            if name == "snapshot.dump":
                try:
                    binding_fd = os.dup(fd)
                except BaseException:
                    close_guarded(fd)
                    raise
                archive_fd = fd
            else:
                binding_fd = fd
            registered[name] = (
                info.st_dev, info.st_ino, info.st_nlink, binding_fd)
        trip("TRANSIENTS_REGISTERED")
        source_plan = adapter_plan()
        source_adapter_secret_fd = os.dup(source_secret_owner_fd)
        try:
            source_invoked = True
            source_attestation, snapshot = source.open(
                source_plan, source_adapter_secret_fd, deadline)
        finally:
            close_guarded(source_adapter_secret_fd)
        ensure_plan_unchanged(source_plan)
        source_evidence = validate_source_attestation(source_attestation)
        source_container_id = source_evidence["sourceContainerId"]
        checked_snapshot = _exported_snapshot(snapshot)
        trip("SOURCE_ATTESTED")
        dump_plan = adapter_plan()
        dump_fd = os.dup(archive_fd)
        dump_adapter_secret_fd = -1
        try:
            dump_adapter_secret_fd = os.dup(dump_secret_owner_fd)
            dump_invoked = True
            dump_result = dump.run(
                dump_plan, checked_snapshot, source_container_id,
                source_evidence["credentialNotAfterEpoch"], dump_fd,
                dump_adapter_secret_fd, deadline)
        finally:
            close_guarded(dump_fd)
            if dump_adapter_secret_fd >= 0:
                close_guarded(dump_adapter_secret_fd)
        ensure_plan_unchanged(dump_plan)
        if not isinstance(dump_result, Mapping) or set(dump_result) != {
            "clientVersion", "exitCode", "stderrBytes", "stderrSha256",
            "warningCount", "sourceContainerId", "containerId",
        }:
            raise HardenedRefreshError("INVALID_DUMP_ATTESTATION")
        dump_container_id = _container_id(
            dump_result["containerId"], "INVALID_CONTAINER_ID")
        dump_source_container_id = _container_id(
            dump_result["sourceContainerId"], "INVALID_SOURCE_CONTAINER_ID")
        if dump_container_id == source_container_id:
            raise HardenedRefreshError("CONTAINER_ID_COLLISION")
        if (type(dump_result["clientVersion"]) is not str
                or dump_result["clientVersion"] != PG_DUMP_VERSION
                or type(dump_result["exitCode"]) is not int or dump_result["exitCode"] != 0
                or type(dump_result["stderrBytes"]) is not int
                or dump_result["stderrBytes"] != 0
                or type(dump_result["warningCount"]) is not int
                or dump_result["warningCount"] != 0
                or dump_source_container_id != source_container_id
                or _digest(dump_result["stderrSha256"], "INVALID_STDERR_DIGEST")
                != _sha_bytes(b"")
                or dump_container_id != dump_result["containerId"]):
            raise HardenedRefreshError("DUMP_ATTESTATION_FAILED")
        archive_size, archive_sha = _file_digest(archive_fd)
        if not 0 < archive_size <= checked["command"]["maximumArchiveBytes"]:
            raise HardenedRefreshError("ARCHIVE_SIZE_INVALID")
        trip("DUMP_VERIFIED")
        restore_plan = adapter_plan()
        restore_archive_fd = -1
        restore_workspace_fd = -1
        try:
            restore_archive_fd = os.dup(archive_fd)
            restore_workspace_fd = os.dup(directory_fd)
            restore_invoked = True
            equality = restore.verify(
                restore_plan, restore_archive_fd, restore_workspace_fd,
                {
                    "tables": source_evidence["sourceTableFingerprints"],
                    "tableSha256": source_evidence[
                        "sourceTableFingerprintSha256"
                    ],
                    "catalog": source_evidence[
                        "sourceCatalogFingerprints"
                    ],
                    "catalogSha256": source_evidence[
                        "sourceCatalogFingerprintSha256"
                    ],
                    "systemIdentifier": source_evidence[
                        "sourceSystemIdentifier"
                    ],
                },
                deadline,
            )
        finally:
            if restore_archive_fd >= 0:
                close_guarded(restore_archive_fd)
            if restore_workspace_fd >= 0:
                close_guarded(restore_workspace_fd)
        ensure_plan_unchanged(restore_plan)
        if not isinstance(equality, Mapping) or set(equality) != {
            "tables", "catalogSections", "tableMatch", "catalogMatch",
            "restoreClusterDistinct", "sequenceRuntimeStateCompared",
            "restoreNoOwnerApplied", "restoreNoPrivilegesApplied",
            "containerId",
        }:
            raise HardenedRefreshError("RESTORE_EQUALITY_FAILED")
        restore_container_id = _container_id(
            equality.get("containerId"), "INVALID_RESTORE_CONTAINER_ID")
        if restore_container_id in (source_container_id, dump_container_id):
            raise HardenedRefreshError("CONTAINER_ID_COLLISION")
        equality_summary = {key: equality[key] for key in (
            "tables", "catalogSections", "tableMatch", "catalogMatch",
            "restoreClusterDistinct", "sequenceRuntimeStateCompared",
            "restoreNoOwnerApplied", "restoreNoPrivilegesApplied")}
        if not _exact(equality_summary, {
            "tables": 54, "catalogSections": 13, "tableMatch": True,
            "catalogMatch": True, "restoreClusterDistinct": True,
            "sequenceRuntimeStateCompared": False, "restoreNoOwnerApplied": True,
            "restoreNoPrivilegesApplied": True,
        }):
            raise HardenedRefreshError("RESTORE_EQUALITY_FAILED")
        equality_sha = _sha_bytes(_canonical(equality_summary))
        trip("RESTORE_EQUALITY_VERIFIED")
        result_status = "COMPLETED"
    except BaseException as exc:
        error_code = _safe_error(exc)
    finally:
        if source_invoked:
            try:
                close_evidence = source.close()
                if (not isinstance(close_evidence, Mapping)
                        or not _exact(close_evidence, {
                            "sourceSessionClosed": True,
                            "credentialRevocationAttested": True,
                            "loginState": "DISABLED",
                            "credentialState": "ABSENT",
                            "activeSessions": 0,
                        })):
                    raise HardenedRefreshError(
                        "INVALID_SOURCE_CLOSE_ATTESTATION"
                    )
                source_closed = True
                credential_revocation_attested = True
            except BaseException:
                source_closed = False
                credential_revocation_attested = False
        else:
            source_closed = True
        dump_target_safe = (dump_container_id is not None
                            and dump_container_id != source_container_id
                            and dump_container_id != restore_container_id)
        restore_target_safe = (restore_container_id is not None
                               and restore_container_id != source_container_id
                               and restore_container_id != dump_container_id)
        dump_cleanup = cleanup_result(
            dump, dump_container_id, dump_invoked, dump_target_safe)
        restore_cleanup = cleanup_result(
            restore, restore_container_id, restore_invoked, restore_target_safe)
        if archive_fd >= 0:
            if not close_guarded(archive_fd):
                cleanup_uncertain = True
        if directory_fd >= 0:
            for name, expected_binding in registered.items():
                expected_inode = expected_binding[:3]
                binding_fd = expected_binding[3]
                try:
                    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if ((info.st_dev, info.st_ino, info.st_nlink) != expected_inode
                            or not stat.S_ISREG(info.st_mode)):
                        cleanup_uncertain = True
                        continue
                    os.unlink(name, dir_fd=directory_fd)
                    bound = os.fstat(binding_fd)
                    if ((bound.st_dev, bound.st_ino) != expected_inode[:2]
                            or bound.st_nlink != 0):
                        cleanup_uncertain = True
                except FileNotFoundError:
                    cleanup_uncertain = True
                except BaseException:
                    cleanup_uncertain = True
                finally:
                    if not close_guarded(binding_fd):
                        cleanup_uncertain = True
            try:
                current_directory = os.fstat(directory_fd)
                if workspace_inode != (current_directory.st_dev, current_directory.st_ino):
                    cleanup_uncertain = True
                os.fsync(directory_fd)
            except BaseException:
                cleanup_uncertain = True
        if workspace_created:
            try:
                named_directory = os.stat(
                    workspace_name, dir_fd=parent_fd, follow_symlinks=False)
                if (workspace_inode != (named_directory.st_dev, named_directory.st_ino)
                        or not stat.S_ISDIR(named_directory.st_mode)):
                    cleanup_uncertain = True
                elif not close_guarded(directory_fd):
                    directory_fd = -1
                    cleanup_uncertain = True
                else:
                    directory_fd = -1
                    os.rmdir(workspace_name, dir_fd=parent_fd)
                    workspace_removal_durable = False
                    try:
                        os.fsync(parent_fd)
                        workspace_removal_durable = True
                    except BaseException:
                        cleanup_uncertain = True
                    bound_directory = os.fstat(workspace_binding_fd)
                    bound_directory_absent = (
                        workspace_inode == (bound_directory.st_dev, bound_directory.st_ino)
                        and bound_directory.st_nlink == 0)
                    try:
                        os.stat(workspace_name, dir_fd=parent_fd, follow_symlinks=False)
                        cleanup_uncertain = True
                    except FileNotFoundError:
                        if (bound_directory_absent
                                and workspace_removal_durable):
                            workspace_absent = True
                        else:
                            cleanup_uncertain = True
            except FileNotFoundError:
                cleanup_uncertain = True
            except BaseException:
                cleanup_uncertain = True
        if directory_fd >= 0 and not close_guarded(directory_fd):
            cleanup_uncertain = True
        if workspace_binding_fd >= 0 and not close_guarded(workspace_binding_fd):
            cleanup_uncertain = True
        if not close_guarded(parent_fd):
            cleanup_uncertain = True
        if not close_guarded(source_secret_owner_fd):
            cleanup_uncertain = True
        if not close_guarded(dump_secret_owner_fd):
            cleanup_uncertain = True

    try:
        deadline_exceeded = monotonic() > deadline
    except BaseException:
        cleanup_uncertain = True
        deadline_exceeded = True
    if deadline_exceeded:
        if error_code is None:
            error_code = "OVERALL_DEADLINE_EXCEEDED"
        result_status = "FAILED"

    cleanup_verified = (not cleanup_uncertain and source_closed and workspace_absent
                        and dump_cleanup == {"containerId": dump_container_id,
                                             "containerAbsent": True,
                                             "tmpfsReleased": True}
                        and restore_cleanup == {"containerId": restore_container_id,
                                                "containerAbsent": True,
                                                "tmpfsReleased": True})
    if not cleanup_verified and error_code is None:
        error_code = "CLEANUP_UNCERTAIN"
        result_status = "FAILED"
    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "route": ROUTE,
        "planSha256": plan_sha256,
        "runNonce": checked["runNonce"],
        "status": result_status,
        "errorCode": error_code,
        "archiveBytes": archive_size,
        "archiveSha256": archive_sha,
        "equalitySha256": equality_sha,
        "cleanupStatus": "CLEANUP_VERIFIED" if cleanup_verified else "CLEANUP_UNCERTAIN",
        "cleanup": {
            "absenceScope": "REGISTERED_WORKSPACE_PATHS_AND_ID_BOUND_CONTAINERS_ONLY",
            "registeredArchivePathAbsent": workspace_absent,
            "registeredManifestPathsAbsent": workspace_absent,
            "expectedContainerIdsAbsent": (dump_cleanup["containerAbsent"]
                                           and restore_cleanup["containerAbsent"]),
            "dumpContainerAbsent": dump_cleanup["containerAbsent"],
            "restoreContainerAbsent": restore_cleanup["containerAbsent"],
            "containerTmpfsLifetimesEnded": (dump_cleanup["tmpfsReleased"]
                                             and restore_cleanup["tmpfsReleased"]),
            "dumpTmpfsReleased": dump_cleanup["tmpfsReleased"],
            "restoreTmpfsReleased": restore_cleanup["tmpfsReleased"],
            "sourceSessionClosed": source_closed,
            "credentialRevocationAttested":
                credential_revocation_attested,
            "workspaceAbsent": workspace_absent,
            "externalCopiesAbsentProven": False,
            "physicalErasureProven": False,
        },
        "adapterProductionContactDeclaration": (
            "SOURCE_AND_DUMP_TRUE_RESTORE_FALSE"
            if expected_contact == (True, True, False)
            else "ALL_DECLARED_FALSE"
        ),
        "productionContactIndependentlyObserved": None,
        "productionContactObservationScope": "NOT_OBSERVABLE_BY_HERMETIC_CORE",
        "productionAdapterEnabled": expected_contact == (True, True, False),
        "authorizationConsumed": expected_contact == (True, True, False),
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }
    _canonical(receipt)
    return receipt


def execute_hermetic(
    plan: Mapping[str, Any], workspace_parent: Path, *,
    source: SourceAdapter, dump: DumpAdapter, restore: RestoreAdapter,
    source_secret_fd: int, dump_secret_fd: int,
    absolute_deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    fault_hook: Callable[[str], None] | None = None,
    workspace_registered: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Run the complete lifecycle with production-disconnected adapters."""
    return _execute_bound(
        plan, workspace_parent, source=source, dump=dump,
        restore=restore, source_secret_fd=source_secret_fd,
        dump_secret_fd=dump_secret_fd,
        expected_contact=(False, False, False),
        absolute_deadline=absolute_deadline, monotonic=monotonic,
        fault_hook=fault_hook, workspace_registered=workspace_registered,
    )


def execute_authorized(
    plan: Mapping[str, Any], workspace_parent: Path, *,
    effective_plan: Mapping[str, Any],
    source: SourceAdapter, dump: DumpAdapter, restore: RestoreAdapter,
    source_secret_fd: int, dump_secret_fd: int,
    authorization: Any, absolute_deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    fault_hook: Callable[[str], None] | None = None,
    workspace_registered: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Run only after the signed activation boundary starts one attempt."""
    try:
        import b64_064a_activation_entrypoint as activation
        verified = activation.require_verified_execution_authorization(
            authorization, expected_environment="PRODUCTION"
        )
    except BaseException as exc:
        raise HardenedRefreshError(
            "PRODUCTION_EXECUTION_NOT_AUTHORIZED"
        ) from exc
    checked = validate_plan(plan)
    try:
        checked_effective = activation.validate_effective_execution_plan(
            effective_plan
        )
        compatibility = activation.compatibility_hardened_plan(
            checked_effective
        )
    except BaseException as exc:
        raise HardenedRefreshError(
            "PRODUCTION_EFFECTIVE_PLAN_INVALID"
        ) from exc
    if (checked["runNonce"] != verified.run_nonce
            or _canonical(checked) != _canonical(compatibility)
            or _sha_bytes(_canonical(checked_effective))
            != verified.derived_execution_plan_sha256):
        raise HardenedRefreshError("PRODUCTION_EXECUTION_NONCE_MISMATCH")
    return _execute_bound(
        checked, workspace_parent, source=source, dump=dump,
        restore=restore, source_secret_fd=source_secret_fd,
        dump_secret_fd=dump_secret_fd,
        expected_contact=(True, True, False),
        absolute_deadline=absolute_deadline, monotonic=monotonic,
        fault_hook=fault_hook, workspace_registered=workspace_registered,
    )
