import hashlib
import importlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))
launcher = importlib.import_module("b64_064a_activation_launcher")
activation = importlib.import_module("b64_064a_activation_entrypoint")
watchdog = importlib.import_module("b64_snapshot_reader_watchdog")
UNIT = ROOT / "deploy/systemd/obsidian-b64-064a-activation.service"


def _request(**overrides):
    value = {
        "schemaVersion": launcher.LAUNCH_REQUEST_SCHEMA,
        "route": launcher.ROUTE,
        "environment": "PRODUCTION",
        "runNonce": "production_nonce_1234",
        "action": launcher.LAUNCH_ACTION,
        "operatorCommitOnly": True,
        "grantsAuthority": False,
        "automaticRetryAllowed": False,
        "expectedKeyringSha256": "1" * 64,
        "planSha256": "2" * 64,
        "decisionSha256": "3" * 64,
        "recoveryManifestSha256": "4" * 64,
    }
    value.update(overrides)
    return value


def _result():
    return {
        "schemaVersion": "b64-064a-production-activation-result.v1",
        "route": launcher.ROUTE,
        "status": "ACTIVATION_COMPLETED_DORMANT_VERIFIED",
        "environment": "PRODUCTION",
        "runNonce": "production_nonce_1234",
        "planSha256": "2" * 64,
        "decisionSha256": "3" * 64,
        "receiptSha256": "5" * 64,
        "journalState": "CLOSED",
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }


def test_signed_artifact_closure_includes_exact_launcher_bytes():
    assert activation.ARTIFACT_PATHS["activationLauncher"] == \
        POSTGRES / "b64_064a_activation_launcher.py"
    digest = hashlib.sha256(
        activation.ARTIFACT_PATHS["activationLauncher"].read_bytes()
    ).hexdigest()
    assert len(digest) == 64
    assert "activationLauncher" in activation.ARTIFACT_KEYS


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"action": "VERIFY_ONLY"}, "LAUNCH_REQUEST_INVALID"),
        ({"operatorCommitOnly": False}, "LAUNCH_REQUEST_INVALID"),
        ({"grantsAuthority": True}, "LAUNCH_REQUEST_INVALID"),
        ({"automaticRetryAllowed": True}, "LAUNCH_REQUEST_INVALID"),
        ({"planSha256": "x" * 64}, "LAUNCH_REQUEST_DIGEST_INVALID"),
    ],
)
def test_launch_request_is_exact_non_authorizing_commit(change, reason):
    with pytest.raises(launcher.LauncherError, match=reason):
        launcher._validate_launch_request(_request(**change))


def test_committed_package_requires_launch_and_recovery_exact_binding(
    monkeypatch,
):
    keyring = b"keyring"
    plan = b"plan"
    decision = b"decision"
    request = _request(
        expectedKeyringSha256="a" * 64,
        planSha256="b" * 64,
        decisionSha256="c" * 64,
    )
    recovery = {
        "runNonce": request["runNonce"],
        "expectedKeyringSha256": request["expectedKeyringSha256"],
        "planSha256": request["planSha256"],
        "decisionSha256": request["decisionSha256"],
        "manifestSha256": request["recoveryManifestSha256"],
    }
    package = {
        "stagedWithoutRequest": False, "request": recovery,
        "keyring.json": keyring, "activation-plan.json": plan,
        "decision.json": decision,
    }
    verified = SimpleNamespace(
        run_nonce=request["runNonce"],
        keyring_sha256=request["expectedKeyringSha256"],
        plan_sha256=request["planSha256"],
        decision_sha256=request["decisionSha256"],
    )
    monkeypatch.setattr(launcher, "_load_launch_request", lambda: request)
    monkeypatch.setattr(watchdog, "_load_recovery_package", lambda: package)
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch", lambda: (1_800_000_000, {})
    )
    monkeypatch.setattr(
        activation, "verify_activation_decision", lambda **_kwargs: verified
    )
    observed, authorization = launcher._load_committed_package()
    assert observed is package
    assert authorization is verified

    monkeypatch.setattr(
        launcher, "_load_launch_request",
        lambda: {**request, "planSha256": "9" * 64},
    )
    with pytest.raises(
        launcher.LauncherError, match="LAUNCH_RECOVERY_BINDING_MISMATCH"
    ):
        launcher._load_committed_package()


