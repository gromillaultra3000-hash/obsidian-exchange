from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib
import json
import os
import signal
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


def _write_recovery_package(parent: Path) -> dict:
    parent.chmod(0o700)
    package = parent / watchdog.RECOVERY_PACKAGE_NAME
    package.mkdir(mode=0o700)
    artifacts = {
        "keyring.json": b'{"keyring":true}\n',
        "decision.json": b'{"decision":true}\n',
        "activation-plan.json": b'{"plan":true}\n',
    }
    binding = {
        "route": watchdog.ACTIVATION_ROUTE,
        "environment": "PRODUCTION",
        "runNonce": "recovery_nonce_1234",
        "action": watchdog.RECOVERY_ACTION,
        "automaticRetryAllowed": False,
        "expectedKeyringSha256": "1" * 64,
        "planSha256": "2" * 64,
        "decisionSha256": "3" * 64,
    }
    manifest = {
        "schemaVersion": watchdog.RECOVERY_PACKAGE_SCHEMA,
        **binding,
        "files": {
            name: {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }
            for name, raw in artifacts.items()
        },
    }
    manifest_raw = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode() + b"\n"
    for name, raw in {**artifacts, "manifest.json": manifest_raw}.items():
        path = package / name
        path.write_bytes(raw)
        path.chmod(0o400)
    package.chmod(0o500)
    request = {
        "schemaVersion": watchdog.RECOVERY_REQUEST_SCHEMA,
        **binding,
        "manifestSha256": hashlib.sha256(manifest_raw).hexdigest(),
    }
    request_path = parent / watchdog.RECOVERY_REQUEST_NAME
    request_path.write_text(
        json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    request_path.chmod(0o400)
    return {"package": package, "request": request_path, **artifacts}


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


def test_fixed_recovery_package_is_exactly_bound(monkeypatch, tmp_path):
    written = _write_recovery_package(tmp_path)
    monkeypatch.setattr(watchdog, "RECOVERY_PARENT", tmp_path)
    loaded = watchdog._load_recovery_package()
    assert loaded is not None
    assert loaded["stagedWithoutRequest"] is False
    assert loaded["request"]["runNonce"] == "recovery_nonce_1234"
    assert loaded["keyring.json"] == written["keyring.json"]


@pytest.mark.parametrize("fault", ["extra", "mode", "hardlink", "symlink"])
def test_fixed_recovery_package_rejects_unsafe_entries(
    monkeypatch, tmp_path, fault,
):
    written = _write_recovery_package(tmp_path)
    package = written["package"]
    package.chmod(0o700)
    if fault == "extra":
        extra = package / "foreign"
        extra.write_text("x", encoding="utf-8")
        extra.chmod(0o400)
    elif fault == "mode":
        (package / "decision.json").chmod(0o600)
    elif fault == "hardlink":
        target = package / "decision.json"
        os.link(target, tmp_path / "decision-hardlink")
    else:
        target = package / "decision.json"
        target.unlink()
        target.symlink_to(package / "keyring.json")
    package.chmod(0o500)
    monkeypatch.setattr(watchdog, "RECOVERY_PARENT", tmp_path)
    with pytest.raises(watchdog.WatchdogError):
        watchdog._load_recovery_package()


def test_package_without_request_is_staged_and_not_interpreted(
    monkeypatch, tmp_path,
):
    written = _write_recovery_package(tmp_path)
    written["request"].unlink()
    monkeypatch.setattr(watchdog, "RECOVERY_PARENT", tmp_path)
    assert watchdog._load_recovery_package() == {
        "stagedWithoutRequest": True
    }


def _orchestrator_dormant_result() -> dict:
    return {
        "schemaVersion": "obsidian-b64-snapshot-reader-watchdog.v1",
        "status": "DORMANT_VERIFIED", "watchdogReady": True,
        "container": dict(CONTAINER), "roleLoginState": "DISABLED",
        "credentialState": "ABSENT", "activeSessions": 0,
        "dormantRequired": True, "activationInterlockHeld": False,
        "customerRowsRead": False,
        "authorityIncreased": False,
    }


@pytest.fixture
def idle_recovery_discovery(monkeypatch):
    monkeypatch.setattr(
        watchdog, "_activation_interlock_status",
        lambda *_args, **_kwargs: contextlib.nullcontext(False),
    )
    monkeypatch.setattr(
        watchdog, "_runtime_commit_markers", lambda: {
            "rollbackIntent": None,
            "launchRequest": {
                "runNonce": "recovery_nonce_1234",
                "expectedKeyringSha256": "1" * 64,
                "planSha256": "2" * 64,
                "decisionSha256": "3" * 64,
                "recoveryManifestSha256": None,
            },
        },
    )


def _cleanup_recovery_fixture(*, expires_at_epoch: int):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    nonce = "recovery_nonce_1234"
    target = {
        "containerName": rebind.PRODUCTION_CONTAINER,
        "containerId": CONTAINER["containerId"],
        "imageId": rebind.POSTGRES_17_11_IMAGE_ID,
        "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    }
    recovery = activation.VerifiedRecovery(
        environment="PRODUCTION", run_nonce=nonce,
        plan_sha256="2" * 64, decision_sha256="3" * 64,
        keyring_sha256="1" * 64,
        derived_execution_plan_sha256="4" * 64,
        decision_expires_at_epoch=expires_at_epoch, target=target,
        limits=dict(activation.LIMITS),
        _recovery_seal=activation._VERIFIED_RECOVERY_SEAL,
    )
    package = {
        "stagedWithoutRequest": False,
        "request": {
            "runNonce": nonce, "expectedKeyringSha256": "1" * 64,
            "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        },
        "keyring.json": b"keyring", "decision.json": b"decision",
        "activation-plan.json": b"plan",
    }
    return activation, recovery, package


def _write_outer_journal(
    root: Path, nonce: str, state: str,
) -> None:
    journal_root = root / "journal"
    if not journal_root.exists():
        journal_root.mkdir(mode=0o700)
    lock = journal_root / f".{nonce}.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    receipt_sha = None
    if state == "CLOSED":
        receipt = journal_root / f"{nonce}.receipt.json"
        receipt.write_bytes(b"{}\n")
        receipt.chmod(0o600)
        receipt_sha = hashlib.sha256(b"{}").hexdigest()
    value = {
        "schemaVersion": watchdog.ACTIVATION_JOURNAL_SCHEMA,
        "route": watchdog.ACTIVATION_ROUTE, "runNonce": nonce,
        "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        "state": state, "attempt": 1, "retryAllowed": False,
        "receiptSha256": receipt_sha, "reasonCode": None,
    }
    journal = journal_root / f"{nonce}.json"
    journal.write_text(json.dumps(value) + "\n", encoding="utf-8")
    journal.chmod(0o600)


def _execution_receipt(nonce: str) -> dict:
    return {
        "schemaVersion": watchdog.ACTIVATION_RECEIPT_SCHEMA,
        "route": watchdog.ACTIVATION_ROUTE,
        "environment": "PRODUCTION", "runNonce": nonce,
        "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        "status": "COMPLETED_DORMANT_VERIFIED",
        "archiveBytes": 4096, "archiveSha256": "4" * 64,
        "catalogEquality": True, "tableEquality": True,
        "credentialIssued": True, "credentialRevoked": True,
        "sourceSessionClosed": True,
        "readerLoginState": "DISABLED",
        "readerCredentialState": "ABSENT", "readerActiveSessions": 0,
        "registeredWorkspaceAbsent": True,
        "dumpContainerAbsent": True, "restoreContainerAbsent": True,
        "containerTmpfsLifetimesEnded": True,
        "productionDataRetained": False,
        "automaticRetryAllowed": False, "actionAllowed": False,
    }


def test_journal_scan_is_exact_and_rejects_multiple_incomplete(
    monkeypatch, tmp_path,
):
    activation_root = tmp_path / "activation"
    activation_root.mkdir(mode=0o700)
    _write_outer_journal(activation_root, "recovery_nonce_1234", "RUNNING")
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root
    )
    scanned = watchdog._scan_activation_journals()
    assert scanned["recovery_nonce_1234"]["state"] == "RUNNING"
    _write_outer_journal(activation_root, "recovery_nonce_5678", "CLAIMED")
    with pytest.raises(
        watchdog.WatchdogError, match="MULTIPLE_INCOMPLETE_ACTIVATIONS"
    ):
        watchdog._scan_activation_journals()


def test_journal_scan_rejects_orphan_lock_and_foreign_entry(
    monkeypatch, tmp_path,
):
    activation_root = tmp_path / "activation"
    activation_root.mkdir(mode=0o700)
    journal_root = activation_root / "journal"
    journal_root.mkdir(mode=0o700)
    lock = journal_root / ".recovery_nonce_1234.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root
    )
    with pytest.raises(watchdog.WatchdogError, match="LOCK_BINDING_MISMATCH"):
        watchdog._scan_activation_journals()
    lock.unlink()
    foreign = journal_root / "latest"
    foreign.write_text("x", encoding="utf-8")
    with pytest.raises(watchdog.WatchdogError, match="FOREIGN_ENTRY"):
        watchdog._scan_activation_journals()


def test_journal_scan_defers_a_live_execution_lock(monkeypatch, tmp_path):
    activation_root = tmp_path / "activation"
    activation_root.mkdir(mode=0o700)
    journal_root = activation_root / "journal"
    journal_root.mkdir(mode=0o700)
    lock = journal_root / ".recovery_nonce_1234.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    descriptor = os.open(lock, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root
    )
    try:
        with pytest.raises(
            watchdog.WatchdogError,
            match="WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED",
        ):
            watchdog._scan_activation_journals()
    finally:
        os.close(descriptor)


