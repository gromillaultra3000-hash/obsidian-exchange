from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

rebind = importlib.import_module("b64_snapshot_reader_runtime_rebind")
watchdog = importlib.import_module("b64_snapshot_reader_watchdog")
transition_gate = importlib.import_module("b64_snapshot_reader_transition_gate")
shutdown_gate = importlib.import_module("b64_postgres_shutdown")


def test_contract_labels_cannot_collide_with_production_compose():
    assert rebind.CONTRACT_COMPOSE_PROJECT != "obsidian-postgres"
    assert rebind.CONTRACT_COMPOSE_SERVICE != "postgres"


CONTAINER = {
    "containerId": "a" * 64,
    "containerPid": 1234,
    "imageId": rebind.POSTGRES_17_11_IMAGE_ID,
    "health": "healthy",
    "startedAt": "2026-08-24T00:00:00Z",
    "restartCount": 0,
    "mountSource": "/var/lib/docker/volumes/obsidian-postgres-data/_data",
}


class FakeConnection:
    def __init__(self):
        self.info = type("Info", (), {"dsn": "synthetic-secretless-admin-dsn"})()

    def execute(self, *_args, **_kwargs):
        return self


def _state(authority: str, *, remaining: float = 90) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "serverVersionNum": 170011,
        "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        "postmasterStartTime": now,
        "serverNow": now,
        "roleOid": 123,
        "login": authority != "DORMANT",
        "passwordAbsent": authority == "DORMANT",
        "validUntil": now + dt.timedelta(seconds=remaining),
        "connectionLimit": 2,
        "sessions": 0,
        "authority": authority,
    }


