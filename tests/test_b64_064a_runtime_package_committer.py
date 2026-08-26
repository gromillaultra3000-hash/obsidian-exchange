from __future__ import annotations

import contextlib
import importlib
import hashlib
import json
import os
import signal
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

committer = importlib.import_module("b64_064a_runtime_package_committer")
activation = importlib.import_module("b64_064a_activation_entrypoint")
launcher = importlib.import_module("b64_064a_activation_launcher")
watchdog = importlib.import_module("b64_snapshot_reader_watchdog")
archiver = importlib.import_module("b64_064a_terminal_evidence_archiver")


@pytest.fixture
def commit_state(tmp_path, monkeypatch):
    recovery = tmp_path / "etc"
    recovery.mkdir(mode=0o755)
    activation_parent = tmp_path / "var"
    activation_parent.mkdir(mode=0o755)
    activation_parent.chmod(0o3770)
    activation_root = activation_parent / "b64-064a-activation"
    lock = tmp_path / "commit.lock"
    release = tmp_path / ("a" * 40)
    release.mkdir(mode=0o755)

    monkeypatch.setattr(committer, "RECOVERY_PARENT", recovery)
    monkeypatch.setattr(committer, "ACTIVATION_ROOT", activation_root)
    monkeypatch.setattr(committer, "ACTIVATION_PARENT_MODE", 0o3770)
    monkeypatch.setattr(committer, "ACTIVATION_PARENT_GID", os.getgid())
    monkeypatch.setattr(committer, "LOCK_PATH", lock)
    monkeypatch.setattr(watchdog, "RECOVERY_PARENT", recovery)
    monkeypatch.setattr(
        watchdog, "PRODUCTION_ACTIVATION_ROOT", activation_root,
    )
    monkeypatch.setattr(
        activation, "PRODUCTION_ACTIVATION_ROOT", activation_root,
    )
    monkeypatch.setattr(
        activation, "PRODUCTION_JOURNAL_ROOT", activation_root / "journal",
    )
    monkeypatch.setattr(
        activation, "PRODUCTION_RESOURCE_JOURNAL_ROOT",
        activation_root / "resources",
    )
    monkeypatch.setattr(
        activation, "PRODUCTION_WORKSPACE_ROOT", activation_root / "workspace",
    )
    monkeypatch.setattr(
        activation, "PRODUCTION_PROXY_ROOT", activation_root / "proxy",
    )
    monkeypatch.setattr(
        activation, "PRODUCTION_INTERLOCK_PATH",
        tmp_path / "activation-interlock.lock",
    )
    monkeypatch.setattr(
        committer, "_verify_runtime_identity", lambda: release,
    )

    inputs = {
        "keyring.json": b'{"fixture":"keyring"}\n',
        "decision.json": b'{"fixture":"decision"}\n',
        "activation-plan.json": b'{"fixture":"plan"}\n',
    }
    target = {
        "containerName": activation.PRODUCTION_CONTAINER,
        "containerId": "b" * 64,
        "imageId": activation.PRODUCTION_IMAGE_ID,
        "systemIdentifier": activation.PRODUCTION_SYSTEM_IDENTIFIER,
    }
    verified = SimpleNamespace(
        run_nonce="production_nonce_1234",
        keyring_sha256="1" * 64,
        plan_sha256="2" * 64,
        decision_sha256="3" * 64,
        expires_at_epoch=1_800_000_600,
        target=target,
    )
    monkeypatch.setattr(
        committer, "_load_and_verify",
        lambda _release, **_kwargs: (inputs, verified),
    )
    monkeypatch.setattr(
        activation, "verify_activation_decision", lambda **_kwargs: verified,
    )
    monkeypatch.setattr(committer, "_trusted_now", lambda: 1_800_000_000)
    monkeypatch.setattr(
        committer, "_dormant_tuple", lambda _release: dict(target),
    )
    return {
        "recovery": recovery,
        "activationRoot": activation_root,
        "inputs": inputs,
        "verified": verified,
    }


def _final_paths(state):
    return (
        state["recovery"] / watchdog.RECOVERY_PACKAGE_NAME,
        state["recovery"] / watchdog.RECOVERY_REQUEST_NAME,
        state["recovery"] / launcher.LAUNCH_REQUEST_NAME,
        state["activationRoot"],
    )


def test_committer_is_in_signed_artifact_closure():
    assert activation.ARTIFACT_PATHS["runtimePackageCommitter"] == \
        POSTGRES / "b64_064a_runtime_package_committer.py"
    assert "runtimePackageCommitter" in activation.ARTIFACT_KEYS