def test_journal_scan_reobserves_a_concurrent_atomic_transition(monkeypatch):
    observations = iter([
        watchdog.WatchdogError("WATCHDOG_ACTIVATION_JOURNAL_CHANGED"),
        {"recovery_nonce_1234": {"state": "CLOSED"}},
    ])

    def observe():
        value = next(observations)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(watchdog, "_scan_activation_journals_snapshot", observe)
    assert watchdog._scan_activation_journals()[
        "recovery_nonce_1234"
    ]["state"] == "CLOSED"

    observations = iter([
        watchdog.WatchdogError("WATCHDOG_ACTIVATION_JOURNAL_CHANGED"),
        watchdog.WatchdogError("WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED"),
    ])
    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED",
    ):
        watchdog._scan_activation_journals()


@pytest.mark.parametrize(
    "kill_point", ["partial_write", "before_replace", "after_replace"],
)
def test_journal_scan_repairs_real_killed_outer_transition(
    monkeypatch, tmp_path, kill_point,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_root = tmp_path / "activation"
    journal_root = activation_root / "journal"
    activation_root.mkdir(mode=0o700)
    journal_root.mkdir(mode=0o700)
    binding = activation._LaunchClaimBinding(
        run_nonce="recovery_nonce_1234",
        plan_sha256="2" * 64, decision_sha256="3" * 64,
    )
    journal = activation.ActivationJournal(journal_root, binding)
    lock_fd = journal.acquire_execution_lock()
    os.close(lock_fd)
    journal.claim()
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root,
    )

    child = os.fork()
    if child == 0:
        if kill_point == "partial_write":
            def partial_write(descriptor, raw):
                os.write(descriptor, raw[:max(1, len(raw) // 2)])
                os.kill(os.getpid(), signal.SIGKILL)

            activation._write_all = partial_write
        else:
            real_replace = activation.os.replace

            def killed_replace(*args, **kwargs):
                if kill_point == "after_replace":
                    real_replace(*args, **kwargs)
                os.kill(os.getpid(), signal.SIGKILL)

            activation.os.replace = killed_replace
        journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL

    scanned = watchdog._scan_activation_journals()
    assert scanned[binding.run_nonce]["state"] == "RUNNING"
    assert not (journal_root / journal.transition_name).exists()


@pytest.mark.parametrize(
    "kill_point", ["partial_write", "before_publish", "after_publish"],
)
def test_journal_scan_repairs_real_killed_receipt_publication(
    monkeypatch, tmp_path, kill_point,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_root = tmp_path / "activation"
    journal_root = activation_root / "journal"
    activation_root.mkdir(mode=0o700)
    journal_root.mkdir(mode=0o700)
    binding = activation._LaunchClaimBinding(
        run_nonce="recovery_nonce_1234",
        plan_sha256="2" * 64, decision_sha256="3" * 64,
    )
    journal = activation.ActivationJournal(journal_root, binding)
    lock_fd = journal.acquire_execution_lock()
    os.close(lock_fd)
    journal.claim()
    journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root,
    )
    receipt = _execution_receipt(binding.run_nonce)

    child = os.fork()
    if child == 0:
        if kill_point == "partial_write":
            def partial_write(descriptor, raw):
                os.write(descriptor, raw[:max(1, len(raw) // 2)])
                os.kill(os.getpid(), signal.SIGKILL)

            activation._write_all = partial_write
        else:
            real_publish = activation.ActivationJournal._rename_noreplace

            def killed_publish(directory_fd, source, target):
                if kill_point == "after_publish":
                    real_publish(directory_fd, source, target)
                os.kill(os.getpid(), signal.SIGKILL)

            activation.ActivationJournal._rename_noreplace = staticmethod(
                killed_publish
            )
        journal.write_receipt(receipt)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL

    scanned = watchdog._scan_activation_journals()
    observed = scanned[binding.run_nonce]
    if kill_point == "partial_write":
        assert observed["state"] == "HOLD"
        assert "residualReceiptSha256" not in observed
        assert not (journal_root / journal.receipt_name).exists()
    else:
        assert observed["state"] == "RUNNING"
        assert observed["residualReceiptSha256"] == hashlib.sha256(
            activation._canonical(receipt)
        ).hexdigest()
    assert not (journal_root / journal.receipt_temp_name).exists()


def test_journal_scan_repairs_partial_closed_transition_to_recoverable_hold(
    monkeypatch, tmp_path,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_root = tmp_path / "activation"
    journal_root = activation_root / "journal"
    activation_root.mkdir(mode=0o700)
    journal_root.mkdir(mode=0o700)
    binding = activation._LaunchClaimBinding(
        run_nonce="recovery_nonce_1234",
        plan_sha256="2" * 64, decision_sha256="3" * 64,
    )
    journal = activation.ActivationJournal(journal_root, binding)
    lock_fd = journal.acquire_execution_lock()
    os.close(lock_fd)
    journal.claim()
    journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
    receipt = _execution_receipt(binding.run_nonce)
    receipt_sha = journal.write_receipt(receipt)
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root,
    )

    child = os.fork()
    if child == 0:
        def partial_write(descriptor, raw):
            os.write(descriptor, raw[:max(1, len(raw) // 2)])
            os.kill(os.getpid(), signal.SIGKILL)

        activation._write_all = partial_write
        journal.transition(
            expected_state={"RUNNING"}, state="CLOSED",
            receipt_sha256=receipt_sha,
        )
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL

    observed = watchdog._scan_activation_journals()[binding.run_nonce]
    assert observed["state"] == "HOLD"
    assert observed["residualReceiptSha256"] == receipt_sha
    assert not (journal_root / journal.transition_name).exists()


def test_journal_scan_repairs_combined_receipt_and_hold_transition_prefixes(
    monkeypatch, tmp_path,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_root = tmp_path / "activation"
    journal_root = activation_root / "journal"
    activation_root.mkdir(mode=0o700)
    journal_root.mkdir(mode=0o700)
    binding = activation._LaunchClaimBinding(
        run_nonce="recovery_nonce_1234",
        plan_sha256="2" * 64, decision_sha256="3" * 64,
    )
    journal = activation.ActivationJournal(journal_root, binding)
    lock_fd = journal.acquire_execution_lock()
    os.close(lock_fd)
    journal.claim()
    journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
    receipt_prefix = journal_root / journal.receipt_temp_name
    receipt_prefix.write_bytes(b'{"partial":')
    receipt_prefix.chmod(0o600)
    transition_prefix = journal_root / journal.transition_name
    transition_prefix.write_bytes(b'{"schemaVersion":')
    transition_prefix.chmod(0o600)
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root,
    )

    observed = watchdog._scan_activation_journals()[binding.run_nonce]
    assert observed["state"] == "HOLD"
    assert observed["reasonCode"] == \
        "INTERRUPTED_JOURNAL_TRANSITION_NO_RETRY"
    assert not receipt_prefix.exists()
    assert not transition_prefix.exists()


@pytest.mark.parametrize("state", ["RUNNING", "HOLD"])
def test_journal_scan_accepts_bound_residual_receipt_after_crash(
    monkeypatch, tmp_path, state,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_root = tmp_path / "activation"
    activation_root.mkdir(mode=0o700)
    nonce = "recovery_nonce_1234"
    _write_outer_journal(activation_root, nonce, state)
    receipt = _execution_receipt(nonce)
    receipt_path = activation_root / "journal" / f"{nonce}.receipt.json"
    receipt_path.write_bytes(activation._canonical(receipt) + b"\n")
    receipt_path.chmod(0o600)
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root
    )
    observed = watchdog._scan_activation_journals()[nonce]
    assert observed["state"] == state
    assert observed["residualReceiptSha256"] == hashlib.sha256(
        activation._canonical(receipt)
    ).hexdigest()


def test_journal_scan_rejects_receipt_after_hold_is_already_reconciled(
    monkeypatch, tmp_path,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_root = tmp_path / "activation"
    activation_root.mkdir(mode=0o700)
    nonce = "recovery_nonce_1234"
    _write_outer_journal(activation_root, nonce, "RECONCILED_HOLD")
    receipt_path = activation_root / "journal" / f"{nonce}.receipt.json"
    receipt_path.write_bytes(
        activation._canonical(_execution_receipt(nonce)) + b"\n"
    )
    receipt_path.chmod(0o600)
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root,
    )
    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_ACTIVATION_RESIDUAL_RECEIPT_INVALID",
    ):
        watchdog._scan_activation_journals()


def test_no_request_or_state_is_ready_without_creating_or_using_clock(
    monkeypatch, idle_recovery_discovery,
):
    calls = []
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **kwargs: calls.append(kwargs) or _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {})
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: None)
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == "DORMANT_VERIFIED_NO_RECOVERY_REQUEST"
    assert result["recoveryStatus"] == "NO_ACTION"
    assert len(calls) == 1


def test_orchestrator_holds_idle_interlock_during_exact_scan(monkeypatch):
    held = []

    @contextlib.contextmanager
    def idle_interlock(*_args, **_kwargs):
        held.append(True)
        try:
            yield False
        finally:
            held.pop()

    def scan():
        assert held == [True]
        return {}

    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(
        watchdog, "_activation_interlock_status", idle_interlock,
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", scan)
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: None)
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert held == []
    assert result["status"] == "DORMANT_VERIFIED_NO_RECOVERY_REQUEST"


def test_live_activation_and_busy_discovery_defer_without_package_scan(
    monkeypatch, idle_recovery_discovery,
):
    live = {
        **_orchestrator_dormant_result(),
        "status": "ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED",
        "activationInterlockHeld": True,
        "roleLoginState": "ENABLED", "credentialState": "PRESENT",
    }
    monkeypatch.setattr(watchdog, "watchdog_once", lambda **_kwargs: live)
    monkeypatch.setattr(
        watchdog, "_scan_activation_journals",
        lambda: pytest.fail("live activation must defer before discovery"),
    )
    monkeypatch.setattr(
        watchdog, "_load_recovery_package",
        lambda: pytest.fail("live activation must defer before package scan"),
    )
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == "WATCHDOG_RECOVERY_DEFERRED_LIVE_ACTIVATION"

    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(
        watchdog, "_scan_activation_journals",
        lambda: (_ for _ in ()).throw(
            watchdog.WatchdogError(
                "WATCHDOG_ACTIVATION_DISCOVERY_DEFERRED"
            )
        ),
    )
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["recoveryStatus"] == "DEFERRED_LIVE_ACTIVATION"


@pytest.mark.parametrize("journal_state", [None, "RECONCILED_HOLD"])
def test_no_action_recovery_skips_trusted_time_and_full_verification(
    monkeypatch, idle_recovery_discovery, journal_state,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    nonce = "recovery_nonce_1234"
    package = {
        "stagedWithoutRequest": False,
        "request": {
            "runNonce": nonce, "expectedKeyringSha256": "1" * 64,
            "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        },
        "keyring.json": b"unneeded", "decision.json": b"unneeded",
        "activation-plan.json": b"unneeded",
    }
    journal = {} if journal_state is None else {nonce: {
        "state": journal_state, "planSha256": "2" * 64,
        "decisionSha256": "3" * 64,
    }}
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: journal)
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch",
        lambda: pytest.fail("no-action branch must not require trusted time"),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery",
        lambda **_kwargs: pytest.fail("no-action branch must not verify package"),
    )
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["actionAllowed"] is False
    assert result["recoveryStatus"] == (
        "EXACT_JOURNAL_ABSENT_NO_ACTION"
        if journal_state is None else journal_state
    )


def test_claimed_prelaunch_remains_pending_until_signed_expiry(
    monkeypatch, idle_recovery_discovery,
):
    activation, recovery, package = _cleanup_recovery_fixture(
        expires_at_epoch=1_900_000_000,
    )
    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
    )
    passes = []
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: passes.append(True) or _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        recovery.run_nonce: {
            "state": "CLAIMED", "planSha256": recovery.plan_sha256,
            "decisionSha256": recovery.decision_sha256,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch",
        lambda: (1_800_000_000, {}),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )
    monkeypatch.setattr(
        activation_executor, "BoundRecoveryExecutor",
        lambda **_kwargs: pytest.fail("pending claim must not construct cleanup"),
    )
    monkeypatch.setattr(
        activation, "reconcile_incomplete",
        lambda **_kwargs: pytest.fail("pending claim must not reconcile"),
    )

    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )

    assert result["status"] == "DORMANT_VERIFIED_LAUNCH_PENDING"
    assert result["recoveryStatus"] == "CLAIMED_PENDING_SIGNED_EXPIRY"
    assert len(passes) == 2


def test_claimed_state_without_final_launch_is_nonmutating_commit_prefix(
    monkeypatch, idle_recovery_discovery,
):
    activation, recovery, package = _cleanup_recovery_fixture(
        expires_at_epoch=1_700_000_000,
    )
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: _orchestrator_dormant_result(),
    )
    journal = {
        "state": "CLAIMED", "planSha256": recovery.plan_sha256,
        "decisionSha256": recovery.decision_sha256,
    }
    monkeypatch.setattr(
        watchdog, "_scan_activation_journals",
        lambda: {recovery.run_nonce: journal},
    )
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        watchdog, "_runtime_commit_markers",
        lambda: {"rollbackIntent": None, "launchRequest": None},
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery",
        lambda **_kwargs: pytest.fail("commit prefix must not be terminalized"),
    )

    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == "DORMANT_VERIFIED_COMMIT_PREFIX_PENDING"
    assert result["recoveryStatus"] == \
        "STATE_CLAIMED_LAUNCH_NOT_PUBLISHED_NO_ACTION"
    assert journal["state"] == "CLAIMED"


def test_durable_rollback_intent_defers_watchdog_without_scanning_state(
    monkeypatch, idle_recovery_discovery,
):
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: _orchestrator_dormant_result(),
    )
    rollback = {
        "runNonce": "recovery_nonce_1234",
        "planSha256": "2" * 64,
        "decisionSha256": "3" * 64,
    }
    monkeypatch.setattr(
        watchdog, "_runtime_commit_markers",
        lambda: {"rollbackIntent": rollback, "launchRequest": None},
    )
    monkeypatch.setattr(
        watchdog, "_scan_activation_journals",
        lambda: pytest.fail("rollback prefix state must not be scanned"),
    )
    monkeypatch.setattr(
        watchdog, "_load_recovery_package",
        lambda: pytest.fail("rollback prefix package must not be consumed"),
    )

    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == \
        "DORMANT_VERIFIED_RUNTIME_ROLLBACK_PENDING"
    assert result["recoveryStatus"] == \
        "COMMIT_ROLLBACK_PENDING_NO_ACTION"


def test_expired_claimed_prelaunch_is_cleanup_only_once(
    monkeypatch, idle_recovery_discovery,
):
    activation, recovery, package = _cleanup_recovery_fixture(
        expires_at_epoch=1_700_000_000,
    )
    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
    )
    monkeypatch.setattr(
        watchdog, "watchdog_once", lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        recovery.run_nonce: {
            "state": "CLAIMED", "planSha256": recovery.plan_sha256,
            "decisionSha256": recovery.decision_sha256,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch",
        lambda: (1_800_000_000, {}),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )

    class RecoveryExecutor:
        @staticmethod
        def attest_dormant():
            return {
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "customerRowsRead": False,
            }

    monkeypatch.setattr(
        activation_executor, "BoundRecoveryExecutor",
        lambda **_kwargs: RecoveryExecutor(),
    )
    observed = []

    def reconcile(**kwargs):
        observed.append(kwargs["automatic_no_retry"])
        return {
            "status": "ACTIVATION_RECONCILED_HOLD",
            "runNonce": recovery.run_nonce,
            "automaticRetryAllowed": False, "actionAllowed": False,
        }

    monkeypatch.setattr(activation, "reconcile_incomplete", reconcile)
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == "DORMANT_VERIFIED_RECOVERY_RECONCILED_HOLD"
    assert observed == [True]


def test_watchdog_recovers_bound_residual_receipt_to_closed(
    monkeypatch, idle_recovery_discovery,
):
    activation, recovery, package = _cleanup_recovery_fixture(
        expires_at_epoch=1_900_000_000,
    )
    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
    )
    receipt_sha = "4" * 64
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        recovery.run_nonce: {
            "state": "RUNNING", "planSha256": recovery.plan_sha256,
            "decisionSha256": recovery.decision_sha256,
            "residualReceiptSha256": receipt_sha,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch",
        lambda: (1_800_000_000, {}),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )

    class RecoveryExecutor:
        production_contact = True

        @staticmethod
        def attest_dormant():
            return {
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "customerRowsRead": False,
            }

    monkeypatch.setattr(
        activation_executor, "BoundRecoveryExecutor",
        lambda **_kwargs: RecoveryExecutor(),
    )
    observed = []

    def recover_close(**kwargs):
        observed.append(kwargs["authorization"].run_nonce)
        return {
            "status": "ACTIVATION_COMPLETED_CLOSE_RECOVERED",
            "runNonce": recovery.run_nonce,
            "receiptSha256": receipt_sha, "journalState": "CLOSED",
            "automaticRetryAllowed": False, "actionAllowed": False,
        }

    monkeypatch.setattr(activation, "recover_completed_close", recover_close)
    monkeypatch.setattr(
        activation, "reconcile_incomplete",
        lambda **_kwargs: pytest.fail("generic reconciliation was used"),
    )
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == "DORMANT_VERIFIED_RECOVERY_COMPLETED_CLOSED"
    assert result["recoveryStatus"] == \
        "ACTIVATION_COMPLETED_CLOSE_RECOVERED"
    assert observed == [recovery.run_nonce]