def _watchdog_harness(monkeypatch, *, state: dict, acquired: bool, holders: list[dict]):
    connection = FakeConnection()
    inspect_calls = []

    def inspect(*_args, **_kwargs):
        inspect_calls.append(True)
        return dict(CONTAINER)

    monkeypatch.setattr(watchdog, "inspect_container", inspect)
    monkeypatch.setattr(watchdog, "_validate_runtime_bundle", lambda *_a, **_k: None)
    monkeypatch.setattr(
        watchdog,
        "admin_connection",
        lambda *_a, **_k: contextlib.nullcontext(connection),
    )
    monkeypatch.setattr(watchdog, "_host_lock", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(
        watchdog, "_activation_interlock_status",
        lambda *_a, **_k: contextlib.nullcontext(False),
    )
    monkeypatch.setattr(watchdog, "_role_state", lambda *_a, **_k: dict(state))
    monkeypatch.setattr(watchdog, "_acquire_runtime_lock", lambda *_a, **_k: acquired)
    monkeypatch.setattr(watchdog, "_runtime_lock_holders", lambda *_a, **_k: list(holders))
    monkeypatch.setattr(
        watchdog,
        "_verify_role",
        lambda *_a, **_k: {"status": "match"},
    )
    return connection, inspect_calls


def _run_watchdog(**kwargs):
    return watchdog.watchdog_once(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        **kwargs,
    )


def test_dormant_watchdog_run_is_ready_and_non_mutating(monkeypatch):
    _connection, inspections = _watchdog_harness(
        monkeypatch, state=_state("DORMANT"), acquired=True, holders=[]
    )
    monkeypatch.setattr(
        watchdog,
        "_force_dormant",
        lambda *_a: pytest.fail("dormant role must not be mutated"),
    )
    result = _run_watchdog()
    assert result["status"] == "DORMANT_VERIFIED"
    assert result["credentialState"] == "ABSENT"
    assert result["authorityIncreased"] is False
    assert len(inspections) == 2


def test_valid_live_lease_is_deferred(monkeypatch):
    holder = {
        "pid": 77,
        "user": "postgres",
        "applicationName": "obsidian-b64-lease-lock-" + "a" * 32,
        "unixSocket": True,
        "state": "idle",
    }
    _watchdog_harness(
        monkeypatch,
        state=_state("ACTIVE_LEASE", remaining=90),
        acquired=False,
        holders=[holder],
    )
    monkeypatch.setattr(
        watchdog,
        "_force_dormant",
        lambda *_a: pytest.fail("valid active lease must be deferred"),
    )
    result = _run_watchdog()
    assert result["status"] == "ACTIVE_LEASE_SUPERVISED"
    assert result["credentialState"] == "PRESENT"


@pytest.mark.parametrize(
    ("remaining", "expected"),
    [
        (-1, "EXPIRED_AUTHORITY_REVOKED_VERIFIED"),
        (300, "INVALID_EXPIRY_AUTHORITY_REVOKED_VERIFIED"),
    ],
)
def test_expired_or_unbounded_lease_is_revoked(monkeypatch, remaining, expected):
    holder = {
        "pid": 77,
        "user": "postgres",
        "applicationName": "obsidian-b64-lease-lock-" + "b" * 32,
        "unixSocket": True,
        "state": "idle",
    }
    connection, _ = _watchdog_harness(
        monkeypatch,
        state=_state("ACTIVE_LEASE", remaining=remaining),
        acquired=False,
        holders=[holder],
    )
    taken = []
    revoked = []
    monkeypatch.setattr(
        watchdog,
        "_terminate_holders_and_take_lock",
        lambda conn, rows: taken.append((conn, rows)),
    )
    monkeypatch.setattr(watchdog, "_force_dormant", lambda conn: revoked.append(conn))
    result = _run_watchdog()
    assert result["status"] == expected
    assert taken == [(connection, [holder])]
    assert revoked == [connection]
    assert result["credentialState"] == "ABSENT"


def test_shutdown_mode_revokes_otherwise_valid_lease(monkeypatch):
    holder = {
        "pid": 88,
        "user": "postgres",
        "applicationName": "obsidian-b64-lease-lock-" + "c" * 32,
        "unixSocket": True,
        "state": "idle",
    }
    _watchdog_harness(
        monkeypatch,
        state=_state("ACTIVE_LEASE", remaining=90),
        acquired=False,
        holders=[holder],
    )
    monkeypatch.setattr(
        watchdog, "_terminate_holders_and_take_lock", lambda *_a: None
    )
    revoked = []
    monkeypatch.setattr(watchdog, "_force_dormant", lambda *_a: revoked.append(True))
    result = _run_watchdog(require_dormant=True)
    assert result["status"] == "REQUIRED_DORMANT_AUTHORITY_REVOKED_VERIFIED"
    assert result["dormantRequired"] is True
    assert revoked == [True]


def test_shutdown_mode_supervises_valid_lease_only_with_live_activation_interlock(
    monkeypatch,
):
    holder = {
        "pid": 88,
        "user": "postgres",
        "applicationName": "obsidian-b64-lease-lock-" + "d" * 32,
        "unixSocket": True,
        "state": "idle",
    }
    _watchdog_harness(
        monkeypatch,
        state=_state("ACTIVE_LEASE", remaining=90),
        acquired=False,
        holders=[holder],
    )
    monkeypatch.setattr(
        watchdog, "_activation_interlock_status",
        lambda *_a, **_k: contextlib.nullcontext(True),
    )
    monkeypatch.setattr(
        watchdog, "_terminate_holders_and_take_lock",
        lambda *_a: pytest.fail("live activation lease must not be terminated"),
    )
    monkeypatch.setattr(
        watchdog, "_force_dormant",
        lambda *_a: pytest.fail("live activation lease must not be revoked"),
    )
    result = _run_watchdog(require_dormant=True)
    assert result["status"] == (
        "ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED"
    )
    assert result["activationInterlockHeld"] is True
    assert result["roleLoginState"] == "ENABLED"
    assert result["credentialState"] == "PRESENT"


def test_activation_interlock_holds_idle_side_and_detects_live_owner(tmp_path):
    path = tmp_path / "activation.lock"
    with watchdog._activation_interlock_status(str(path)) as activation_live:
        assert activation_live is False
        competing = os.open(path, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                watchdog.fcntl.flock(
                    competing, watchdog.fcntl.LOCK_EX | watchdog.fcntl.LOCK_NB
                )
        finally:
            os.close(competing)
    owner = os.open(path, os.O_RDWR)
    try:
        watchdog.fcntl.flock(owner, watchdog.fcntl.LOCK_EX)
        with watchdog._activation_interlock_status(str(path)) as activation_live:
            assert activation_live is True
    finally:
        os.close(owner)


def test_invalid_lock_holder_with_authority_is_revoked(monkeypatch):
    holder = {
        "pid": 99,
        "user": "foreign",
        "applicationName": "not-an-issuer",
        "unixSocket": True,
        "state": "idle",
    }
    _watchdog_harness(
        monkeypatch,
        state=_state("INCONSISTENT"),
        acquired=False,
        holders=[holder],
    )
    monkeypatch.setattr(
        watchdog, "_terminate_holders_and_take_lock", lambda *_a: None
    )
    revoked = []
    monkeypatch.setattr(watchdog, "_force_dormant", lambda *_a: revoked.append(True))
    result = _run_watchdog()
    assert result["status"] == "UNTRUSTED_AUTHORITY_REVOKED_VERIFIED"
    assert revoked == [True]


def test_container_change_during_watchdog_is_failure(monkeypatch):
    connection = FakeConnection()
    values = [dict(CONTAINER), {**CONTAINER, "containerPid": 9876}]
    monkeypatch.setattr(watchdog, "inspect_container", lambda *_a, **_k: values.pop(0))
    monkeypatch.setattr(watchdog, "_validate_runtime_bundle", lambda *_a, **_k: None)
    monkeypatch.setattr(
        watchdog, "admin_connection", lambda *_a, **_k: contextlib.nullcontext(connection)
    )
    monkeypatch.setattr(watchdog, "_host_lock", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(
        watchdog, "_activation_interlock_status",
        lambda *_a, **_k: contextlib.nullcontext(False),
    )
    monkeypatch.setattr(watchdog, "_role_state", lambda *_a, **_k: _state("DORMANT"))
    monkeypatch.setattr(watchdog, "_acquire_runtime_lock", lambda *_a: True)
    monkeypatch.setattr(watchdog, "_verify_role", lambda *_a, **_k: {})
    with pytest.raises(watchdog.WatchdogError, match="CONTAINER_CHANGED"):
        _run_watchdog()


def test_invalid_bundle_forces_dormant_before_failure(monkeypatch):
    connection = FakeConnection()
    states = [_state("ACTIVE_LEASE"), _state("DORMANT")]
    terminated = []
    revoked = []
    monkeypatch.setattr(watchdog, "inspect_container", lambda *_a, **_k: dict(CONTAINER))
    monkeypatch.setattr(
        watchdog,
        "_validate_runtime_bundle",
        lambda *_a, **_k: (_ for _ in ()).throw(
            watchdog.WatchdogError("SYNTHETIC_BUNDLE_INVALID")
        ),
    )
    monkeypatch.setattr(
        watchdog,
        "admin_connection",
        lambda *_a, **_k: contextlib.nullcontext(connection),
    )
    monkeypatch.setattr(watchdog, "_host_lock", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(
        watchdog, "_activation_interlock_status",
        lambda *_a, **_k: contextlib.nullcontext(False),
    )
    monkeypatch.setattr(watchdog, "_role_state", lambda *_a, **_k: states.pop(0))
    monkeypatch.setattr(watchdog, "_acquire_runtime_lock", lambda *_a: False)
    monkeypatch.setattr(watchdog, "_runtime_lock_holders", lambda *_a: [{"pid": 55}])
    monkeypatch.setattr(
        watchdog,
        "_terminate_holders_and_take_lock",
        lambda *_a: terminated.append(True),
    )
    monkeypatch.setattr(watchdog, "_force_dormant", lambda *_a: revoked.append(True))
    monkeypatch.setattr(watchdog, "_verify_role", lambda *_a, **_k: {})
    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_BUNDLE_INVALID_AUTHORITY_REVOKED",
    ):
        _run_watchdog()
    assert terminated == [True]
    assert revoked == [True]


@pytest.mark.parametrize(
    ("previous_image", "expected_image"),
    [
        (rebind.POSTGRES_17_10_IMAGE_ID, rebind.POSTGRES_17_11_IMAGE_ID),
        (rebind.POSTGRES_17_11_IMAGE_ID, rebind.POSTGRES_17_11_IMAGE_ID),
    ],
)
def test_transition_gate_rebinds_allowlisted_runtime(
    monkeypatch, previous_image, expected_image
):
    monkeypatch.setattr(
        transition_gate, "_host_lock", lambda *_a, **_k: contextlib.nullcontext()
    )
    monkeypatch.setattr(
        transition_gate, "inspect_container", lambda *_a, **_k: dict(CONTAINER)
    )
    monkeypatch.setattr(
        transition_gate,
        "_previous_binding",
        lambda *_a, **_k: ("b" * 64, previous_image),
    )
    calls = []

    def rebound(**kwargs):
        calls.append(kwargs)
        return {"status": "RUNTIME_REBOUND_VERIFIED"}

    monkeypatch.setattr(transition_gate, "rebind_runtime", rebound)
    monkeypatch.setattr(
        transition_gate,
        "watchdog_once",
        lambda **_k: {
            "status": "DORMANT_VERIFIED",
            "roleLoginState": "DISABLED",
            "credentialState": "ABSENT",
            "container": dict(CONTAINER),
        },
    )
    result = transition_gate.transition_gate_once(
        expected_image_id=expected_image,
        apply=True,
    )
    assert result["status"] == "TRANSITION_GATE_VERIFIED"
    assert calls[0]["host_lock_held"] is True
    assert calls[0]["previous_image_id"] == previous_image


def test_transition_gate_rejects_unallowlisted_or_dry_run(monkeypatch):
    monkeypatch.setattr(
        transition_gate, "_host_lock", lambda *_a, **_k: contextlib.nullcontext()
    )
    monkeypatch.setattr(
        transition_gate, "inspect_container", lambda *_a, **_k: dict(CONTAINER)
    )
    monkeypatch.setattr(
        transition_gate,
        "_previous_binding",
        lambda *_a, **_k: ("b" * 64, "sha256:" + "0" * 64),
    )
    with pytest.raises(
        transition_gate.TransitionGateError,
        match="JOURNAL_IMAGE_TRANSITION_NOT_ALLOWED",
    ):
        transition_gate.transition_gate_once(apply=True)

    monkeypatch.setattr(
        transition_gate,
        "_previous_binding",
        lambda *_a, **_k: ("b" * 64, rebind.POSTGRES_17_10_IMAGE_ID),
    )
    monkeypatch.setattr(
        transition_gate,
        "rebind_runtime",
        lambda **_k: {"status": "RUNTIME_REBIND_REQUIRED"},
    )
    with pytest.raises(
        transition_gate.TransitionGateError,
        match="TRANSITION_GATE_APPLY_REQUIRED",
    ):
        transition_gate.transition_gate_once(apply=False)


def test_transition_gate_rejects_missing_journal_image(monkeypatch, tmp_path):
    pgdata_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    state_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    journal = {
        "schemaVersion": "obsidian-b64-hba-journal.v1",
        "phase": "DEPLOYED_VERIFIED",
        "containerId": "b" * 64,
        "containerPid": 42,
        "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        "originalSha256": rebind.EXPECTED_ORIGINAL_HBA_SHA256,
        "deployedSha256": rebind.EXPECTED_DEPLOYED_HBA_SHA256,
        "nonce": "c" * 32,
        "verifiedAt": "2026-08-24T00:00:00+00:00",
    }
    monkeypatch.setattr(
        transition_gate,
        "_open_bundle",
        lambda *_a: (os.dup(pgdata_fd), os.dup(state_fd), journal, None, False),
    )
    try:
        with pytest.raises(
            transition_gate.TransitionGateError,
            match="JOURNAL_IMAGE_BINDING_INVALID",
        ):
            transition_gate._previous_binding(
                dict(CONTAINER), rebind.PRODUCTION_SYSTEM_IDENTIFIER
            )
    finally:
        os.close(state_fd)
        os.close(pgdata_fd)


def test_shutdown_detects_allowlisted_17_10_and_postverifies_timeout(monkeypatch):
    inspect_running = subprocess.CompletedProcess(
        [],
        0,
        stdout=json.dumps([{"Image": rebind.POSTGRES_17_10_IMAGE_ID}]),
        stderr="",
    )
    inspect_stopped = subprocess.CompletedProcess(
        [],
        0,
        stdout=json.dumps([{"State": {"Running": False, "Pid": 0}}]),
        stderr="",
    )
    inspections = [inspect_running, inspect_stopped]

    def run(args, **_kwargs):
        if args[1] == "inspect":
            return inspections.pop(0)
        raise subprocess.TimeoutExpired(args, 140)

    monkeypatch.setattr(shutdown_gate.subprocess, "run", run)
    monkeypatch.setattr(
        shutdown_gate,
        "watchdog_once",
        lambda **kwargs: {
            "watchdogReady": True,
            "credentialState": "ABSENT",
            "roleLoginState": "DISABLED",
            "expectedImage": kwargs["expected_image_id"],
        },
    )
    result, code = shutdown_gate.shutdown()
    assert result["reconciliation"]["expectedImage"] == rebind.POSTGRES_17_10_IMAGE_ID
    assert result["containerStopTimedOut"] is True
    assert result["containerStoppedPostverified"] is True
    assert result["status"] == "STOPPED_RECONCILE_UNCERTAIN"
    assert code == 2


def test_journal_validation_accepts_only_exact_deployed_binding():
    journal = {
        "schemaVersion": "obsidian-b64-hba-journal.v1",
        "phase": "DEPLOYED_VERIFIED",
        "containerId": "a" * 64,
        "containerImageId": rebind.POSTGRES_17_11_IMAGE_ID,
        "containerPid": 123,
        "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        "originalSha256": rebind.EXPECTED_ORIGINAL_HBA_SHA256,
        "deployedSha256": rebind.EXPECTED_DEPLOYED_HBA_SHA256,
        "nonce": "b" * 32,
        "verifiedAt": "2026-08-24T00:00:00+00:00",
    }
    rebind._validate_journal(
        journal,
        allowed_container_ids={"a" * 64},
        allowed_image_ids={rebind.POSTGRES_17_11_IMAGE_ID},
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    for field, value in (
        ("phase", "APPLY_ATTEMPTED"),
        ("containerId", "c" * 64),
        ("containerImageId", rebind.POSTGRES_17_10_IMAGE_ID),
        ("deployedSha256", "d" * 64),
    ):
        drifted = {**journal, field: value}
        with pytest.raises(rebind.RebindError, match="HBA_JOURNAL_BINDING_MISMATCH"):
            rebind._validate_journal(
                drifted,
                allowed_container_ids={"a" * 64},
                allowed_image_ids={rebind.POSTGRES_17_11_IMAGE_ID},
                expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
            )


def test_atomic_journal_replace_fsyncs_and_leaves_no_temp(tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    try:
        journal = {"schemaVersion": "synthetic", "phase": "DEPLOYED_VERIFIED"}
        rebind._replace_journal(state_fd, journal)
        assert json.loads((state / "journal.json").read_text("utf-8")) == journal
        assert list(state.glob("journal.*.tmp")) == []
        assert (state / "journal.json").stat().st_mode & 0o777 == 0o600
    finally:
        os.close(state_fd)


def test_crash_before_journal_rename_retains_one_recoverable_temp(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    real_rename = os.rename
    monkeypatch.setattr(rebind.os, "rename", lambda *_a, **_k: (_ for _ in ()).throw(OSError("crash")))
    try:
        with pytest.raises(OSError, match="crash"):
            rebind._replace_journal(state_fd, {"phase": "DEPLOYED_VERIFIED"})
    finally:
        monkeypatch.setattr(rebind.os, "rename", real_rename)
        os.close(state_fd)
    pending = list(state.glob("journal.*.tmp"))
    assert len(pending) == 1
    assert json.loads(pending[0].read_text("utf-8"))["phase"] == "DEPLOYED_VERIFIED"


def test_ownership_reclaim_resumes_after_partial_chown(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    pending_name = "journal." + "a" * 16 + ".tmp"
    for name in (rebind.JOURNAL_NAME, pending_name):
        path = state / name
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
        os.chown(path, 70, 0)
    os.chown(state, 70, 0)
    state_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    real_fchown = os.fchown
    calls = 0

    def crash_after_first_chown(fd, uid, gid):
        nonlocal calls
        real_fchown(fd, uid, gid)
        calls += 1
        if calls == 1:
            raise OSError("injected ownership crash")

    try:
        monkeypatch.setattr(rebind.os, "fchown", crash_after_first_chown)
        with pytest.raises(OSError, match="injected ownership crash"):
            rebind._reclaim_state_ownership(state_fd, (pending_name, {}))
        monkeypatch.setattr(rebind.os, "fchown", real_fchown)
        rebind._reclaim_state_ownership(state_fd, (pending_name, {}))
    finally:
        os.close(state_fd)
    assert (state.stat().st_uid, state.stat().st_gid) == (0, 0)
    assert ((state / rebind.JOURNAL_NAME).stat().st_uid,
            (state / rebind.JOURNAL_NAME).stat().st_gid) == (0, 0)
    assert ((state / pending_name).stat().st_uid,
            (state / pending_name).stat().st_gid) == (0, 0)


@pytest.mark.parametrize(
    "fault",
    [
        "create", "post_create", "partial_write", "temp_fsync", "rename",
        "directory_fsync",
    ],
)
def test_journal_replace_crashes_are_idempotently_repaired(
    monkeypatch, tmp_path, fault
):
    original = b"synthetic original hba\n"
    deployed = b"synthetic deployed hba\n"
    monkeypatch.setattr(rebind, "EXPECTED_ORIGINAL_HBA_SHA256", rebind._sha256(original))
    monkeypatch.setattr(rebind, "EXPECTED_DEPLOYED_HBA_SHA256", rebind._sha256(deployed))
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir(mode=0o700)
    os.chown(pgdata, 70, 70)
    hba = pgdata / rebind.HBA_NAME
    hba.write_bytes(deployed)
    hba.chmod(0o600)
    os.chown(hba, 70, 70)
    state = pgdata / rebind.STATE_DIRECTORY
    state.mkdir(mode=0o700)
    backup = state / rebind.BACKUP_NAME
    backup.write_bytes(original)
    backup.chmod(0o600)
    os.chown(backup, 70, 70)
    container = {
        **CONTAINER,
        "containerId": "a" * 64,
        "containerPid": 1234,
        "mountSource": str(pgdata),
    }
    journal = {
        "schemaVersion": "obsidian-b64-hba-journal.v1",
        "phase": "DEPLOYED_VERIFIED",
        "containerId": container["containerId"],
        "containerImageId": rebind.POSTGRES_17_11_IMAGE_ID,
        "containerPid": container["containerPid"],
        "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        "originalSha256": rebind.EXPECTED_ORIGINAL_HBA_SHA256,
        "deployedSha256": rebind.EXPECTED_DEPLOYED_HBA_SHA256,
        "nonce": "b" * 32,
        "verifiedAt": "2026-08-24T00:00:00+00:00",
    }
    journal_path = state / rebind.JOURNAL_NAME
    journal_path.write_text(json.dumps(journal) + "\n", encoding="utf-8")
    journal_path.chmod(0o600)
    state_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY)
    real_open = os.open
    real_fchmod = os.fchmod
    real_write = os.write
    real_fsync = os.fsync
    real_rename = os.rename
    fsync_calls = 0
    write_calls = 0

    def fault_open(name, flags, *args, **kwargs):
        if (
            fault == "create"
            and isinstance(name, str)
            and rebind.TEMP_JOURNAL.fullmatch(name)
            and flags & os.O_CREAT
        ):
            raise OSError("injected create crash")
        return real_open(name, flags, *args, **kwargs)

    def fault_write(fd, data):
        nonlocal write_calls
        write_calls += 1
        if fault == "partial_write" and write_calls == 1:
            real_write(fd, data[:1])
            raise OSError("injected partial write crash")
        return real_write(fd, data)

    def fault_fchmod(fd, mode):
        real_fchmod(fd, mode)
        if fault == "post_create":
            raise OSError("injected post create crash")

    def fault_fsync(fd):
        nonlocal fsync_calls
        fsync_calls += 1
        if fault == "temp_fsync" and fsync_calls == 1:
            raise OSError("injected temp fsync crash")
        if fault == "directory_fsync" and fsync_calls == 2:
            raise OSError("injected directory fsync crash")
        return real_fsync(fd)

    def fault_rename(*args, **kwargs):
        if fault == "rename":
            raise OSError("injected rename crash")
        return real_rename(*args, **kwargs)

    try:
        with monkeypatch.context() as injected:
            injected.setattr(rebind.os, "open", fault_open)
            injected.setattr(rebind.os, "fchmod", fault_fchmod)
            injected.setattr(rebind.os, "write", fault_write)
            injected.setattr(rebind.os, "fsync", fault_fsync)
            injected.setattr(rebind.os, "rename", fault_rename)
            with pytest.raises(OSError, match="injected"):
                rebind._replace_journal(state_fd, {**journal, "verifiedAt": "later"})
    finally:
        os.close(state_fd)
    status = rebind._apply_bundle_rebind(
        container=container,
        previous_container_id=container["containerId"],
        previous_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        apply=True,
    )
    assert status in {
        "ALREADY_RUNTIME_BOUND",
        "RUNTIME_REBIND_TEMP_CLEANED_VERIFIED",
        "RUNTIME_REBIND_INVALID_TEMP_CLEANED_VERIFIED",
    }
    assert set(item.name for item in state.iterdir()) == {
        rebind.JOURNAL_NAME,
        rebind.BACKUP_NAME,
    }


def test_production_transition_allowlist_is_exact():
    assert (
        rebind.POSTGRES_17_10_IMAGE_ID,
        rebind.POSTGRES_17_11_IMAGE_ID,
    ) in rebind.PRODUCTION_IMAGE_TRANSITIONS
    assert (
        rebind.POSTGRES_17_11_IMAGE_ID,
        rebind.POSTGRES_17_10_IMAGE_ID,
    ) in rebind.PRODUCTION_IMAGE_TRANSITIONS
    assert ("sha256:" + "0" * 64, rebind.POSTGRES_17_11_IMAGE_ID) not in \
        rebind.PRODUCTION_IMAGE_TRANSITIONS


def test_runtime_surfaces_contain_no_secret_input_channel():
    watchdog_source = (POSTGRES / "b64_snapshot_reader_watchdog.py").read_text("utf-8")
    rebind_source = (POSTGRES / "b64_snapshot_reader_runtime_rebind.py").read_text("utf-8")
    unit = (ROOT / "deploy/systemd/obsidian-postgres.service").read_text("utf-8")
    timer_service = (
        ROOT / "deploy/systemd/obsidian-b64-snapshot-reader-watchdog.service"
    ).read_text("utf-8")
    for source in (watchdog_source, rebind_source):
        assert "PGPASSWORD" not in source
        assert "EXCHANGE_DATABASE_URL" not in source
        assert "password.decode" not in source
        assert "pg_authid" in source
    assert "ExecStartPost=" in unit and "--require-dormant" in unit
    assert "ReadWritePaths=/run/lock " in unit
    assert "--require-dormant" in timer_service
    assert "ReadWritePaths=/run/lock " in timer_service
    assert "EnvironmentFile=" not in timer_service
    assert "LoadCredential=" not in timer_service
    assert "RestrictAddressFamilies=AF_UNIX" in timer_service