def test_activation_parent_contract_requires_sticky_root_payout_group(
    tmp_path,
):
    assert committer.ACTIVATION_PARENT_MODE == 0o3770
    assert committer.ACTIVATION_PARENT_GID == 986
    parent = tmp_path / "shared-parent"
    parent.mkdir(mode=0o700)
    parent.chmod(0o3770)
    descriptor = committer._open_root_directory(
        parent, exact_mode=0o3770, exact_gid=os.getgid(),
    )
    os.close(descriptor)

    with pytest.raises(
        committer.CommitError, match="RUNTIME_COMMIT_PARENT_UNSAFE",
    ):
        committer._open_root_directory(
            parent, exact_mode=0o3770, exact_gid=os.getgid() + 1,
        )

    parent.chmod(0o2770)
    with pytest.raises(
        committer.CommitError, match="RUNTIME_COMMIT_PARENT_UNSAFE",
    ):
        committer._open_root_directory(
            parent, exact_mode=0o3770, exact_gid=os.getgid(),
        )


def test_stage_state_explicitly_rebinds_private_root_to_root_group(
    tmp_path, monkeypatch,
):
    parent = tmp_path / "shared-parent"
    parent.mkdir(mode=0o700)
    parent.chmod(0o3770)
    observed = []
    real_fchown = os.fchown

    def record_fchown(descriptor, uid, gid):
        observed.append((uid, gid))
        real_fchown(descriptor, uid, gid)

    monkeypatch.setattr(committer.os, "fchown", record_fchown)
    verified = SimpleNamespace(
        run_nonce="production_nonce_1234",
        plan_sha256="2" * 64,
        decision_sha256="3" * 64,
    )
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        committer._stage_state(
            parent_fd, "private-state", verified=verified,
        )
    finally:
        os.close(parent_fd)

    state = parent / "private-state"
    assert observed == [(0, 0)]
    assert state.stat().st_uid == 0
    assert state.stat().st_gid == 0
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert all(
        child.stat().st_uid == 0 and child.stat().st_gid == 0
        and stat.S_IMODE(child.stat().st_mode) == 0o700
        for child in state.iterdir()
    )
    journal = state / "journal"
    assert set(path.name for path in journal.iterdir()) == {
        "production_nonce_1234.json", ".production_nonce_1234.lock",
    }


def test_load_and_verify_binds_exact_inputs_freshness_and_dormant_target(
    monkeypatch, tmp_path,
):
    inputs = {
        "keyring.json": b'{"keyringSha256":"' + b"1" * 64 + b'"}\n',
        "decision.json": b"signed-decision\n",
        "activation-plan.json": b"activation-plan\n",
    }
    target = {
        "containerName": activation.PRODUCTION_CONTAINER,
        "containerId": "a" * 64,
        "imageId": activation.PRODUCTION_IMAGE_ID,
        "systemIdentifier": activation.PRODUCTION_SYSTEM_IDENTIFIER,
    }
    verified = SimpleNamespace(expires_at_epoch=1300, target=target)
    observed = {}

    def verify(**kwargs):
        observed.update(kwargs)
        return verified

    monkeypatch.setattr(committer, "_load_coordination", lambda: inputs)
    monkeypatch.setattr(committer, "_trusted_now", lambda: 1000)
    monkeypatch.setattr(
        committer, "_dormant_tuple", lambda _release: dict(target),
    )
    monkeypatch.setattr(activation, "verify_activation_decision", verify)

    loaded, authorization = committer._load_and_verify(tmp_path)

    assert loaded is inputs
    assert authorization is verified
    assert observed == {
        "keyring_raw": inputs["keyring.json"],
        "decision_raw": inputs["decision.json"],
        "activation_plan_raw": inputs["activation-plan.json"],
        "expected_keyring_sha256": "1" * 64,
        "expected_environment": "PRODUCTION",
        "now_epoch": 1000,
    }


def test_load_and_verify_rejects_short_window_or_target_change(
    monkeypatch, tmp_path,
):
    inputs = {
        "keyring.json": b'{"keyringSha256":"' + b"1" * 64 + b'"}\n',
        "decision.json": b"signed-decision\n",
        "activation-plan.json": b"activation-plan\n",
    }
    target = {
        "containerName": activation.PRODUCTION_CONTAINER,
        "containerId": "a" * 64,
        "imageId": activation.PRODUCTION_IMAGE_ID,
        "systemIdentifier": activation.PRODUCTION_SYSTEM_IDENTIFIER,
    }
    verified = SimpleNamespace(expires_at_epoch=1299, target=target)
    monkeypatch.setattr(committer, "_load_coordination", lambda: inputs)
    monkeypatch.setattr(committer, "_trusted_now", lambda: 1000)
    monkeypatch.setattr(
        activation, "verify_activation_decision", lambda **_kwargs: verified,
    )
    monkeypatch.setattr(
        committer, "_dormant_tuple", lambda _release: dict(target),
    )
    with pytest.raises(
        committer.CommitError,
        match="INSUFFICIENT_DECISION_WINDOW_REMAINING",
    ):
        committer._load_and_verify(tmp_path)

    verified.expires_at_epoch = 1300
    changed = dict(target)
    changed["containerId"] = "c" * 64
    monkeypatch.setattr(
        committer, "_dormant_tuple", lambda _release: changed,
    )
    with pytest.raises(
        committer.CommitError,
        match="RUNTIME_COMMIT_PRODUCTION_TARGET_MISMATCH",
    ):
        committer._load_and_verify(tmp_path)