def test_manual_hold_leaves_residual_receipt_for_automatic_close(
    monkeypatch, idle_recovery_discovery,
):
    activation, recovery, package = _cleanup_recovery_fixture(
        expires_at_epoch=1_700_000_000,
    )
    receipt_sha = "4" * 64
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        recovery.run_nonce: {
            "state": "HOLD", "planSha256": recovery.plan_sha256,
            "decisionSha256": recovery.decision_sha256,
            "residualReceiptSha256": receipt_sha,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation, "recover_completed_close",
        lambda **_kwargs: pytest.fail("manual path consumed residual receipt"),
    )
    monkeypatch.setattr(
        activation, "reconcile_incomplete",
        lambda **_kwargs: pytest.fail("manual path reconciled residual receipt"),
    )

    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_MANUAL_HOLD_RESIDUAL_RECEIPT_AUTOMATIC_REQUIRED",
    ):
        watchdog.watchdog_with_cleanup_recovery(
            container_name=rebind.PRODUCTION_CONTAINER,
            expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
            expected_volume_name=rebind.PRODUCTION_VOLUME,
            expected_server_version_num=170011,
            expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
            manual_hold=True, confirm_run_nonce=recovery.run_nonce,
            confirm_decision_sha256=recovery.decision_sha256,
        )