def test_unsafe_or_missing_package_fails_before_production_contact(monkeypatch):
    monkeypatch.setattr(launcher, "_reject_ambient_authority", lambda: None)
    monkeypatch.setattr(
        launcher, "_load_committed_package",
        lambda: (_ for _ in ()).throw(
            launcher.LauncherError("LAUNCH_RECOVERY_PACKAGE_MISSING")
        ),
    )
    monkeypatch.setattr(
        launcher.activation_executor, "_inspect_container",
        lambda *_args, **_kwargs: pytest.fail("production contact occurred"),
    )
    with pytest.raises(
        launcher.LauncherError, match="LAUNCH_RECOVERY_PACKAGE_MISSING"
    ):
        launcher._execute_production_once()


def test_observation_secret_moves_only_through_sealed_fd(tmp_path):
    path = tmp_path / "observation-env"
    path.write_bytes(
        b"EXCHANGE_DB_CONNECTION=pgsql\n"
        b"EXCHANGE_DATABASE_URL=postgresql://obsidian_readonly:"
        + b"s" * 64
        + b"@127.0.0.1:5432/obsidian_exchange\n"
        b"EXCHANGE_DB_SSLMODE=disable\n"
    )
    path.chmod(0o400)
    fd, observation_dsn, admin_dsn = launcher._production_connections(
        container_pid=os.getpid(), credential_path=path,
    )
    try:
        assert "s" * 64 not in observation_dsn
        assert "s" * 64 not in admin_dsn
        assert f"passfile=/proc/self/fd/{fd}" in observation_dsn
        assert "user=obsidian_readonly" in observation_dsn
        assert f"host=/proc/{os.getpid()}/root/var/run/postgresql" \
            in admin_dsn
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 4096).endswith(b":" + b"s" * 64 + b"\n")
    finally:
        os.close(fd)


def test_ambient_libpq_or_arguments_are_rejected(monkeypatch):
    monkeypatch.setattr(sys, "argv", [sys.argv[0]])
    monkeypatch.setenv("PGSERVICE", "forbidden")
    with pytest.raises(
        launcher.LauncherError,
        match="LAUNCHER_AMBIENT_LIBPQ_ENVIRONMENT_FORBIDDEN",
    ):
        launcher._reject_ambient_authority()
    monkeypatch.delenv("PGSERVICE")
    monkeypatch.setattr(sys, "argv", [sys.argv[0], "--retry"])
    with pytest.raises(
        launcher.LauncherError, match="LAUNCHER_ARGUMENTS_FORBIDDEN"
    ):
        launcher._reject_ambient_authority()


def test_production_wiring_uses_verified_target_and_one_run_once(monkeypatch):
    request = _request()
    verified = SimpleNamespace(
        run_nonce=request["runNonce"], keyring_sha256="1" * 64,
        target={"containerId": "a" * 64},
    )
    package = {
        "keyring.json": b"keyring", "decision.json": b"decision",
        "activation-plan.json": b"plan",
    }
    monkeypatch.setattr(launcher, "_reject_ambient_authority", lambda: None)
    monkeypatch.setattr(
        launcher, "_load_committed_package", lambda: (package, verified)
    )
    monkeypatch.setattr(
        launcher.activation_executor, "_inspect_container", lambda _name: {
            "Id": "a" * 64, "Image": activation.PRODUCTION_IMAGE_ID,
            "State": {"Running": True, "Pid": 12345},
        },
    )
    monkeypatch.setattr(
        activation, "_require_empty_production_activation_state", lambda: None,
    )
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    monkeypatch.setattr(
        launcher, "_production_connections",
        lambda **_kwargs: (read_fd, "observation", "admin"),
    )

    class Dormant:
        def __init__(self, **kwargs):
            assert kwargs["container_id"] == "a" * 64

        @staticmethod
        def attest_dormant():
            return {}

    class Executor:
        def __init__(self, **kwargs):
            assert kwargs["production_contact"] is True
            assert kwargs["observation_dsn"] == "observation"

    monkeypatch.setattr(
        launcher.activation_executor, "BoundRecoveryExecutor", Dormant
    )
    monkeypatch.setattr(
        launcher.activation_executor, "BoundActivationExecutor", Executor
    )
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch", lambda: (1_800_000_000, {})
    )
    calls = []
    monkeypatch.setattr(
        activation, "run_once", lambda **kwargs: calls.append(kwargs) or _result()
    )
    assert launcher._execute_production_once()["journalState"] == "CLOSED"
    assert len(calls) == 1
    assert calls[0]["expected_environment"] == "PRODUCTION"
    assert calls[0]["journal_root"] == activation.PRODUCTION_JOURNAL_ROOT