def test_commit_publishes_exact_bound_package_and_claimed_state(commit_state):
    result = committer.commit_runtime_package()

    assert result["status"] == \
        "RUNTIME_PACKAGE_COMMITTED_LAUNCHER_NOT_STARTED"
    assert result["launcherStarted"] is False
    assert result["actionAllowed"] is False
    assert result["activationAuthorizationClaimed"] is True
    assert result["activationJournalState"] == "CLAIMED"
    package = watchdog._load_recovery_package()
    launch = launcher._load_launch_request()
    assert package is not None
    assert package["stagedWithoutRequest"] is False
    assert package["keyring.json"] == commit_state["inputs"]["keyring.json"]
    assert package["decision.json"] == commit_state["inputs"]["decision.json"]
    assert package["activation-plan.json"] == \
        commit_state["inputs"]["activation-plan.json"]
    assert launch["runNonce"] == commit_state["verified"].run_nonce
    assert launch["operatorCommitOnly"] is True
    assert launch["grantsAuthority"] is False

    package_path, recovery_path, launch_path, state_path = _final_paths(
        commit_state,
    )
    assert stat.S_IMODE(package_path.stat().st_mode) == 0o500
    assert stat.S_IMODE(recovery_path.stat().st_mode) == 0o400
    assert stat.S_IMODE(launch_path.stat().st_mode) == 0o400
    assert recovery_path.stat().st_nlink == 1
    assert launch_path.stat().st_nlink == 1
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o700
    assert set(path.name for path in state_path.iterdir()) == \
        set(committer.STATE_NAMES)
    assert all(
        path.is_dir() and stat.S_IMODE(path.stat().st_mode) == 0o700
        and not any(path.iterdir())
        for path in state_path.iterdir() if path.name != "journal"
    )
    journal_path = state_path / "journal"
    nonce = commit_state["verified"].run_nonce
    assert set(path.name for path in journal_path.iterdir()) == {
        f"{nonce}.json", f".{nonce}.lock",
    }
    journal = activation.ActivationJournal(
        journal_path, commit_state["verified"],
    ).inspect()
    assert journal == activation._journal_claim_value(
        commit_state["verified"]
    )
    assert stat.S_IMODE((journal_path / f".{nonce}.lock").stat().st_mode) \
        == 0o600


@pytest.mark.parametrize("failure_point", [
    "after_staging",
    "after_package_publish",
    "after_state_publish",
    "after_recovery_request_publish",
    "after_postverify",
])
def test_every_partial_publication_fault_rolls_back_exactly(
    commit_state, failure_point,
):
    def fail(point):
        if point == failure_point:
            raise committer.CommitError("INJECTED_COMMIT_FAILURE")

    with pytest.raises(
        committer.CommitError, match="INJECTED_COMMIT_FAILURE",
    ):
        committer.commit_runtime_package(fault=fail)

    assert all(not path.exists() for path in _final_paths(commit_state))
    assert not any(
        path.name.startswith(".b64-064a-")
        for path in commit_state["recovery"].iterdir()
    )
    assert not any(
        path.name.startswith(".b64-064a-")
        for path in commit_state["activationRoot"].parent.iterdir()
    )


def test_failure_after_authority_publication_preserves_complete_commit(
    commit_state,
):
    def fail(point):
        if point == "after_launch_request_publish":
            raise committer.CommitError("INJECTED_POST_AUTHORITY_FAILURE")

    with pytest.raises(
        committer.CommitError,
        match="RUNTIME_COMMIT_AUTHORITY_PUBLICATION_UNCERTAIN",
    ):
        committer.commit_runtime_package(fault=fail)

    assert all(path.exists() for path in _final_paths(commit_state))
    result = committer.commit_runtime_package()
    assert result["activationJournalState"] == "CLAIMED"
    assert result["runtimePathsState"] == "COMMITTED_VERIFIED"


def test_main_never_reports_authority_publication_failure_as_absent(
    commit_state, monkeypatch, capsys,
):
    real_commit = committer.commit_runtime_package

    def invoke_with_post_authority_failure():
        def fail(point):
            if point == "after_launch_request_publish":
                raise OSError("injected post-authority reporting failure")

        return real_commit(fault=fail)

    monkeypatch.setattr(
        committer, "commit_runtime_package",
        invoke_with_post_authority_failure,
    )
    previous_umask = os.umask(0o077)
    try:
        assert committer.main() == 3
    finally:
        os.umask(previous_umask)
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["reason"] == \
        "RUNTIME_COMMIT_AUTHORITY_PUBLICATION_UNCERTAIN"
    assert receipt["runtimePackageCommitted"] is None
    assert receipt["activationAuthorizationClaimed"] is None
    assert receipt["runtimePathsState"] == \
        "COMMITTED_OR_RESUMABLE_PREFIX_REQUIRES_INSPECTION"
    assert all(path.exists() for path in _final_paths(commit_state))