def test_hold_requires_exact_post_expiry_manual_reconciliation(
    monkeypatch, idle_recovery_discovery,
):
    activation, recovery, package = _cleanup_recovery_fixture(
        expires_at_epoch=1_700_000_000,
    )
    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
    )
    monkeypatch.setattr(
        watchdog, "watchdog_once", lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        recovery.run_nonce: {
            "state": "HOLD", "planSha256": recovery.plan_sha256,
            "decisionSha256": recovery.decision_sha256,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)

    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_RECOVERY_HOLD_MANUAL_REQUIRED",
    ):
        watchdog.watchdog_with_cleanup_recovery(
            container_name=rebind.PRODUCTION_CONTAINER,
            expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
            expected_volume_name=rebind.PRODUCTION_VOLUME,
            expected_server_version_num=170011,
            expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        )

    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch",
        lambda: (1_800_000_000, {}),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )

    class RecoveryExecutor:
        @staticmethod
        def attest_dormant():
            return {
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "customerRowsRead": False,
            }

    monkeypatch.setattr(
        activation_executor, "BoundRecoveryExecutor",
        lambda **_kwargs: RecoveryExecutor(),
    )
    observed = []

    def reconcile(**kwargs):
        observed.append(kwargs["automatic_no_retry"])
        return {
            "status": "ACTIVATION_RECONCILED_HOLD",
            "runNonce": recovery.run_nonce,
            "automaticRetryAllowed": False, "actionAllowed": False,
        }

    monkeypatch.setattr(activation, "reconcile_incomplete", reconcile)
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        manual_hold=True, confirm_run_nonce=recovery.run_nonce,
        confirm_decision_sha256=recovery.decision_sha256,
    )
    assert result["status"] == "DORMANT_VERIFIED_MANUAL_HOLD_RECONCILED"
    assert observed == [False]


