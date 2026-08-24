import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy/postgres/deploy_b64_snapshot_reader_hba.py"
MANIFEST_PATH = ROOT / "deploy/postgres/b64_snapshot_reader_hba.v1.json"
sys.path.insert(0, str(ROOT / "deploy/postgres"))
SPEC = importlib.util.spec_from_file_location(
    "deploy_b64_snapshot_reader_hba", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_hba_container_inspection_never_materializes_environment(monkeypatch):
    observed = {}

    def run(command, **_kwargs):
        observed["command"] = command
        return subprocess.CompletedProcess(command, 0, json.dumps({
            "Id": "a" * 64, "Mounts": [],
        }), "")

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    assert MODULE._docker_inspect("obsidian-postgres") == {
        "Id": "a" * 64, "Mounts": [],
    }
    assert observed["command"][:2] == ["/usr/bin/docker", "inspect"]
    assert observed["command"][2].startswith("--format=")
    assert "Config.Env" not in observed["command"][2]


def test_manifest_and_managed_bytes_are_exactly_bound():
    manifest = json.loads(MANIFEST_PATH.read_text("utf-8"))
    assert manifest["schemaVersion"] == \
        "obsidian-b64-snapshot-reader-hba.v1"
    assert hashlib.sha256(MODULE.MANAGED_BLOCK).hexdigest() == \
        manifest["managedBlockSha256"]
    assert manifest["expectedOriginalSha256"] == \
        "45b68cd420caab6d19725857c309871880a66a4c195bcd7e1604e7c334b6be82"
    assert manifest["expectedDeployedSha256"] == \
        "08b049674e7593bc87c8e78744ba6b65b557750807c17e860920931aa1b3d3b6"
    MODULE._load_manifest()


def test_managed_prefix_is_first_match_complete_and_role_scoped():
    lines = MODULE.MANAGED_BLOCK.decode("ascii").splitlines()
    rules = [line.split() for line in lines if line and not line.startswith("#")]
    assert rules == [
        ["local", "all", MODULE.ROLE, "reject"],
        ["local", "replication", MODULE.ROLE, "reject"],
        ["host", "obsidian_exchange", MODULE.ROLE, "127.0.0.1/32",
         "scram-sha-256"],
        ["host", "replication", MODULE.ROLE, "0.0.0.0/0", "reject"],
        ["host", "replication", MODULE.ROLE, "::/0", "reject"],
        ["host", "all", MODULE.ROLE, "0.0.0.0/0", "reject"],
        ["host", "all", MODULE.ROLE, "::/0", "reject"],
    ]


def _pgdata(tmp_path: Path, content: bytes = b"base\n"):
    target = tmp_path / MODULE.HBA_NAME
    target.write_bytes(content)
    target.chmod(0o600)
    directory_fd = MODULE._open_pgdata(tmp_path)
    metadata = os.stat(target)
    return target, directory_fd, metadata


def test_rename_exchange_installs_exact_candidate(monkeypatch, tmp_path):
    target, directory_fd, metadata = _pgdata(tmp_path)
    monkeypatch.setattr(MODULE, "_validate_hba_metadata", lambda _value: None)
    try:
        MODULE._exchange_target(
            directory_fd, b"candidate\n", metadata,
            hashlib.sha256(b"base\n").hexdigest(),
        )
        assert target.read_bytes() == b"candidate\n"
        assert list(tmp_path.glob(".obsidian-b64-hba-stage-*")) == []
    finally:
        os.close(directory_fd)


def test_concurrent_edit_is_preserved_and_never_overwritten(
        monkeypatch, tmp_path):
    target, directory_fd, metadata = _pgdata(tmp_path)
    monkeypatch.setattr(MODULE, "_validate_hba_metadata", lambda _value: None)
    real_exchange = MODULE._rename_exchange

    calls = 0

    def drift_then_exchange(fd, first, second):
        nonlocal calls
        calls += 1
        if calls == 1:
            target.write_bytes(b"foreign\n")
        return real_exchange(fd, first, second)

    monkeypatch.setattr(MODULE, "_rename_exchange", drift_then_exchange)
    try:
        with pytest.raises(MODULE.HbaDeploymentError,
                           match="CONCURRENT_HBA_EDIT_PRESERVED"):
            MODULE._exchange_target(
                directory_fd, b"candidate\n", metadata,
                hashlib.sha256(b"base\n").hexdigest(),
            )
        assert target.read_bytes() == b"foreign\n"
        assert list(tmp_path.glob(".obsidian-b64-hba-stage-*")) == []
    finally:
        os.close(directory_fd)


def test_reverse_exchange_failure_retains_foreign_displaced_bytes(
        monkeypatch, tmp_path):
    target, directory_fd, metadata = _pgdata(tmp_path)
    monkeypatch.setattr(MODULE, "_validate_hba_metadata", lambda _value: None)
    real_exchange = MODULE._rename_exchange
    calls = 0

    def fail_reverse(fd, first, second):
        nonlocal calls
        calls += 1
        if calls == 1:
            target.write_bytes(b"foreign\n")
            return real_exchange(fd, first, second)
        raise MODULE.HbaDeploymentError("INJECTED_REVERSE_FAILURE")

    monkeypatch.setattr(MODULE, "_rename_exchange", fail_reverse)
    try:
        with pytest.raises(
            MODULE.HbaDeploymentError,
            match="CONCURRENT_HBA_EDIT_REVERSE_FAILED",
        ):
            MODULE._exchange_target(
                directory_fd, b"candidate\n", metadata,
                hashlib.sha256(b"base\n").hexdigest(),
            )
        assert target.read_bytes() == b"candidate\n"
        stages = list(tmp_path.glob(".obsidian-b64-hba-stage-*"))
        assert len(stages) == 1
        assert stages[0].read_bytes() == b"foreign\n"
    finally:
        os.close(directory_fd)


def test_post_exchange_fsync_failure_retains_displaced_bytes(
        monkeypatch, tmp_path):
    target, directory_fd, metadata = _pgdata(tmp_path)
    monkeypatch.setattr(MODULE, "_validate_hba_metadata", lambda _value: None)
    real_exchange = MODULE._rename_exchange

    def drift_then_exchange(fd, first, second):
        target.write_bytes(b"foreign\n")
        return real_exchange(fd, first, second)

    monkeypatch.setattr(MODULE, "_rename_exchange", drift_then_exchange)
    monkeypatch.setattr(
        MODULE, "_fsync_exchange_directory",
        lambda _fd: (_ for _ in ()).throw(OSError("injected fsync failure")),
    )
    try:
        with pytest.raises(
            MODULE.HbaDeploymentError,
            match="POST_EXCHANGE_DIRECTORY_FSYNC_FAILED",
        ):
            MODULE._exchange_target(
                directory_fd, b"candidate\n", metadata,
                hashlib.sha256(b"base\n").hexdigest(),
            )
        assert target.read_bytes() == b"candidate\n"
        stages = list(tmp_path.glob(".obsidian-b64-hba-stage-*"))
        assert len(stages) == 1
        assert stages[0].read_bytes() == b"foreign\n"
    finally:
        os.close(directory_fd)


def test_state_directory_and_journal_are_exclusive_and_durable(tmp_path):
    directory_fd = MODULE._open_pgdata(tmp_path)
    state_fd = MODULE._mkdir_state(directory_fd)
    try:
        MODULE._write_new(
            state_fd, MODULE.BACKUP_NAME, b"original\n",
            mode=0o600, uid=0, gid=0,
        )
        MODULE._replace_journal(state_fd, {"phase": "BACKUP_VERIFIED"})
        MODULE._replace_journal(state_fd, {"phase": "APPLY_ATTEMPTED"})
        assert json.loads(
            (tmp_path / MODULE.STATE_DIRECTORY / MODULE.JOURNAL_NAME)
            .read_text("utf-8")
        ) == {"phase": "APPLY_ATTEMPTED"}
        assert MODULE._read_journal(state_fd) == {
            "phase": "APPLY_ATTEMPTED"
        }
        metadata = os.fstat(state_fd)
        assert metadata.st_uid == 0
        assert metadata.st_gid == 0
        assert metadata.st_mode & 0o777 == 0o700
        with pytest.raises(MODULE.HbaDeploymentError,
                           match="HBA_STATE_DIRECTORY_ALREADY_EXISTS"):
            MODULE._mkdir_state(directory_fd)
    finally:
        os.close(state_fd)
        os.close(directory_fd)


def test_read_rejects_symlink_target(tmp_path):
    (tmp_path / "real").write_text("value", encoding="utf-8")
    (tmp_path / MODULE.HBA_NAME).symlink_to("real")
    directory_fd = MODULE._open_pgdata(tmp_path)
    try:
        with pytest.raises(OSError):
            MODULE._read_at(directory_fd, MODULE.HBA_NAME)
    finally:
        os.close(directory_fd)


def test_reconcile_journal_accepts_crash_phases_and_pid_rebind():
    manifest = {
        "expectedOriginalSha256": "1" * 64,
        "expectedDeployedSha256": "2" * 64,
    }
    container = {
        "containerId": "3" * 64,
        "containerPid": 222,
        "imageId": "sha256:" + "6" * 64,
    }
    cluster = {"systemIdentifier": "444"}
    base = {
        "schemaVersion": "obsidian-b64-hba-journal.v1",
        "nonce": "5" * 32,
        "containerId": container["containerId"],
        "containerImageId": container["imageId"],
        "containerPid": 111,
        "systemIdentifier": cluster["systemIdentifier"],
        "originalSha256": manifest["expectedOriginalSha256"],
        "deployedSha256": manifest["expectedDeployedSha256"],
    }
    for phase in MODULE.RECOVERABLE_JOURNAL_PHASES:
        journal = {**base, "phase": phase}
        if phase == "DEPLOYED_VERIFIED":
            journal["verifiedAt"] = "2026-08-23T00:00:00+00:00"
        MODULE._validate_journal(
            journal, container, cluster, manifest,
            MODULE.RECOVERABLE_JOURNAL_PHASES, strict_pid=False,
        )
    with pytest.raises(MODULE.HbaDeploymentError,
                       match="ROLLBACK_JOURNAL_BINDING_MISMATCH"):
        MODULE._validate_journal(
            {**base, "phase": "CANDIDATE_INSTALLED"},
            container, cluster, manifest,
            MODULE.RECOVERABLE_JOURNAL_PHASES, strict_pid=True,
        )


def test_clean_state_rejects_unexpected_entry(tmp_path):
    directory_fd = MODULE._open_pgdata(tmp_path)
    state_fd = MODULE._mkdir_state(directory_fd)
    (tmp_path / MODULE.STATE_DIRECTORY / "foreign").write_text(
        "preserve", encoding="utf-8"
    )
    try:
        with pytest.raises(MODULE.HbaDeploymentError,
                           match="HBA_STATE_DIRECTORY_UNEXPECTED_ENTRY"):
            MODULE._clean_state(directory_fd, state_fd)
        assert (tmp_path / MODULE.STATE_DIRECTORY / "foreign").read_text(
            "utf-8"
        ) == "preserve"
    finally:
        os.close(state_fd)
        os.close(directory_fd)


def test_original_reconcile_validates_prejournal_partial_backup(tmp_path):
    original = b"exact original bytes\n"
    manifest = {
        "expectedOriginalSha256": hashlib.sha256(original).hexdigest(),
        "expectedDeployedSha256": "2" * 64,
    }
    container = {
        "containerId": "3" * 64,
        "containerPid": 222,
        "imageId": "sha256:" + "6" * 64,
    }
    cluster = {"systemIdentifier": "444"}
    directory_fd = MODULE._open_pgdata(tmp_path)
    state_fd = MODULE._mkdir_state(directory_fd)
    try:
        MODULE._write_new(
            state_fd, MODULE.BACKUP_NAME, original[:7],
            mode=0o600, uid=0, gid=0,
        )
        assert MODULE._validate_original_recovery_state(
            state_fd, original, container, cluster, manifest,
        ) == "PRE_JOURNAL_BACKUP_PARTIAL"
    finally:
        os.close(state_fd)
        os.close(directory_fd)


def test_original_reconcile_requires_bound_journal_and_exact_backup(
        monkeypatch, tmp_path):
    original = b"exact original bytes\n"
    manifest = {
        "expectedOriginalSha256": hashlib.sha256(original).hexdigest(),
        "expectedDeployedSha256": "2" * 64,
    }
    container = {
        "containerId": "3" * 64,
        "containerPid": 222,
        "imageId": "sha256:" + "6" * 64,
    }
    cluster = {"systemIdentifier": "444"}
    real_bundle = MODULE._validate_recovery_bundle
    real_read_recovery = MODULE._read_recovery_at

    def root_owned_bundle(*args, **kwargs):
        monkeypatch.setattr(
            MODULE, "_read_recovery_at",
            lambda fd, name, *, mode, uid, gid: real_read_recovery(
                fd, name, mode=mode, uid=0, gid=0
            ),
        )
        return real_bundle(*args, **kwargs)

    monkeypatch.setattr(
        MODULE, "_validate_recovery_bundle", root_owned_bundle
    )
    journal = {
        "schemaVersion": "obsidian-b64-hba-journal.v1",
        "nonce": "5" * 32,
        "phase": "APPLY_ATTEMPTED",
        "containerId": container["containerId"],
        "containerImageId": container["imageId"],
        "containerPid": 111,
        "systemIdentifier": cluster["systemIdentifier"],
        "originalSha256": manifest["expectedOriginalSha256"],
        "deployedSha256": manifest["expectedDeployedSha256"],
    }
    directory_fd = MODULE._open_pgdata(tmp_path)
    state_fd = MODULE._mkdir_state(directory_fd)
    try:
        MODULE._write_new(
            state_fd, MODULE.BACKUP_NAME, original,
            mode=0o600, uid=0, gid=0,
        )
        MODULE._replace_journal(state_fd, journal)
        assert MODULE._validate_original_recovery_state(
            state_fd, original, container, cluster, manifest,
        ) == "APPLY_ATTEMPTED"
        journal["containerId"] = "6" * 64
        MODULE._replace_journal(state_fd, journal)
        with pytest.raises(MODULE.HbaDeploymentError,
                           match="ROLLBACK_JOURNAL_BINDING_MISMATCH"):
            MODULE._validate_original_recovery_state(
                state_fd, original, container, cluster, manifest,
            )
    finally:
        os.close(state_fd)
        os.close(directory_fd)


def test_runner_exposes_only_bounded_statuses_and_never_restarts():
    source = MODULE_PATH.read_text("utf-8")
    for status in (
        "PRECHECK_FAILED_NO_MUTATION", "HBA_DEPLOYED_PARSED_DORMANT",
        "FAILED_ROLLED_BACK", "ROLLBACK_UNCERTAIN", "ROLLED_BACK",
        "RECONCILED_ORIGINAL", "RECONCILED_ROLLED_BACK",
    ):
        assert status in source
    assert "RENAME_EXCHANGE" in source
    assert "pg_reload_conf()" in source
    assert "pg_conf_load_time()" in source
    assert "ROLLBACK_JOURNAL_BINDING_MISMATCH" in source
    assert 'operation.add_argument("--reconcile"' in source
    assert 'journal["phase"] = "ROLLBACK_ATTEMPTED"' in source
    assert "systemctl" not in source
    assert "docker\", \"restart" not in source


def test_apply_requires_both_named_connection_environments(
        monkeypatch, capsys):
    monkeypatch.delenv("EXCHANGE_DATABASE_URL", raising=False)
    monkeypatch.delenv("B64_LOCAL_ADMIN_DSN", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "deploy_b64_snapshot_reader_hba.py",
        "--admin-postgres-env", "B64_LOCAL_ADMIN_DSN",
        "--container", "obsidian-postgres",
        "--expected-container-id", "a" * 64,
        "--expected-image-id", "sha256:" + "b" * 64,
        "--apply",
    ])
    assert MODULE.main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "FAILED"
    assert report["reason"] == "REQUIRED_POSTGRES_ENV_MISSING"
    assert report["roleLoginChanged"] is False
    assert report["serviceRestarted"] is False