def test_main_never_reports_complete_prefix_recheck_failure_as_absent(
    commit_state, monkeypatch, capsys,
):
    committed = committer.commit_runtime_package()
    assert committed["runtimePackageCommitted"] is True
    monkeypatch.setattr(
        committer, "_postverify",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            committer.CommitError("INJECTED_COMPLETE_RECHECK_FAILURE")
        ),
    )

    previous_umask = os.umask(0o077)
    try:
        assert committer.main() == 3
    finally:
        os.umask(previous_umask)
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["reason"] == \
        "RUNTIME_COMMIT_AUTHORITY_PUBLICATION_UNCERTAIN"
    assert receipt["runtimePackageCommitted"] is None
    assert receipt["activationAuthorizationClaimed"] is None
    assert receipt["runtimePathsState"] == \
        "COMMITTED_OR_RESUMABLE_PREFIX_REQUIRES_INSPECTION"
    assert all(path.exists() for path in _final_paths(commit_state))


@pytest.mark.parametrize("kill_point", [
    "after_staging",
    "after_package_publish",
    "after_recovery_request_publish",
    "after_state_publish",
    "after_launch_request_publish",
    "after_postverify",
])
def test_real_sigkill_prefix_is_exactly_resumed_or_recommitted(
    commit_state, kill_point,
):
    child = os.fork()
    if child == 0:
        def kill(point):
            if point == kill_point:
                os.kill(os.getpid(), signal.SIGKILL)

        committer.commit_runtime_package(fault=kill)
        os._exit(99)
    waited, status = os.waitpid(child, 0)
    assert waited == child
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL

    result = committer.commit_runtime_package()

    assert result["status"] == \
        "RUNTIME_PACKAGE_COMMITTED_LAUNCHER_NOT_STARTED"
    assert result["activationJournalState"] == "CLAIMED"
    assert all(path.exists() for path in _final_paths(commit_state))
    names = committer._transaction_names(commit_state["verified"])
    assert all(not (commit_state["recovery"] / names[key]).exists()
               for key in ("package_tmp", "recovery_tmp", "launch_tmp"))
    assert not (
        commit_state["activationRoot"].parent / names["state_tmp"]
    ).exists()


@pytest.mark.parametrize("kill_point", [
    "rollback_after_intent_staging",
    "rollback_after_intent_publish",
    "rollback_after_launch_move",
    "rollback_after_state_move",
    "rollback_after_recovery_move",
    "rollback_after_package_move",
    "rollback_after_package_cleanup",
    "rollback_after_state_cleanup",
    "rollback_after_recovery_cleanup",
    "rollback_after_launch_cleanup",
    "rollback_after_intent_cleanup",
])
def test_real_sigkill_rollback_is_exactly_resumed_then_recommitted(
    commit_state, kill_point,
):
    child = os.fork()
    if child == 0:
        def fail_then_kill(point):
            if point == "after_postverify":
                raise committer.CommitError("TRIGGER_EXACT_ROLLBACK")
            if point == kill_point:
                os.kill(os.getpid(), signal.SIGKILL)

        committer.commit_runtime_package(fault=fail_then_kill)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL

    result = committer.commit_runtime_package()
    assert result["status"] == \
        "RUNTIME_PACKAGE_COMMITTED_LAUNCHER_NOT_STARTED"
    assert result["activationJournalState"] == "CLAIMED"
    assert all(path.exists() for path in _final_paths(commit_state))
    names = committer._transaction_names(commit_state["verified"])
    assert all(not (commit_state["recovery"] / names[key]).exists()
               for key in (
                   "package_tmp", "recovery_tmp", "launch_tmp",
                   "rollback_intent_tmp", "rollback_intent",
               ))
    assert not (
        commit_state["activationRoot"].parent / names["state_tmp"]
    ).exists()