def test_manual_hold_rejects_mismatch_and_unexpired_decision(
    monkeypatch, idle_recovery_discovery,
):
    activation, recovery, package = _cleanup_recovery_fixture(
        expires_at_epoch=1_900_000_000,
    )
    monkeypatch.setattr(
        watchdog, "watchdog_once", lambda **_kwargs: _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        recovery.run_nonce: {
            "state": "HOLD", "planSha256": recovery.plan_sha256,
            "decisionSha256": recovery.decision_sha256,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_MANUAL_HOLD_CONFIRMATION_MISMATCH",
    ):
        watchdog.watchdog_with_cleanup_recovery(
            container_name=rebind.PRODUCTION_CONTAINER,
            expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
            expected_volume_name=rebind.PRODUCTION_VOLUME,
            expected_server_version_num=170011,
            expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
            manual_hold=True, confirm_run_nonce=recovery.run_nonce,
            confirm_decision_sha256="9" * 64,
        )
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch",
        lambda: (1_800_000_000, {}),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )
    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_MANUAL_HOLD_DECISION_NOT_EXPIRED",
    ):
        watchdog.watchdog_with_cleanup_recovery(
            container_name=rebind.PRODUCTION_CONTAINER,
            expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
            expected_volume_name=rebind.PRODUCTION_VOLUME,
            expected_server_version_num=170011,
            expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
            manual_hold=True, confirm_run_nonce=recovery.run_nonce,
            confirm_decision_sha256=recovery.decision_sha256,
        )