def test_old_activation_state_blocks_before_secret_or_executor(monkeypatch):
    verified = SimpleNamespace(
        run_nonce="fresh_nonce_12345", keyring_sha256="1" * 64,
        target={"containerId": "a" * 64},
    )
    monkeypatch.setattr(launcher, "_reject_ambient_authority", lambda: None)
    monkeypatch.setattr(
        launcher, "_load_committed_package",
        lambda: ({"unused": b"unused"}, verified),
    )
    monkeypatch.setattr(
        launcher.activation_executor, "_inspect_container", lambda _name: {
            "Id": "a" * 64, "Image": activation.PRODUCTION_IMAGE_ID,
            "State": {"Running": True, "Pid": 12345},
        },
    )
    monkeypatch.setattr(
        activation, "_require_empty_production_activation_state",
        lambda: (_ for _ in ()).throw(
            activation.ActivationError(
                "PRODUCTION_ACTIVATION_STATE_NOT_EMPTY"
            )
        ),
    )
    monkeypatch.setattr(
        launcher, "_production_connections",
        lambda **_kwargs: pytest.fail("observation credential was opened"),
    )
    monkeypatch.setattr(
        launcher.activation_executor, "BoundActivationExecutor",
        lambda **_kwargs: pytest.fail("executor was constructed"),
    )
    monkeypatch.setattr(
        activation, "run_once",
        lambda **_kwargs: pytest.fail("activation boundary was entered"),
    )
    with pytest.raises(
        activation.ActivationError,
        match="PRODUCTION_ACTIVATION_STATE_NOT_EMPTY",
    ):
        launcher._execute_production_once()


def test_supervisor_forks_exactly_once_and_returns_closed_result(tmp_path):
    count = tmp_path / "count"

    def worker():
        count.write_text("one", encoding="ascii")
        return _result()

    code, receipt = launcher.supervise_once(worker, wall_seconds=1.0)
    assert code == 0
    assert receipt["status"] == "ACTIVATION_COMPLETED_DORMANT_VERIFIED"
    assert receipt["activationResult"]["journalState"] == "CLOSED"
    assert receipt["processesRetried"] == 0
    assert count.read_text("ascii") == "one"


def test_hard_wall_kills_worker_process_group_without_retry(tmp_path):
    state = tmp_path / "state"

    def worker():
        descendant = subprocess.Popen(
            ["/bin/sleep", "30"], close_fds=True,
        )
        state.write_text(
            json.dumps({"worker": os.getpid(), "descendant": descendant.pid}),
            encoding="ascii",
        )
        while True:
            time.sleep(1)

    started = time.monotonic()
    code, receipt = launcher.supervise_once(worker, wall_seconds=0.2)
    elapsed = time.monotonic() - started
    assert code == 3
    assert receipt["reason"] == \
        "LAUNCHER_HARD_WALL_TIMEOUT_PROCESS_GROUP_TERMINATED"
    assert receipt["processesRetried"] == 0
    assert elapsed < 6
    identities = json.loads(state.read_text("ascii"))
    for pid in identities.values():
        deadline = time.monotonic() + 2
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            if time.monotonic() >= deadline:
                pytest.fail(f"process {pid} survived launcher hard wall")
            time.sleep(0.02)


def test_timeout_before_readiness_kills_child_and_never_starts_worker(
    monkeypatch, tmp_path,
):
    called = tmp_path / "called"
    real_arm = launcher._arm_parent_death_signal

    def delayed_arm(parent_pid):
        time.sleep(0.2)
        real_arm(parent_pid)

    monkeypatch.setattr(launcher, "_arm_parent_death_signal", delayed_arm)

    def worker():
        called.write_text("unsafe", encoding="ascii")
        return _result()

    code, receipt = launcher.supervise_once(worker, wall_seconds=0.1)
    assert code == 3
    assert receipt["reason"] == \
        "LAUNCHER_HARD_WALL_TIMEOUT_PROCESS_GROUP_TERMINATED"
    assert not called.exists()