@pytest.mark.parametrize("partial_key", ["recovery_tmp", "launch_tmp"])
def test_partial_staged_marker_is_rollback_repaired_then_recommitted(
    commit_state, partial_key,
):
    names = committer._transaction_names(commit_state["verified"])
    child = os.fork()
    if child == 0:
        real_stage_file = committer._stage_file

        def partial_stage(parent_fd, name, raw, *, mode):
            if name != names[partial_key]:
                return real_stage_file(parent_fd, name, raw, mode=mode)
            descriptor = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                mode, dir_fd=parent_fd,
            )
            try:
                os.write(descriptor, raw[:max(1, len(raw) // 2)])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            raise committer.CommitError("INJECTED_PARTIAL_STAGE_WRITE")

        def kill_rollback(point):
            if point == "rollback_after_intent_publish":
                os.kill(os.getpid(), signal.SIGKILL)

        committer._stage_file = partial_stage
        committer.commit_runtime_package(fault=kill_rollback)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL
    assert (
        commit_state["recovery"] / names["rollback_intent"]
    ).exists()

    result = committer.commit_runtime_package()
    assert result["runtimePathsState"] == "COMMITTED_VERIFIED"
    assert all(path.exists() for path in _final_paths(commit_state))
    assert not any(
        (commit_state["recovery"] / names[key]).exists()
        for key in (
            "package_tmp", "recovery_tmp", "launch_tmp",
            "rollback_intent_tmp", "rollback_intent",
        )
    )


def test_rollback_intent_rejects_consumed_or_drifted_state(
    commit_state,
):
    child = os.fork()
    if child == 0:
        def fail_then_kill(point):
            if point == "after_postverify":
                raise committer.CommitError("TRIGGER_EXACT_ROLLBACK")
            if point == "rollback_after_intent_publish":
                os.kill(os.getpid(), signal.SIGKILL)

        committer.commit_runtime_package(fault=fail_then_kill)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)

    state = commit_state["activationRoot"]
    journal = activation.ActivationJournal(
        state / "journal", commit_state["verified"],
    )
    journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
    with pytest.raises(
        committer.CommitError, match="RUNTIME_COMMIT_PREFIX_CHANGED",
    ):
        committer.commit_runtime_package()
    assert state.exists()
    assert (
        commit_state["recovery"] / launcher.ROLLBACK_INTENT_NAME
    ).exists()


def test_expired_sigkill_rollback_is_cleanup_only_and_never_launches(
    commit_state, monkeypatch,
):
    child = os.fork()
    if child == 0:
        def fail_then_kill(point):
            if point == "after_postverify":
                raise committer.CommitError("TRIGGER_EXACT_ROLLBACK")
            if point == "rollback_after_state_move":
                os.kill(os.getpid(), signal.SIGKILL)

        committer.commit_runtime_package(fault=fail_then_kill)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)

    current = commit_state["verified"]
    recovery = activation.VerifiedRecovery(
        environment="PRODUCTION", run_nonce=current.run_nonce,
        plan_sha256=current.plan_sha256,
        decision_sha256=current.decision_sha256,
        keyring_sha256=current.keyring_sha256,
        derived_execution_plan_sha256="4" * 64,
        decision_expires_at_epoch=1_700_000_000,
        target=current.target, limits=dict(activation.LIMITS),
        _recovery_seal=activation._VERIFIED_RECOVERY_SEAL,
    )
    monkeypatch.setattr(
        committer, "_load_and_verify",
        lambda _release, **_kwargs: (commit_state["inputs"], recovery),
    )
    result = committer.commit_runtime_package()
    assert result["status"] == \
        "RUNTIME_COMMIT_EXPIRED_PREFIX_CLEANED_NO_LAUNCH"
    assert result["runtimePackageCommitted"] is False
    assert all(not path.exists() for path in _final_paths(commit_state))
    names = committer._transaction_names(recovery)
    assert not (
        commit_state["recovery"] / names["rollback_intent"]
    ).exists()


def test_sigkill_prefix_drift_is_preserved_and_rejected(commit_state):
    child = os.fork()
    if child == 0:
        def kill(point):
            if point == "after_package_publish":
                os.kill(os.getpid(), signal.SIGKILL)

        committer.commit_runtime_package(fault=kill)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)

    package = commit_state["recovery"] / watchdog.RECOVERY_PACKAGE_NAME
    package.chmod(0o700)
    artifact = package / "keyring.json"
    artifact.chmod(0o600)
    artifact.write_bytes(b'{"drift":true}\n')
    artifact.chmod(0o400)
    package.chmod(0o500)

    with pytest.raises(
        committer.CommitError, match="RUNTIME_COMMIT_PREFIX_CHANGED",
    ):
        committer.commit_runtime_package()
    assert package.exists()
    assert artifact.read_bytes() == b'{"drift":true}\n'
    assert not commit_state["activationRoot"].exists()
    assert not (
        commit_state["recovery"] / launcher.LAUNCH_REQUEST_NAME
    ).exists()


