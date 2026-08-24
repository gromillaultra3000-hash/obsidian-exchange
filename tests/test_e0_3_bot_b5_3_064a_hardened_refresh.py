import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import stat
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy/postgres/b64_064a_hardened_refresh.py"
SPEC = importlib.util.spec_from_file_location("b64_064a_hardened_refresh", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FROZEN_PLAN = ROOT / "docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json"
ARTIFACT_PATHS = {
    "runner": "deploy/postgres/b64_064a_hardened_refresh.py",
    "dirtyScan": "deploy/postgres/check_b64_notification_migration.py",
    "catalogFingerprintSql": "deploy/postgres/b64_catalog_security_fingerprint.sql",
    "tableFingerprintSql": "deploy/postgres/b64_table_fingerprint.sql",
    "catalogComparator": "deploy/postgres/b64_compare_catalog_fingerprints.py",
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


def _plan():
    return MODULE.build_plan(
        run_nonce="testnonce_0123456789abcdef",
        artifact_sha256={key: hashlib.sha256(key.encode()).hexdigest()
                         for key in MODULE.ARTIFACT_KEYS},
        registry_observed_at="2026-08-23T19:57:30Z",
    )


def _source_attestation():
    tables = [
        [f"table_{index:02d}", index, hashlib.sha256(
            f"table-{index}".encode()
        ).hexdigest()]
        for index in range(54)
    ]
    catalog = [
        ["b64-catalog-security-fingerprint.v2", f"section_{index:02d}",
         index, hashlib.sha256(f"catalog-{index}".encode()).hexdigest()]
        for index in range(13)
    ]
    return {
        "database": MODULE.SOURCE_DATABASE,
        "serverMajor": 17,
        "clusterSha256": hashlib.sha256(b"cluster").hexdigest(),
        "sourceContainerId": "a" * 64,
        "sourceContainerImageSha256": hashlib.sha256(b"source-image").hexdigest(),
        "transactionReadOnly": True,
        "transactionIsolation": "repeatable read",
        "snapshotReaderVerifierStatus": "match",
        "snapshotReaderProfile": MODULE.SNAPSHOT_READER_PROFILE,
        "snapshotReaderInventorySha256":
            MODULE.SNAPSHOT_READER_INVENTORY_SHA256,
        "aclVerifiedInExportingTransaction": True,
        "exclusiveDatabaseConnectivity": True,
        "hbaFirstMatchAttested": True,
        "roleCredentialAuthenticated": True,
        "credentialExpiryBound": True,
        "credentialNotAfterEpoch": int(time.time()) + 120,
        "credentialRevocationPending": True,
        "sourceTableFingerprints": tables,
        "sourceTableFingerprintSha256": hashlib.sha256(
            MODULE._canonical(tables)
        ).hexdigest(),
        "sourceCatalogFingerprints": catalog,
        "sourceCatalogFingerprintSha256": hashlib.sha256(
            MODULE._canonical(catalog)
        ).hexdigest(),
        "sourceSystemIdentifier": "1234567890123456789",
        "sessionUser": MODULE.RUNNER_ROLE,
        "currentUser": MODULE.RUNNER_ROLE,
        "roleCanLogin": True,
        "roleSuperuser": False,
        "roleCreateDb": False,
        "roleCreateRole": False,
        "roleInherit": False,
        "roleReplication": False,
        "roleBypassRls": False,
        "roleConnectionLimit": 2,
        "roleSettingsMatch": True,
        "roleMemberships": [],
        "databaseConnect": True,
        "databaseCreate": False,
        "databaseTemp": False,
        "schemaUsage": True,
        "schemaCreate": False,
        "publicTables": 54,
        "publicColumns": 423,
        "columnCatalogSha256":
            "adf9ef068c9778f3173bac3d824606ab4796b67f5647df770cbbc8be4ad53f99",
        "selectablePublicTables": 54,
        "publicSequences": 29,
        "selectablePublicSequences": 29,
        "rlsTables": 0,
        "largeObjects": 0,
        "tableWritePrivileges": 0,
        "sequenceUsageOrUpdatePrivileges": 0,
        "userFunctionExecutePrivileges": 0,
        "otherSchemaPrivileges": 0,
    }


class FakeSource:
    production_contact = False

    def __init__(self, attestation=None, secret_sentinel=b""):
        self.attestation = attestation or _source_attestation()
        self.secret_sentinel = secret_sentinel
        self.closed = False

    def open(self, _plan, secret_fd, _deadline):
        if self.secret_sentinel:
            assert os.read(secret_fd, 4096) == self.secret_sentinel
        return self.attestation, "00000003-0000001B-1"

    def close(self):
        self.closed = True
        return {
            "sourceSessionClosed": True,
            "credentialRevocationAttested": True,
            "loginState": "DISABLED",
            "credentialState": "ABSENT",
            "activeSessions": 0,
        }


class FakeDump:
    production_contact = False

    def __init__(self, *, payload=b"synthetic-archive", result=None,
                 cleanup=True, secret_sentinel=b""):
        self.payload = payload
        self.result = result
        self.cleanup_ok = cleanup
        self.secret_sentinel = secret_sentinel

    def run(self, _plan, _snapshot, source_container_id,
            credential_not_after_epoch, archive_fd, secret_fd, _deadline):
        assert source_container_id == "a" * 64
        assert 1 <= credential_not_after_epoch - int(time.time()) <= 181
        if self.secret_sentinel:
            assert os.read(secret_fd, 4096) == self.secret_sentinel
        os.write(archive_fd, self.payload)
        return self.result or {
            "clientVersion": MODULE.PG_DUMP_VERSION,
            "exitCode": 0,
            "stderrBytes": 0,
            "stderrSha256": hashlib.sha256(b"").hexdigest(),
            "warningCount": 0,
            "sourceContainerId": source_container_id,
            "containerId": "b" * 64,
        }

    def cleanup(self, expected_container_id):
        return {"containerId": expected_container_id,
                "containerAbsent": self.cleanup_ok, "tmpfsReleased": self.cleanup_ok}


class FakeRestore:
    production_contact = False

    def __init__(self, *, result=None, cleanup=True):
        self.result = result
        self.cleanup_ok = cleanup

    def verify(self, _plan, archive_fd, _workspace_fd,
               source_fingerprints, _deadline):
        os.lseek(archive_fd, 0, os.SEEK_SET)
        assert os.read(archive_fd, 4096)
        assert len(source_fingerprints["tables"]) == 54
        return self.result or {
            "tables": 54,
            "catalogSections": 13,
            "tableMatch": True,
            "catalogMatch": True,
            "restoreClusterDistinct": True,
            "sequenceRuntimeStateCompared": False,
            "restoreNoOwnerApplied": True,
            "restoreNoPrivilegesApplied": True,
            "containerId": "c" * 64,
        }

    def cleanup(self, expected_container_id):
        return {"containerId": expected_container_id,
                "containerAbsent": self.cleanup_ok, "tmpfsReleased": self.cleanup_ok}


def _parent(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir(mode=0o700, exist_ok=True)
    return parent


def _credential_fd(payload=b"synthetic-secret"):
    fd = os.memfd_create(
        "b64-core-test-secret", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    )
    os.fchmod(fd, 0o600)
    os.write(fd, payload)
    os.lseek(fd, 0, os.SEEK_SET)
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS, MODULE.REQUIRED_CREDENTIAL_SEALS)
    return fd


def _execute(tmp_path, *, plan=None, source=None, dump=None, restore=None,
             secret=b"synthetic-secret", hook=None, monotonic=None):
    source_read_fd = _credential_fd(secret)
    dump_read_fd = _credential_fd(secret)
    try:
        kwargs = {"source": source or FakeSource(), "dump": dump or FakeDump(),
                  "restore": restore or FakeRestore(),
                  "source_secret_fd": source_read_fd,
                  "dump_secret_fd": dump_read_fd,
                  "fault_hook": hook}
        if monotonic is not None:
            kwargs["monotonic"] = monotonic
        return MODULE.execute_hermetic(plan or _plan(), _parent(tmp_path), **kwargs)
    finally:
        os.close(source_read_fd)
        os.close(dump_read_fd)


def test_closed_plan_pins_fresh_registry_chain_patched_client_and_no_authority():
    plan = _plan()
    assert plan["registryObservation"] == {
        "observedAt": "2026-08-23T19:57:30Z",
        "tag": "docker.io/library/postgres:17.11-alpine3.24",
        "indexDigest": MODULE.IMAGE_INDEX,
        "linuxAmd64ChildDigest": MODULE.IMAGE_CHILD,
        "configDigest": MODULE.IMAGE_CONFIG,
        "sourceRevision": MODULE.IMAGE_SOURCE_REVISION,
        "versionAnnotation": "17.11-alpine3.24",
        "freshRevalidationRequiredAtAuthorization": True,
        "digestPinDoesNotProveFutureSecurity": True,
    }
    assert plan["client"]["expectedPgDumpVersion"] == "pg_dump (PostgreSQL) 17.11"
    assert plan["client"]["minimumVersionNum"] == 170011
    assert plan["source"]["dormantPrincipalProvisioningImplemented"] is True
    assert plan["source"]["activePrincipalProvisioningImplemented"] is True
    assert plan["source"]["sequencePrivilegeProfile"] == \
        "SELECT_ONLY_FOR_PG_DUMP_STATE"
    assert plan["authentication"]["implementedByThisModule"] is False
    assert all(value is False for value in plan["authority"].values())


def test_derived_plan_validates_and_binds_every_executable_input_byte_exact():
    historical = json.loads(FROZEN_PLAN.read_text(encoding="utf-8"))
    plan = MODULE.build_plan(
        run_nonce="derived_plan_0123456789abcdef",
        artifact_sha256={
            key: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            for key, relative in ARTIFACT_PATHS.items()
        },
        registry_observed_at=historical["registryObservation"]["observedAt"],
    )
    MODULE.validate_plan(plan)
    assert set(plan["artifactsSha256"]) == set(ARTIFACT_PATHS)
    for key, relative in ARTIFACT_PATHS.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == \
            plan["artifactsSha256"][key]


@pytest.mark.parametrize("path,value", [
    (("client", "imageRef"), "postgres:17.11"),
    (("client", "minimumVersionNum"), 170010),
    (("client", "platform"), "linux/arm64"),
    (("command", "noPasswordPrompt"), False),
    (("command", "noSyncForbidden"), False),
    (("credentials", "secretInEnvironment"), True),
    (("authentication", "implementedByThisModule"), True),
    (("authority", "actionAllowed"), True),
    (("authentication", "implementedByThisModule"), 0),
    (("authority", "actionAllowed"), 0),
    (("client", "capDropAll"), 1),
])
def test_plan_drift_fails_closed(path, value):
    plan = copy.deepcopy(_plan())
    plan[path[0]][path[1]] = value
    with pytest.raises(MODULE.HardenedRefreshError):
        MODULE.validate_plan(plan)


def test_compiled_commands_are_digest_pinned_sandboxed_bounded_and_secret_free():
    plan = _plan()
    version = MODULE.compile_client_preflight(plan)
    source_id = "a" * 64
    dump = MODULE.compile_dump_command(
        plan, "00000003-0000001B-1", source_id,
        transaction_timeout_ms=90_000,
        lease_not_after_epoch=int(time.time()) + 120,
    )
    assert MODULE.IMAGE_REF in version and "--network=none" in version
    assert MODULE.IMAGE_REF in dump and "--pull=never" in dump
    assert "--platform=linux/amd64" in dump
    assert "--read-only" in dump and "--cap-drop=ALL" in dump
    assert "--security-opt=no-new-privileges=true" in dump
    assert f"--network=container:{source_id}" in dump
    assert "--no-password" in dump and "--lock-wait-timeout=5000" in dump
    assert "--schema=public" in dump and "--no-large-objects" in dump
    assert "--strict-names" in dump
    assert "--env=PGOPTIONS=-c transaction_timeout=90000ms" in dump
    assert any(item.startswith("--env=B64_LEASE_NOT_AFTER_EPOCH=")
               for item in dump)
    dbname = next(item for item in dump if item.startswith("--dbname="))
    assert "require_auth=scram-sha256" not in dbname
    assert "require_auth=scram-sha-256" in dbname
    assert "connect_timeout=5" in dbname
    assert "timeout -s KILL" in " ".join(dump)
    assert "-i" in dump and "-i" not in version
    assert not any("--no-sync" == item for item in dump)
    assert "postgres" not in [item.removeprefix("--username=") for item in dump]
    assert not any("password=" in item.lower() for item in dump)
    assert "PGPASSWORD" not in " ".join(dump)


@pytest.mark.parametrize("snapshot", ["", "abc;id", "$(id)", "a" * 129, None])
def test_snapshot_is_never_interpolated_without_closed_validation(snapshot):
    with pytest.raises(MODULE.HardenedRefreshError):
        MODULE.compile_dump_command(
            _plan(), snapshot, "a" * 64, transaction_timeout_ms=90_000,
            lease_not_after_epoch=int(time.time()) + 120,
        )


@pytest.mark.parametrize("timeout_ms", [0, 180_001, True, 90_000.0])
def test_dump_transaction_timeout_is_closed_and_lease_bounded(timeout_ms):
    with pytest.raises(
        MODULE.HardenedRefreshError,
        match="INVALID_DUMP_TRANSACTION_TIMEOUT",
    ):
        MODULE.compile_dump_command(
            _plan(), "00000003-0000001B-1", "a" * 64,
            transaction_timeout_ms=timeout_ms,
            lease_not_after_epoch=int(time.time()) + 120,
        )


@pytest.mark.parametrize("offset", [0, 182, -1])
def test_dump_absolute_lease_deadline_is_closed(offset):
    with pytest.raises(
        MODULE.HardenedRefreshError,
        match="INVALID_DUMP_LEASE_DEADLINE",
    ):
        MODULE.compile_dump_command(
            _plan(), "00000003-0000001B-1", "a" * 64,
            transaction_timeout_ms=1,
            lease_not_after_epoch=int(time.time()) + offset,
        )


def test_dump_transaction_timeout_cannot_exceed_absolute_lease_residual():
    with pytest.raises(
        MODULE.HardenedRefreshError,
        match="INVALID_DUMP_LEASE_DEADLINE",
    ):
        MODULE.compile_dump_command(
            _plan(), "00000003-0000001B-1", "a" * 64,
            transaction_timeout_ms=90_000,
            lease_not_after_epoch=int(time.time()) + 30,
        )


def test_core_rejects_invalid_snapshot_before_dump_adapter(tmp_path):
    class InvalidSnapshotSource(FakeSource):
        def open(self, plan, secret_fd, deadline):
            attestation, _snapshot = super().open(plan, secret_fd, deadline)
            return attestation, "abc;id"

    class RecordingDump(FakeDump):
        invoked = False

        def run(self, *args):
            self.invoked = True
            return super().run(*args)

    dump = RecordingDump()
    receipt = _execute(tmp_path, source=InvalidSnapshotSource(), dump=dump)
    assert receipt["errorCode"] == "INVALID_EXPORTED_SNAPSHOT"
    assert dump.invoked is False
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"


@pytest.mark.parametrize("source_id", ["", "a" * 63, "a" * 65, "g" * 64, None])
def test_source_container_id_is_exact_before_namespace_join(source_id):
    with pytest.raises(MODULE.HardenedRefreshError, match="INVALID_SOURCE_CONTAINER_ID"):
        MODULE.compile_dump_command(
            _plan(), "00000003-0000001B-1", source_id,
            transaction_timeout_ms=90_000,
            lease_not_after_epoch=int(time.time()) + 120,
        )


@pytest.mark.parametrize("field,value", [
    ("sessionUser", "postgres"),
    ("currentUser", "postgres"),
    ("roleSuperuser", True),
    ("roleBypassRls", True),
    ("roleInherit", True),
    ("roleConnectionLimit", 3),
    ("roleSettingsMatch", False),
    ("roleMemberships", ["pg_read_all_data"]),
    ("databaseTemp", True),
    ("schemaCreate", True),
    ("selectablePublicTables", 53),
    ("publicColumns", 422),
    ("columnCatalogSha256", "0" * 64),
    ("selectablePublicSequences", 28),
    ("rlsTables", 1),
    ("largeObjects", 1),
    ("tableWritePrivileges", 1),
    ("sequenceUsageOrUpdatePrivileges", 1),
    ("userFunctionExecutePrivileges", 1),
    ("otherSchemaPrivileges", 1),
    ("publicTables", 54.0),
    ("rlsTables", False),
])
def test_least_privilege_attestation_rejects_each_privilege_gap(field, value):
    attestation = _source_attestation()
    attestation[field] = value
    with pytest.raises(MODULE.HardenedRefreshError):
        MODULE.validate_source_attestation(attestation)


def test_success_is_full_lifecycle_with_verified_absence_and_no_authority(tmp_path):
    source = FakeSource()
    receipt = _execute(tmp_path, source=source)
    assert receipt["status"] == "COMPLETED"
    assert receipt["errorCode"] is None
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
    assert receipt["cleanup"] == {
        "absenceScope": "REGISTERED_WORKSPACE_PATHS_AND_ID_BOUND_CONTAINERS_ONLY",
        "registeredArchivePathAbsent": True,
        "registeredManifestPathsAbsent": True,
            "expectedContainerIdsAbsent": True,
            "dumpContainerAbsent": True,
            "restoreContainerAbsent": True,
            "containerTmpfsLifetimesEnded": True,
            "dumpTmpfsReleased": True,
            "restoreTmpfsReleased": True,
        "sourceSessionClosed": True,
        "credentialRevocationAttested": True,
        "workspaceAbsent": True,
        "externalCopiesAbsentProven": False,
        "physicalErasureProven": False,
    }
    assert source.closed is True
    assert receipt["adapterProductionContactDeclaration"] == "ALL_DECLARED_FALSE"
    assert receipt["productionContactIndependentlyObserved"] is None
    assert receipt["productionContactObservationScope"] == \
        "NOT_OBSERVABLE_BY_HERMETIC_CORE"
    assert receipt["productionAdapterEnabled"] is False
    assert receipt["authorizationConsumed"] is False
    assert receipt["automaticRetryAllowed"] is False
    assert receipt["actionAllowed"] is False
    assert list((_parent_path := tmp_path / "parent").iterdir()) == []
    assert stat.S_IMODE(_parent_path.stat().st_mode) == 0o700


@pytest.mark.parametrize("stage", [
    "WORKSPACE_CREATED", "TRANSIENTS_REGISTERED", "SOURCE_ATTESTED",
    "DUMP_VERIFIED", "RESTORE_EQUALITY_VERIFIED",
])
def test_cancellation_after_every_stage_still_cleans_and_forbids_retry(tmp_path, stage):
    def cancel(observed):
        if observed == stage:
            raise KeyboardInterrupt()

    receipt = _execute(tmp_path, hook=cancel)
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "CANCELLED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
    assert receipt["automaticRetryAllowed"] is False
    assert list((tmp_path / "parent").iterdir()) == []


def test_nonzero_or_warning_dump_fails_closed_and_removes_partial_archive(tmp_path):
    result = {
        "clientVersion": MODULE.PG_DUMP_VERSION,
        "exitCode": 1,
        "stderrBytes": 12,
        "stderrSha256": hashlib.sha256(b"safe warning").hexdigest(),
        "warningCount": 1,
        "sourceContainerId": "a" * 64,
        "containerId": "b" * 64,
    }
    receipt = _execute(tmp_path, dump=FakeDump(payload=b"partial", result=result))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "DUMP_ATTESTATION_FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
    assert list((tmp_path / "parent").iterdir()) == []


def test_oversized_archive_fails_closed(tmp_path):
    plan = _plan()
    plan["command"]["maximumArchiveBytes"] = 16 * 1024 * 1024
    receipt = _execute(tmp_path, plan=plan,
                       dump=FakeDump(payload=b"x" * (16 * 1024 * 1024 + 1)))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "ARCHIVE_SIZE_INVALID"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"


def test_deadline_overrun_after_adapter_returns_is_terminal_and_cleaned(tmp_path):
    values = iter((0.0, 1.0, 2.0, 3.0, 181.0, 182.0))
    receipt = _execute(tmp_path, monotonic=lambda: next(values))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "OVERALL_DEADLINE_EXCEEDED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
    assert receipt["automaticRetryAllowed"] is False


def test_cleanup_absence_failure_is_terminal_and_never_retried(tmp_path):
    receipt = _execute(tmp_path, dump=FakeDump(cleanup=False))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "CLEANUP_UNCERTAIN"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert receipt["automaticRetryAllowed"] is False


def test_never_invoked_stages_do_not_receive_unbound_cleanup_callbacks(tmp_path):
    calls = []

    class RecordingDump(FakeDump):
        def cleanup(self, expected_container_id):
            calls.append(("dump", expected_container_id))
            return super().cleanup(expected_container_id)

    class RecordingRestore(FakeRestore):
        def cleanup(self, expected_container_id):
            calls.append(("restore", expected_container_id))
            return super().cleanup(expected_container_id)

    attestation = _source_attestation()
    attestation["roleSuperuser"] = True
    receipt = _execute(
        tmp_path, source=FakeSource(attestation=attestation),
        dump=RecordingDump(), restore=RecordingRestore())
    assert receipt["errorCode"] == "LEAST_PRIVILEGE_ATTESTATION_FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
    assert calls == []


def test_source_close_is_not_called_when_source_open_was_never_invoked(tmp_path):
    class RecordingSource(FakeSource):
        close_called = False

        def close(self):
            self.close_called = True
            return super().close()

    parent = _parent(tmp_path)
    parent.chmod(0o755)
    source = RecordingSource()
    source_read_fd = _credential_fd()
    dump_read_fd = _credential_fd()
    try:
        receipt = MODULE.execute_hermetic(
            _plan(), parent, source=source, dump=FakeDump(),
            restore=FakeRestore(), source_secret_fd=source_read_fd,
            dump_secret_fd=dump_read_fd)
    finally:
        os.close(source_read_fd)
        os.close(dump_read_fd)
    assert receipt["errorCode"] == "UNSAFE_WORKSPACE_PARENT"
    assert source.close_called is False


def test_adapter_plan_mutation_is_detected_and_original_plan_digest_stays_bound(tmp_path):
    class MutatingSource(FakeSource):
        def open(self, plan, secret_fd, deadline):
            plan["authority"]["actionAllowed"] = True
            return super().open(plan, secret_fd, deadline)

    plan = _plan()
    expected = hashlib.sha256(MODULE._canonical(plan)).hexdigest()
    receipt = _execute(tmp_path, plan=plan, source=MutatingSource())
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "ADAPTER_MUTATED_PLAN"
    assert receipt["planSha256"] == expected
    assert plan["authority"]["actionAllowed"] is False


def test_adapter_closing_its_duplicate_archive_fd_cannot_abort_cleanup(tmp_path):
    class ClosingDump(FakeDump):
        def run(self, *args):
            result = super().run(*args)
            os.close(args[4])
            return result

    receipt = _execute(tmp_path, dump=ClosingDump())
    assert receipt["status"] == "COMPLETED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
    assert list((tmp_path / "parent").iterdir()) == []


def test_adapter_closing_duplicate_secret_fd_does_not_close_owner_fd(tmp_path):
    class ClosingSecretDump(FakeDump):
        def run(self, *args):
            result = super().run(*args)
            os.close(args[5])
            return result

    source_read_fd = _credential_fd()
    dump_read_fd = _credential_fd()
    try:
        receipt = MODULE.execute_hermetic(
            _plan(), _parent(tmp_path), source=FakeSource(),
            dump=ClosingSecretDump(), restore=FakeRestore(),
            source_secret_fd=source_read_fd, dump_secret_fd=dump_read_fd)
        os.fstat(source_read_fd)
        os.fstat(dump_read_fd)
    finally:
        os.close(source_read_fd)
        os.close(dump_read_fd)
    assert receipt["status"] == "COMPLETED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"


def test_second_restore_dup_failure_closes_first_and_skips_restore_cleanup(
        tmp_path, monkeypatch):
    real_dup = MODULE.os.dup
    directory_dups = 0
    leaked_candidate = None

    class RecordingRestore(FakeRestore):
        cleanup_called = False

        def cleanup(self, expected_container_id):
            self.cleanup_called = True
            return super().cleanup(expected_container_id)

    def fail_second_directory_dup(fd):
        nonlocal directory_dups, leaked_candidate
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            directory_dups += 1
            if directory_dups == 2:
                raise OSError("synthetic dup failure")
        duplicated = real_dup(fd)
        if directory_dups == 1 and not stat.S_ISDIR(os.fstat(fd).st_mode):
            leaked_candidate = duplicated
        return duplicated

    restore = RecordingRestore()
    monkeypatch.setattr(MODULE.os, "dup", fail_second_directory_dup)
    receipt = _execute(tmp_path, restore=restore)
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "UNEXPECTED_FAILURE"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
    assert restore.cleanup_called is False
    assert leaked_candidate is not None
    with pytest.raises(OSError):
        os.fstat(leaked_candidate)


def test_archive_binding_dup_failure_closes_unregistered_transient_fd(
        tmp_path, monkeypatch):
    real_dup = MODULE.os.dup
    regular_dup_source = None

    def fail_first_regular_dup(fd):
        nonlocal regular_dup_source
        metadata = os.fstat(fd)
        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
            regular_dup_source = fd
            raise OSError("synthetic archive binding dup failure")
        return real_dup(fd)

    monkeypatch.setattr(MODULE.os, "dup", fail_first_regular_dup)
    receipt = _execute(tmp_path)
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "UNEXPECTED_FAILURE"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert regular_dup_source is not None
    with pytest.raises(OSError):
        os.fstat(regular_dup_source)


def test_workspace_rename_and_same_name_replacement_cannot_yield_cleanup_verified(tmp_path):
    parent = _parent(tmp_path)
    workspace = parent / f"b64-064a-{_plan()['runNonce']}"
    moved = parent / "moved-original"

    def swap(stage):
        if stage == "TRANSIENTS_REGISTERED":
            workspace.rename(moved)
            workspace.mkdir(mode=0o700)

    receipt = _execute(tmp_path, hook=swap)
    assert receipt["status"] == "FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert moved.is_dir() and workspace.is_dir()


def test_external_hardlink_prevents_absence_claim(tmp_path):
    parent = _parent(tmp_path)
    workspace = parent / f"b64-064a-{_plan()['runNonce']}"
    external = parent / "external-archive-link"

    def link(stage):
        if stage == "DUMP_VERIFIED":
            os.link(workspace / "snapshot.dump", external)

    receipt = _execute(tmp_path, hook=link)
    assert receipt["status"] == "FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert receipt["cleanup"]["registeredArchivePathAbsent"] is False
    assert external.read_bytes() == b"synthetic-archive"


def test_integer_cleanup_pseudo_booleans_are_rejected(tmp_path):
    class IntegerCleanupDump(FakeDump):
        def cleanup(self, expected_container_id):
            return {"containerId": expected_container_id,
                    "containerAbsent": 1, "tmpfsReleased": 1}

    receipt = _execute(tmp_path, dump=IntegerCleanupDump())
    assert receipt["status"] == "FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"


def test_cleanup_container_id_requires_literal_exact_64hex(tmp_path):
    class EqualAnything:
        def __eq__(self, _other):
            return True

    class MalformedCleanupDump(FakeDump):
        def cleanup(self, _expected_container_id):
            return {"containerId": EqualAnything(), "containerAbsent": True,
                    "tmpfsReleased": True}

    receipt = _execute(tmp_path, dump=MalformedCleanupDump())
    assert receipt["status"] == "FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"


@pytest.mark.parametrize("collision", ["dump-source", "restore-source", "restore-dump"])
def test_container_ids_are_pairwise_distinct_and_unsafe_cleanup_is_skipped(
        tmp_path, collision):
    class RecordingDump(FakeDump):
        cleanup_called = False

        def cleanup(self, expected_container_id):
            self.cleanup_called = True
            return super().cleanup(expected_container_id)

    class RecordingRestore(FakeRestore):
        cleanup_called = False

        def cleanup(self, expected_container_id):
            self.cleanup_called = True
            return super().cleanup(expected_container_id)

    dump_id = "a" * 64 if collision == "dump-source" else "b" * 64
    restore_id = ("a" * 64 if collision == "restore-source" else
                  "b" * 64 if collision == "restore-dump" else "c" * 64)
    dump = RecordingDump(result={
        "clientVersion": MODULE.PG_DUMP_VERSION, "exitCode": 0,
        "stderrBytes": 0, "stderrSha256": hashlib.sha256(b"").hexdigest(),
        "warningCount": 0, "sourceContainerId": "a" * 64,
        "containerId": dump_id,
    })
    restore = RecordingRestore(result={
        "tables": 54, "catalogSections": 13, "tableMatch": True,
        "catalogMatch": True, "restoreClusterDistinct": True,
        "sequenceRuntimeStateCompared": False, "restoreNoOwnerApplied": True,
        "restoreNoPrivilegesApplied": True, "containerId": restore_id,
    })
    receipt = _execute(tmp_path, dump=dump, restore=restore)
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "CONTAINER_ID_COLLISION"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    if collision == "dump-source":
        assert dump.cleanup_called is False
    elif collision == "restore-source":
        assert dump.cleanup_called is True
        assert restore.cleanup_called is False
    else:
        assert dump.cleanup_called is False
        assert restore.cleanup_called is False


def test_stat_unlink_swap_cannot_hide_escaped_bound_inode(tmp_path, monkeypatch):
    parent = _parent(tmp_path)
    workspace = parent / f"b64-064a-{_plan()['runNonce']}"
    escaped = parent / "escaped-original-archive"
    real_unlink = MODULE.os.unlink
    attacked = False

    def swap_then_unlink(path, *args, **kwargs):
        nonlocal attacked
        if path == "snapshot.dump" and not attacked:
            attacked = True
            (workspace / "snapshot.dump").rename(escaped)
            (workspace / "snapshot.dump").write_bytes(b"replacement")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(MODULE.os, "unlink", swap_then_unlink)
    receipt = _execute(tmp_path)
    assert receipt["status"] == "FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert escaped.read_bytes() == b"synthetic-archive"
    assert receipt["cleanup"]["externalCopiesAbsentProven"] is False


def test_stat_rmdir_swap_cannot_claim_bound_workspace_absent(tmp_path, monkeypatch):
    parent = _parent(tmp_path)
    workspace = parent / f"b64-064a-{_plan()['runNonce']}"
    escaped = parent / "escaped-original-workspace"
    real_rmdir = MODULE.os.rmdir
    attacked = False

    def swap_then_rmdir(path, *args, **kwargs):
        nonlocal attacked
        if path == workspace.name and not attacked:
            attacked = True
            workspace.rename(escaped)
            workspace.mkdir(mode=0o700)
        return real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(MODULE.os, "rmdir", swap_then_rmdir)
    receipt = _execute(tmp_path)
    assert receipt["status"] == "FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert receipt["cleanup"]["workspaceAbsent"] is False
    assert escaped.is_dir()


def test_parent_fsync_failure_cannot_claim_workspace_cleanup(tmp_path, monkeypatch):
    plan = _plan()
    source_fd = _credential_fd()
    dump_fd = _credential_fd()
    parent = _parent(tmp_path)
    real_rmdir = MODULE.os.rmdir
    real_fsync = MODULE.os.fsync
    removed = False

    def observed_rmdir(path, *args, **kwargs):
        nonlocal removed
        result = real_rmdir(path, *args, **kwargs)
        if path == f"b64-064a-{plan['runNonce']}":
            removed = True
        return result

    def fail_parent_fsync(fd):
        if removed:
            raise OSError("synthetic parent fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(MODULE.os, "rmdir", observed_rmdir)
    monkeypatch.setattr(MODULE.os, "fsync", fail_parent_fsync)
    try:
        receipt = MODULE.execute_hermetic(
            plan, parent, source=FakeSource(), dump=FakeDump(),
            restore=FakeRestore(), source_secret_fd=source_fd,
            dump_secret_fd=dump_fd,
        )
    finally:
        os.close(source_fd)
        os.close(dump_fd)
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert receipt["cleanup"]["workspaceAbsent"] is False


def test_cleanup_overrun_is_detected_by_final_deadline_check(tmp_path):
    class Clock:
        value = 0.0

        def __call__(self):
            current = self.value
            self.value += 1.0
            return current

    clock = Clock()

    class LateCleanupDump(FakeDump):
        def cleanup(self, expected_container_id):
            clock.value = 999.0
            return super().cleanup(expected_container_id)

    receipt = _execute(tmp_path, dump=LateCleanupDump(), monotonic=clock)
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "OVERALL_DEADLINE_EXCEEDED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"


def test_restore_must_attest_no_owner_and_no_privileges_at_restore_time(tmp_path):
    bad = {
        "tables": 54, "catalogSections": 13, "tableMatch": True,
        "catalogMatch": True, "restoreClusterDistinct": True,
        "sequenceRuntimeStateCompared": False, "restoreNoOwnerApplied": False,
        "restoreNoPrivilegesApplied": True,
        "containerId": "c" * 64,
    }
    receipt = _execute(tmp_path, restore=FakeRestore(result=bad))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "RESTORE_EQUALITY_FAILED"
    assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"


def test_restore_boolean_pseudo_values_fail_closed(tmp_path):
    bad = {
        "tables": 54, "catalogSections": 13, "tableMatch": 1,
        "catalogMatch": 1, "restoreClusterDistinct": 1,
        "sequenceRuntimeStateCompared": 0, "restoreNoOwnerApplied": 1,
        "restoreNoPrivilegesApplied": 1, "containerId": "c" * 64,
    }
    receipt = _execute(tmp_path, restore=FakeRestore(result=bad))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "RESTORE_EQUALITY_FAILED"


def test_dump_attestation_must_echo_exact_attested_source_container_id(tmp_path):
    bad = {
        "clientVersion": MODULE.PG_DUMP_VERSION, "exitCode": 0,
        "stderrBytes": 0, "stderrSha256": hashlib.sha256(b"").hexdigest(),
        "warningCount": 0, "sourceContainerId": "d" * 64,
        "containerId": "b" * 64,
    }
    receipt = _execute(tmp_path, dump=FakeDump(result=bad))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == "DUMP_ATTESTATION_FAILED"


@pytest.mark.parametrize("stage", ["dump", "restore"])
def test_container_id_str_subclasses_fail_closed_at_adapter_ingress(tmp_path, stage):
    class HostileId(str):
        def __eq__(self, other):
            return str(other) == str(self)

        __hash__ = str.__hash__

    dump_result = {
        "clientVersion": MODULE.PG_DUMP_VERSION, "exitCode": 0,
        "stderrBytes": 0, "stderrSha256": hashlib.sha256(b"").hexdigest(),
        "warningCount": 0, "sourceContainerId": "a" * 64,
        "containerId": HostileId("a" * 64) if stage == "dump" else "b" * 64,
    }
    restore_result = {
        "tables": 54, "catalogSections": 13, "tableMatch": True,
        "catalogMatch": True, "restoreClusterDistinct": True,
        "sequenceRuntimeStateCompared": False, "restoreNoOwnerApplied": True,
        "restoreNoPrivilegesApplied": True,
        "containerId": HostileId("b" * 64) if stage == "restore" else "c" * 64,
    }
    receipt = _execute(
        tmp_path, dump=FakeDump(result=dump_result),
        restore=FakeRestore(result=restore_result))
    assert receipt["status"] == "FAILED"
    assert receipt["errorCode"] == (
        "INVALID_CONTAINER_ID" if stage == "dump"
        else "INVALID_RESTORE_CONTAINER_ID")
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"


def test_secret_fd_value_never_appears_in_plan_commands_or_receipt(tmp_path):
    sentinel = b"SYNTHETIC-SECRET-DO-NOT-LEAK"
    dump = FakeDump(secret_sentinel=sentinel)
    source = FakeSource(secret_sentinel=sentinel)
    receipt = _execute(tmp_path, source=source, dump=dump, secret=sentinel)
    material = json.dumps(_plan()) + json.dumps(receipt) + " ".join(
        MODULE.compile_dump_command(
            _plan(), "00000003-0000001B-1", "a" * 64,
            transaction_timeout_ms=90_000,
            lease_not_after_epoch=int(time.time()) + 120,
        ))
    assert sentinel.decode() not in material


def test_production_capable_adapter_is_rejected_before_workspace_or_secret_read(tmp_path):
    class ProductionSource(FakeSource):
        production_contact = True

    parent = _parent(tmp_path)
    source_read_fd, source_write_fd = os.pipe()
    dump_read_fd, dump_write_fd = os.pipe()
    os.write(source_write_fd, b"unread-secret")
    os.write(dump_write_fd, b"unread-secret")
    os.close(source_write_fd)
    os.close(dump_write_fd)
    try:
        with pytest.raises(MODULE.HardenedRefreshError,
                           match="ADAPTER_CONTACT_PROFILE_MISMATCH"):
            MODULE.execute_hermetic(_plan(), parent, source=ProductionSource(),
                                    dump=FakeDump(), restore=FakeRestore(),
                                    source_secret_fd=source_read_fd,
                                    dump_secret_fd=dump_read_fd)
        assert os.read(source_read_fd, 4096) == b"unread-secret"
        assert os.read(dump_read_fd, 4096) == b"unread-secret"
    finally:
        os.close(source_read_fd)
        os.close(dump_read_fd)
    assert list(parent.iterdir()) == []


def test_core_rejects_pipe_credentials_before_adapter_contact(tmp_path):
    source_read_fd, source_write_fd = os.pipe()
    dump_fd = _credential_fd()
    os.write(source_write_fd, b"not-an-anonymous-sealed-memfd")
    os.close(source_write_fd)
    try:
        with pytest.raises(
            MODULE.HardenedRefreshError, match="INVALID_CREDENTIAL_FD"
        ):
            MODULE.execute_hermetic(
                _plan(), _parent(tmp_path), source=FakeSource(),
                dump=FakeDump(), restore=FakeRestore(),
                source_secret_fd=source_read_fd, dump_secret_fd=dump_fd,
            )
    finally:
        os.close(source_read_fd)
        os.close(dump_fd)


def test_core_rejects_same_memfd_for_both_credential_consumers(tmp_path):
    shared_fd = _credential_fd()
    try:
        with pytest.raises(
            MODULE.HardenedRefreshError,
            match="CREDENTIAL_FDS_NOT_INDEPENDENT",
        ):
            MODULE.execute_hermetic(
                _plan(), _parent(tmp_path), source=FakeSource(),
                dump=FakeDump(), restore=FakeRestore(),
                source_secret_fd=shared_fd, dump_secret_fd=shared_fd,
            )
    finally:
        os.close(shared_fd)


def test_unsafe_parent_and_existing_workspace_are_not_deleted(tmp_path):
    parent = _parent(tmp_path)
    parent.chmod(0o755)
    marker = parent / f"b64-064a-{_plan()['runNonce']}"
    marker.mkdir()
    receipt = None
    source_read_fd = _credential_fd()
    dump_read_fd = _credential_fd()
    try:
        receipt = MODULE.execute_hermetic(_plan(), parent, source=FakeSource(),
                                          dump=FakeDump(), restore=FakeRestore(),
                                          source_secret_fd=source_read_fd,
                                          dump_secret_fd=dump_read_fd)
    finally:
        os.close(source_read_fd)
        os.close(dump_read_fd)
    assert receipt["errorCode"] == "UNSAFE_WORKSPACE_PARENT"
    assert receipt["cleanupStatus"] == "CLEANUP_UNCERTAIN"
    assert marker.is_dir()


def test_extra_or_missing_attestation_field_blocks_before_dump(tmp_path):
    for mutate in (
        lambda value: value.update({"extra": False}),
        lambda value: value.pop("roleSuperuser"),
    ):
        attestation = _source_attestation()
        mutate(attestation)
        receipt = _execute(tmp_path, source=FakeSource(attestation=attestation))
        assert receipt["status"] == "FAILED"
        assert receipt["errorCode"] == "INVALID_SOURCE_ATTESTATION_SHAPE"
        assert receipt["cleanupStatus"] == "CLEANUP_VERIFIED"