def test_child_failure_is_closed_and_never_retried():
    def worker():
        raise RuntimeError("sensitive detail")

    code, receipt = launcher.supervise_once(worker, wall_seconds=1.0)
    assert code == 3
    assert receipt["reason"] == "LAUNCHER_UNEXPECTED_FAILURE"
    assert receipt["processesRetried"] == 0
    assert "sensitive" not in json.dumps(receipt)


@pytest.mark.parametrize("interrupt", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_supervisor_signal_terminates_group_with_short_grace(
    tmp_path, interrupt,
):
    worker_state = tmp_path / "worker"
    outcome = tmp_path / "outcome"
    supervisor_pid = os.fork()
    if supervisor_pid == 0:
        def worker():
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            worker_state.write_text(str(os.getpid()), encoding="ascii")
            while True:
                time.sleep(1)

        code, receipt = launcher.supervise_once(worker, wall_seconds=8.0)
        outcome.write_text(
            json.dumps({"code": code, "receipt": receipt}),
            encoding="utf-8",
        )
        os._exit(0)
    try:
        ready_deadline = time.monotonic() + 2
        while not worker_state.exists():
            if time.monotonic() >= ready_deadline:
                pytest.fail("supervised worker did not start")
            time.sleep(0.02)
        started = time.monotonic()
        os.kill(supervisor_pid, interrupt)
        wait_deadline = started + launcher.TERMINATION_GRACE_SECONDS + 2
        while True:
            waited, status = os.waitpid(supervisor_pid, os.WNOHANG)
            if waited == supervisor_pid:
                assert os.WIFEXITED(status)
                break
            if time.monotonic() >= wait_deadline:
                os.kill(supervisor_pid, signal.SIGKILL)
                os.waitpid(supervisor_pid, 0)
                pytest.fail("launcher did not honor termination grace")
            time.sleep(0.02)
    finally:
        try:
            os.kill(supervisor_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    observed = json.loads(outcome.read_text("utf-8"))
    assert observed["code"] == 3
    assert observed["receipt"]["reason"] == \
        "LAUNCHER_SIGNAL_PROCESS_GROUP_TERMINATED"
    worker_pid = int(worker_state.read_text("ascii"))
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pid, 0)


def test_systemd_unit_is_manual_fixed_and_watchdog_preserving():
    unit = UNIT.read_text("utf-8")
    release = (
        "/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/"
        "34bc167ebf192103f588524b521713ab588245e3"
    )
    assert "IMPLEMENTATION_COMMIT" not in unit
    assert f"WorkingDirectory={release}" in unit
    assert f"ConditionPathExists={release}/deploy/postgres/" in unit
    assert f"ExecStart=/opt/obsidian-exchange/relay-venv/bin/python -E {release}/deploy/postgres/" in unit
    assert "Type=oneshot" in unit
    assert "Restart=no" in unit
    assert "TimeoutStartSec=190" in unit
    assert "TimeoutStopSec=5" in unit
    assert "KillMode=control-group" in unit
    assert "FinalKillSignal=SIGKILL" in unit
    assert "SendSIGKILL=yes" in unit
    assert "LoadCredential=observation-env:" in unit
    assert "EnvironmentFile=" not in unit
    assert "ExecStart=/opt/obsidian-exchange/relay-venv/bin/python -E " in unit
    assert "b64_064a_activation_launcher.py" in unit
    assert "--" not in next(
        line for line in unit.splitlines() if line.startswith("ExecStart=")
    )
    assert "[Install]" not in unit
    assert "Conflicts=obsidian-b64-snapshot-reader-watchdog" not in unit
    assert "PartOf=obsidian-b64-snapshot-reader-watchdog" not in unit
    assert "Requires=obsidian-b64-snapshot-reader-watchdog.timer" in unit
    assert "After=obsidian-postgres.service obsidian-b64-snapshot-reader-watchdog.timer" in unit
    assert "ConditionPathExists=/etc/obsidian-exchange/b64-064a" not in unit
    assert "ConditionPathIsDirectory=/var/lib/obsidian-exchange" not in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_INET" in unit
    assert "IPAddressDeny=any" in unit
    assert "IPAddressAllow=localhost" in unit
    assert launcher.CHILD_WALL_SECONDS == activation.LIMITS[
        "overallDeadlineSeconds"
    ]
    assert launcher.CHILD_WALL_SECONDS + 10 == 190