@pytest.mark.parametrize(
    "kill_point,expected_status,committed",
    [
        (
            "after_package_publish",
            "RUNTIME_COMMIT_EXPIRED_PREFIX_CLEANED_NO_LAUNCH", False,
        ),
        (
            "after_recovery_request_publish",
            "RUNTIME_COMMIT_EXPIRED_PREFIX_CLEANED_NO_LAUNCH", False,
        ),
        (
            "after_state_publish",
            "RUNTIME_PACKAGE_RECOVERED_EXPIRED_LAUNCHER_NOT_STARTED", True,
        ),
    ],
)
def test_expired_exact_sigkill_prefix_has_historical_recovery(
    commit_state, monkeypatch, kill_point, expected_status, committed,
):
    child = os.fork()
    if child == 0:
        def kill(point):
            if point == kill_point:
                os.kill(os.getpid(), signal.SIGKILL)

        committer.commit_runtime_package(fault=kill)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)

    current = commit_state["verified"]
    recovery = activation.VerifiedRecovery(
        environment="PRODUCTION", run_nonce=current.run_nonce,
        plan_sha256=current.plan_sha256,
        decision_sha256=current.decision_sha256,
        keyring_sha256=current.keyring_sha256,
        derived_execution_plan_sha256="4" * 64,
        decision_expires_at_epoch=1_700_000_000,
        target=current.target, limits=dict(activation.LIMITS),
        _recovery_seal=activation._VERIFIED_RECOVERY_SEAL,
    )
    monkeypatch.setattr(
        committer, "_load_and_verify",
        lambda _release, **_kwargs: (commit_state["inputs"], recovery),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery", lambda **_kwargs: recovery,
    )
    result = committer.commit_runtime_package()

    assert result["status"] == expected_status
    assert result["runtimePackageCommitted"] is committed
    package, recovery_path, launch, state = _final_paths(commit_state)
    if committed:
        assert all(path.exists() for path in (
            package, recovery_path, launch, state,
        ))
        assert result["historicalPrefixRecovery"] is True
        assert activation.ActivationJournal(
            state / "journal", recovery,
        ).inspect()["state"] == "CLAIMED"
    else:
        assert all(not path.exists() for path in (
            package, recovery_path, launch, state,
        ))