def test_post_pass_defers_a_new_live_activation(
    monkeypatch, idle_recovery_discovery,
):
    live = {
        **_orchestrator_dormant_result(),
        "status": "ACTIVE_LEASE_ACTIVATION_INTERLOCK_SUPERVISED",
        "activationInterlockHeld": True,
        "roleLoginState": "ENABLED", "credentialState": "PRESENT",
    }
    passes = iter([_orchestrator_dormant_result(), live])
    monkeypatch.setattr(watchdog, "watchdog_once", lambda **_kwargs: next(passes))
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {})
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: {
        "stagedWithoutRequest": False,
        "request": {
            "runNonce": "recovery_nonce_1234",
            "expectedKeyringSha256": "1" * 64,
            "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        },
        "keyring.json": b"unneeded", "decision.json": b"unneeded",
        "activation-plan.json": b"unneeded",
    })
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == \
        "WATCHDOG_RECOVERY_POST_DEFERRED_LIVE_ACTIVATION"
    assert result["actionAllowed"] is False


def test_recovery_failure_runs_post_pass_and_preserves_exact_reason(
    monkeypatch, idle_recovery_discovery,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
    )
    nonce = "recovery_nonce_1234"
    recovery = activation.VerifiedRecovery(
        environment="PRODUCTION", run_nonce=nonce,
        plan_sha256="2" * 64, decision_sha256="3" * 64,
        keyring_sha256="1" * 64,
        derived_execution_plan_sha256="4" * 64,
        decision_expires_at_epoch=1_900_000_000,
        target={
            "containerName": rebind.PRODUCTION_CONTAINER,
            "containerId": CONTAINER["containerId"],
            "imageId": rebind.POSTGRES_17_11_IMAGE_ID,
            "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        },
        limits=dict(activation.LIMITS),
        _recovery_seal=activation._VERIFIED_RECOVERY_SEAL,
    )
    package = {
        "stagedWithoutRequest": False,
        "request": {
            "runNonce": nonce, "expectedKeyringSha256": "1" * 64,
            "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        },
        "keyring.json": b"keyring", "decision.json": b"decision",
        "activation-plan.json": b"plan",
    }
    passes = []
    monkeypatch.setattr(
        watchdog, "watchdog_once",
        lambda **_kwargs: passes.append(True) or _orchestrator_dormant_result(),
    )
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        nonce: {
            "state": "RUNNING", "planSha256": "2" * 64,
            "decisionSha256": "3" * 64,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch", lambda: (1_800_000_000, {})
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )

    class RecoveryExecutor:
        def attest_dormant(self):
            return {
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "customerRowsRead": False,
            }

    monkeypatch.setattr(
        activation_executor, "BoundRecoveryExecutor",
        lambda **_kwargs: RecoveryExecutor(),
    )
    monkeypatch.setattr(
        activation, "reconcile_incomplete",
        lambda **_kwargs: (_ for _ in ()).throw(
            activation.ActivationError("SYNTHETIC_RECOVERY_FAILURE")
        ),
    )
    with pytest.raises(
        watchdog.WatchdogError,
        match="WATCHDOG_RECOVERY_SYNTHETIC_RECOVERY_FAILURE",
    ):
        watchdog.watchdog_with_cleanup_recovery(
            container_name=rebind.PRODUCTION_CONTAINER,
            expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
            expected_volume_name=rebind.PRODUCTION_VOLUME,
            expected_server_version_num=170011,
            expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        )
    assert len(passes) == 2


def test_recovery_interlock_race_defers_only_after_live_post_attestation(
    monkeypatch, idle_recovery_discovery,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
    )
    nonce = "recovery_nonce_1234"
    recovery = activation.VerifiedRecovery(
        environment="PRODUCTION", run_nonce=nonce,
        plan_sha256="2" * 64, decision_sha256="3" * 64,
        keyring_sha256="1" * 64,
        derived_execution_plan_sha256="4" * 64,
        decision_expires_at_epoch=1_900_000_000,
        target={
            "containerName": rebind.PRODUCTION_CONTAINER,
            "containerId": CONTAINER["containerId"],
            "imageId": rebind.POSTGRES_17_11_IMAGE_ID,
            "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        },
        limits=dict(activation.LIMITS),
        _recovery_seal=activation._VERIFIED_RECOVERY_SEAL,
    )
    live = {
        **_orchestrator_dormant_result(),
        "status": "DORMANT_ACTIVATION_CLEANUP_DEFERRED",
        "activationInterlockHeld": True,
    }
    passes = iter([_orchestrator_dormant_result(), live])
    monkeypatch.setattr(watchdog, "watchdog_once", lambda **_kwargs: next(passes))
    monkeypatch.setattr(watchdog, "_scan_activation_journals", lambda: {
        nonce: {
            "state": "RUNNING", "planSha256": "2" * 64,
            "decisionSha256": "3" * 64,
        }
    })
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: {
        "stagedWithoutRequest": False,
        "request": {
            "runNonce": nonce, "expectedKeyringSha256": "1" * 64,
            "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        },
        "keyring.json": b"keyring", "decision.json": b"decision",
        "activation-plan.json": b"plan",
    })
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch", lambda: (1_800_000_000, {})
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )

    class RecoveryExecutor:
        def attest_dormant(self):
            return {
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "customerRowsRead": False,
            }

    monkeypatch.setattr(
        activation_executor, "BoundRecoveryExecutor",
        lambda **_kwargs: RecoveryExecutor(),
    )
    monkeypatch.setattr(
        activation, "reconcile_incomplete",
        lambda **_kwargs: (_ for _ in ()).throw(
            activation.ActivationError("ACTIVATION_INTERLOCK_HELD")
        ),
    )
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == "WATCHDOG_RECOVERY_DEFERRED_LIVE_ACTIVATION"
    assert result["recoveryStatus"] == "DEFERRED_LIVE_ACTIVATION"


def test_exact_dormant_requires_customer_rows_read_false():
    result = _orchestrator_dormant_result()
    result["customerRowsRead"] = True
    with pytest.raises(watchdog.WatchdogError, match="DORMANT_REQUIRED"):
        watchdog._require_exact_dormant(result, phase="SYNTHETIC")


def test_incomplete_journal_without_request_fails_before_cleanup(
    monkeypatch, idle_recovery_discovery,
):
    monkeypatch.setattr(
        watchdog, "watchdog_once", lambda **_kwargs: _orchestrator_dormant_result()
    )
    monkeypatch.setattr(
        watchdog, "_scan_activation_journals",
        lambda: {"recovery_nonce_1234": {"state": "RUNNING"}},
    )
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: None)
    with pytest.raises(
        watchdog.WatchdogError,
        match="INCOMPLETE_ACTIVATION_RECOVERY_REQUEST_ABSENT",
    ):
        watchdog.watchdog_with_cleanup_recovery(
            container_name=rebind.PRODUCTION_CONTAINER,
            expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
            expected_volume_name=rebind.PRODUCTION_VOLUME,
            expected_server_version_num=170011,
            expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
        )


def test_orchestrator_uses_recovery_only_between_released_dormant_passes(
    monkeypatch, idle_recovery_discovery,
):
    activation = importlib.import_module("b64_064a_activation_entrypoint")
    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
    )
    nonce = "recovery_nonce_1234"
    target = {
        "containerName": rebind.PRODUCTION_CONTAINER,
        "containerId": CONTAINER["containerId"],
        "imageId": rebind.POSTGRES_17_11_IMAGE_ID,
        "systemIdentifier": rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    }
    recovery = activation.VerifiedRecovery(
        environment="PRODUCTION", run_nonce=nonce,
        plan_sha256="2" * 64, decision_sha256="3" * 64,
        keyring_sha256="1" * 64,
        derived_execution_plan_sha256="4" * 64,
        decision_expires_at_epoch=1_700_000_000, target=target,
        limits=dict(activation.LIMITS),
        _recovery_seal=activation._VERIFIED_RECOVERY_SEAL,
    )
    package = {
        "stagedWithoutRequest": False,
        "request": {
            "runNonce": nonce, "expectedKeyringSha256": "1" * 64,
            "planSha256": "2" * 64, "decisionSha256": "3" * 64,
        },
        "keyring.json": b"keyring", "decision.json": b"decision",
        "activation-plan.json": b"plan",
    }
    sequence = []

    def dormant(**_kwargs):
        sequence.append("watchdog")
        return _orchestrator_dormant_result()

    class RecoveryExecutor:
        def attest_dormant(self):
            sequence.append("attest")
            return {
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "customerRowsRead": False,
            }

    monkeypatch.setattr(watchdog, "watchdog_once", dormant)
    monkeypatch.setattr(
        watchdog, "_scan_activation_journals",
        lambda: {nonce: {
            "state": "RUNNING", "planSha256": "2" * 64,
            "decisionSha256": "3" * 64,
        }},
    )
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch", lambda: (1_800_000_000, {})
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery",
        lambda **_kwargs: sequence.append("verify") or recovery,
    )
    monkeypatch.setattr(
        activation_executor, "BoundRecoveryExecutor",
        lambda **_kwargs: RecoveryExecutor(),
    )

    def reconcile(**kwargs):
        sequence.append("reconcile")
        assert kwargs["authorization"] is recovery
        assert kwargs["automatic_no_retry"] is True
        assert kwargs["executor"].attest_dormant()["activeSessions"] == 0
        return {
            "status": "ACTIVATION_RECONCILED_HOLD", "runNonce": nonce,
            "automaticRetryAllowed": False, "actionAllowed": False,
        }

    monkeypatch.setattr(activation, "reconcile_incomplete", reconcile)
    monkeypatch.setattr(
        activation, "run_once",
        lambda **_kwargs: pytest.fail("activation execute path is forbidden"),
    )
    monkeypatch.setattr(
        activation_executor.runtime, "issue_credential_lease",
        lambda **_kwargs: pytest.fail("lease path is forbidden"),
    )
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=rebind.PRODUCTION_CONTAINER,
        expected_image_id=rebind.POSTGRES_17_11_IMAGE_ID,
        expected_volume_name=rebind.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=rebind.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert result["status"] == "DORMANT_VERIFIED_RECOVERY_RECONCILED_HOLD"
    assert sequence == [
        "watchdog", "verify", "reconcile", "attest", "watchdog"
    ]


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
    assert "-/var/lib/obsidian-exchange/b64-064a-activation" not in unit
    assert "--require-dormant --cleanup-recovery" in timer_service
    assert "ReadWritePaths=/run/lock " in timer_service
    assert "-/var/lib/obsidian-exchange/b64-064a-activation" in timer_service
    assert "SuccessExitStatus=" not in timer_service
    assert "EnvironmentFile=" not in timer_service
    assert "LoadCredential=" not in timer_service
    assert "RestrictAddressFamilies=AF_UNIX" in timer_service