def test_state_before_launch_kill_is_nonmutating_then_terminal_archived(
    commit_state, monkeypatch, tmp_path,
):
    child = os.fork()
    if child == 0:
        def kill(point):
            if point == "after_state_publish":
                os.kill(os.getpid(), signal.SIGKILL)

        committer.commit_runtime_package(fault=kill)
        os._exit(99)
    _waited, status = os.waitpid(child, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL

    package, recovery_path, launch_path, state = _final_paths(commit_state)
    assert package.exists() and recovery_path.exists() and state.exists()
    assert not launch_path.exists()
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for root in (package, state)
        for path in root.rglob("*") if path.is_file()
    }
    before[str(recovery_path.relative_to(tmp_path))] = \
        recovery_path.read_bytes()

    target = commit_state["verified"].target
    dormant = {
        "schemaVersion": "obsidian-b64-snapshot-reader-watchdog.v1",
        "status": "DORMANT_VERIFIED", "watchdogReady": True,
        "container": {
            "containerId": target["containerId"], "containerPid": 1234,
            "imageId": target["imageId"], "health": "healthy",
            "startedAt": "2026-08-26T00:00:00Z", "restartCount": 0,
            "hostPort": 5432,
            "mountSource": (
                "/var/lib/docker/volumes/obsidian-postgres-data/_data"
            ),
        },
        "serverVersionNum": 170011,
        "systemIdentifier": target["systemIdentifier"],
        "roleLoginState": "DISABLED", "credentialState": "ABSENT",
        "activeSessions": 0, "dormantRequired": True,
        "activationInterlockHeld": False, "customerRowsRead": False,
        "hbaChanged": False, "authorityIncreased": False,
    }
    monkeypatch.setattr(
        watchdog, "watchdog_once", lambda **_kwargs: dict(dormant),
    )
    monkeypatch.setattr(
        watchdog, "_activation_interlock_status",
        lambda *_args, **_kwargs: contextlib.nullcontext(False),
    )

    pending = watchdog.watchdog_with_cleanup_recovery(
        container_name=activation.PRODUCTION_CONTAINER,
        expected_image_id=activation.PRODUCTION_IMAGE_ID,
        expected_volume_name=watchdog.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert pending["status"] == "DORMANT_VERIFIED_COMMIT_PREFIX_PENDING"
    after = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for root in (package, state)
        for path in root.rglob("*") if path.is_file()
    }
    after[str(recovery_path.relative_to(tmp_path))] = \
        recovery_path.read_bytes()
    assert after == before

    current = commit_state["verified"]
    verified_recovery = activation.VerifiedRecovery(
        environment="PRODUCTION", run_nonce=current.run_nonce,
        plan_sha256=current.plan_sha256,
        decision_sha256=current.decision_sha256,
        keyring_sha256=current.keyring_sha256,
        derived_execution_plan_sha256="4" * 64,
        decision_expires_at_epoch=1_700_000_000,
        target=current.target, limits=dict(activation.LIMITS),
        _recovery_seal=activation._VERIFIED_RECOVERY_SEAL,
    )
    monkeypatch.setattr(
        committer, "_load_and_verify",
        lambda _release, **_kwargs: (
            commit_state["inputs"], verified_recovery,
        ),
    )
    monkeypatch.setattr(
        activation, "verify_cleanup_recovery",
        lambda **_kwargs: verified_recovery,
    )
    resumed = committer.commit_runtime_package()
    assert resumed["status"] == \
        "RUNTIME_PACKAGE_RECOVERED_EXPIRED_LAUNCHER_NOT_STARTED"
    assert launch_path.exists()

    activation_executor = importlib.import_module(
        "b64_064a_activation_executor"
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
    monkeypatch.setattr(
        activation.supervisor, "_trusted_now_epoch",
        lambda: (1_800_000_000, {}),
    )

    def reconcile(**_kwargs):
        journal = activation.ActivationJournal(
            state / "journal", verified_recovery,
        )
        journal.transition(
            expected_state={"CLAIMED"}, state="RECONCILED_HOLD",
            reason_code="ABNORMAL_EXIT_RECONCILED_NO_RETRY",
        )
        resource_path = (
            state / "resources"
            / f"{verified_recovery.run_nonce}.resources.json"
        )
        resource_path.write_bytes(b"synthetic terminal resources\n")
        resource_path.chmod(0o600)
        return {
            "status": "ACTIVATION_RECONCILED_HOLD",
            "runNonce": verified_recovery.run_nonce,
            "automaticRetryAllowed": False, "actionAllowed": False,
        }

    monkeypatch.setattr(activation, "reconcile_incomplete", reconcile)
    terminal = watchdog.watchdog_with_cleanup_recovery(
        container_name=activation.PRODUCTION_CONTAINER,
        expected_image_id=activation.PRODUCTION_IMAGE_ID,
        expected_volume_name=watchdog.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
    )
    assert terminal["status"] == \
        "DORMANT_VERIFIED_RECOVERY_RECONCILED_HOLD"
    assert activation.ActivationJournal(
        state / "journal", verified_recovery,
    ).inspect()["state"] == "RECONCILED_HOLD"

    backup = tmp_path / "backups"
    backup.mkdir(mode=0o755)
    backup.chmod(0o755)
    os.chown(backup, 0, 0)
    monkeypatch.setattr(archiver, "BACKUP_BASE", backup)
    monkeypatch.setattr(archiver, "ARCHIVE_PARENT", backup / "terminal")
    monkeypatch.setattr(archiver, "RECOVERY_PARENT", commit_state["recovery"])
    monkeypatch.setattr(archiver, "ACTIVATION_ROOT", state)
    expected_files = archiver._expected_files(
        nonce=verified_recovery.run_nonce, activation_root=state,
        recovery_parent=commit_state["recovery"],
        terminal_state="RECONCILED_HOLD",
    )
    files = {}
    for relative, (path, mode, allow_empty) in expected_files.items():
        raw = path.read_bytes()
        assert allow_empty or raw
        files[relative] = {
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size": len(raw), "mode": mode,
        }
    unsigned = {
        "schemaVersion": archiver.ARCHIVE_SCHEMA,
        "route": activation.ROUTE,
        "runNonce": verified_recovery.run_nonce,
        "decisionSha256": verified_recovery.decision_sha256,
        "planSha256": verified_recovery.plan_sha256,
        "keyringSha256": verified_recovery.keyring_sha256,
        "implementationCommit": "a" * 40,
        "archiverSha256": "5" * 64,
        "signedArtifactReleaseCommit": "a" * 40,
        "decisionExpiresAtEpoch": 1_700_000_000,
        "archiveAuthorizedAtEpoch": 1_800_000_000,
        "terminalState": "RECONCILED_HOLD",
        "terminalReason": "ABNORMAL_EXIT_RECONCILED_NO_RETRY",
        "terminalReceiptSha256": None,
        "resourceState": "RECONCILED_HOLD",
        "credentialIssued": False, "credentialReconciled": True,
        "workspaceAbsent": True, "proxyAbsent": True,
        "dumpAbsent": True, "restoreAbsent": True,
        "roleLoginState": "DISABLED", "credentialState": "ABSENT",
        "activeSessions": 0, "containerId": target["containerId"],
        "containerPid": 1234, "imageId": target["imageId"],
        "systemIdentifier": target["systemIdentifier"],
        "files": files, "sourceComponents": sorted(archiver.COMPONENTS),
        "archiverCustomerRowsRead": False,
        "terminalRunCustomerRowReadState": "NOT_READ",
        "hbaChanged": False, "authorityIncreased": False,
        "automaticRetryAllowed": False, "activationRetryAllowed": False,
    }
    manifest = {
        **unsigned,
        "manifestSha256": archiver._sha(archiver._canonical(unsigned)),
    }
    archived, observed_manifest, already = archiver._publish_archive(
        nonce=verified_recovery.run_nonce,
        decision_sha256=verified_recovery.decision_sha256,
        manifest_raw=archiver._canonical(manifest) + b"\n",
    )
    assert already is False
    assert observed_manifest["terminalState"] == "RECONCILED_HOLD"
    assert archived.exists()
    assert all(not path.exists() for path in _final_paths(commit_state))


def test_postverification_failure_rolls_back_all_runtime_paths(
    commit_state, monkeypatch,
):
    monkeypatch.setattr(
        committer, "_postverify",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            committer.CommitError("POSTVERIFY_INJECTED_FAILURE")
        ),
    )
    with pytest.raises(
        committer.CommitError, match="POSTVERIFY_INJECTED_FAILURE",
    ):
        committer.commit_runtime_package()
    assert all(not path.exists() for path in _final_paths(commit_state))


@pytest.mark.parametrize("publication", ["package", "state", "recovery"])
def test_fsync_failure_immediately_after_publication_is_rolled_back(
    commit_state, monkeypatch, publication,
):
    package, recovery, launch, state = _final_paths(commit_state)
    real_fsync = os.fsync
    failed = False

    def injected_fsync(descriptor):
        nonlocal failed
        at_boundary = {
            "package": package.exists() and not recovery.exists(),
            "recovery": recovery.exists() and not state.exists(),
            "state": state.exists() and not launch.exists(),
            "launch": launch.exists(),
        }[publication]
        if at_boundary and not failed:
            failed = True
            raise OSError("injected publication fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(committer.os, "fsync", injected_fsync)
    with pytest.raises(committer.CommitError):
        committer.commit_runtime_package()
    assert failed is True
    assert all(not path.exists() for path in _final_paths(commit_state))


def test_fsync_failure_after_launch_publication_preserves_complete_commit(
    commit_state, monkeypatch,
):
    package, recovery, launch, state = _final_paths(commit_state)
    real_fsync = os.fsync
    failed = False

    def injected_fsync(descriptor):
        nonlocal failed
        if launch.exists() and not failed:
            failed = True
            raise OSError("injected launch publication fsync failure")
        return real_fsync(descriptor)

    monkeypatch.setattr(committer.os, "fsync", injected_fsync)
    with pytest.raises(committer.CommitError):
        committer.commit_runtime_package()
    assert failed is True
    assert all(path.exists() for path in (package, recovery, launch, state))

    monkeypatch.setattr(committer.os, "fsync", real_fsync)
    result = committer.commit_runtime_package()
    assert result["runtimePathsState"] == "COMMITTED_VERIFIED"


def test_marker_publication_uses_atomic_rename_not_link_unlink(
    commit_state, monkeypatch,
):
    monkeypatch.setattr(
        committer.os, "link",
        lambda *_args, **_kwargs: pytest.fail("hard-link publication used"),
    )
    result = committer.commit_runtime_package()
    assert result["activationJournalState"] == "CLAIMED"
    assert all(path.exists() for path in _final_paths(commit_state))


def test_existing_runtime_target_is_preserved_and_nothing_else_is_staged(
    commit_state,
):
    existing = commit_state["recovery"] / launcher.LAUNCH_REQUEST_NAME
    existing.write_bytes(b"owner-controlled-existing\n")
    existing.chmod(0o400)

    with pytest.raises(
        committer.CommitError, match="RUNTIME_COMMIT_PREFIX_SHAPE_INVALID",
    ):
        committer.commit_runtime_package()

    assert existing.read_bytes() == b"owner-controlled-existing\n"
    assert not (
        commit_state["recovery"] / watchdog.RECOVERY_PACKAGE_NAME
    ).exists()
    assert not (
        commit_state["recovery"] / watchdog.RECOVERY_REQUEST_NAME
    ).exists()
    assert not commit_state["activationRoot"].exists()


def test_committer_never_calls_launcher(commit_state, monkeypatch):
    monkeypatch.setattr(
        launcher, "main",
        lambda: pytest.fail("committer must never call launcher.main"),
    )
    monkeypatch.setattr(
        launcher, "supervise_once",
        lambda *_args, **_kwargs: pytest.fail(
            "committer must never supervise launcher"
        ),
    )
    result = committer.commit_runtime_package()
    assert result["launcherStarted"] is False


def test_committer_holds_activation_interlock_through_publication(
    commit_state,
):
    observations = []

    def observe(point):
        if point == "after_launch_request_publish":
            with pytest.raises(
                activation.ActivationError,
                match="ACTIVATION_INTERLOCK_HELD",
            ):
                activation._acquire_production_interlock(
                    commit_state["verified"]
                )
            observations.append(point)

    result = committer.commit_runtime_package(fault=observe)
    assert result["activationJournalState"] == "CLAIMED"
    assert observations == ["after_launch_request_publish"]


def test_root_fixed_no_argument_release_identity_is_required(monkeypatch):
    monkeypatch.setattr(sys, "argv", [sys.argv[0], "--target", "/tmp"])
    with pytest.raises(
        committer.CommitError,
        match="RUNTIME_COMMIT_FIXED_ROOT_COMMAND_REQUIRED",
    ):
        committer._verify_runtime_identity()


def test_lock_rejects_symlink(commit_state):
    target = commit_state["activationRoot"].parent / "lock-target"
    target.write_text("x", encoding="utf-8")
    committer.LOCK_PATH.symlink_to(target)
    with pytest.raises(committer.CommitError, match="RUNTIME_COMMIT_LOCK_UNSAFE"):
        committer.commit_runtime_package()
