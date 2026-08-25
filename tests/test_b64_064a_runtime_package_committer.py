from __future__ import annotations

import importlib
import os
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
        committer, "_load_and_verify", lambda _release: (inputs, verified),
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


def test_commit_publishes_exact_bound_package_and_empty_state(commit_state):
    result = committer.commit_runtime_package()

    assert result["status"] == \
        "RUNTIME_PACKAGE_COMMITTED_LAUNCHER_NOT_STARTED"
    assert result["launcherStarted"] is False
    assert result["actionAllowed"] is False
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
        for path in state_path.iterdir()
    )


@pytest.mark.parametrize("failure_point", [
    "after_staging",
    "after_package_publish",
    "after_state_publish",
    "after_recovery_request_publish",
    "after_launch_request_publish",
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


def test_postverification_failure_rolls_back_all_runtime_paths(
    commit_state, monkeypatch,
):
    monkeypatch.setattr(
        committer, "_postverify",
        lambda *_args: (_ for _ in ()).throw(
            committer.CommitError("POSTVERIFY_INJECTED_FAILURE")
        ),
    )
    with pytest.raises(
        committer.CommitError, match="POSTVERIFY_INJECTED_FAILURE",
    ):
        committer.commit_runtime_package()
    assert all(not path.exists() for path in _final_paths(commit_state))


@pytest.mark.parametrize("publication", [
    "package", "state", "recovery", "launch",
])
def test_fsync_failure_immediately_after_publication_is_rolled_back(
    commit_state, monkeypatch, publication,
):
    package, recovery, launch, state = _final_paths(commit_state)
    real_fsync = os.fsync
    failed = False

    def injected_fsync(descriptor):
        nonlocal failed
        at_boundary = {
            "package": package.exists() and not state.exists(),
            "state": state.exists() and not recovery.exists(),
            "recovery": recovery.exists() and not launch.exists(),
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


def test_marker_temp_unlink_failure_after_link_is_rolled_back(
    commit_state, monkeypatch,
):
    real_unlink = os.unlink
    failed = False

    def injected_unlink(path, *args, **kwargs):
        nonlocal failed
        if (not failed and isinstance(path, str)
                and path.startswith(
                    f".{watchdog.RECOVERY_REQUEST_NAME}.tmp-"
                )
                and (commit_state["recovery"]
                     / watchdog.RECOVERY_REQUEST_NAME).exists()):
            failed = True
            raise OSError("injected marker temp unlink failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(committer.os, "unlink", injected_unlink)
    with pytest.raises(
        committer.CommitError,
        match="RUNTIME_COMMIT_MARKER_PUBLICATION_FAILED",
    ):
        committer.commit_runtime_package()
    assert failed is True
    assert all(not path.exists() for path in _final_paths(commit_state))


def test_existing_runtime_target_is_preserved_and_nothing_else_is_staged(
    commit_state,
):
    existing = commit_state["recovery"] / launcher.LAUNCH_REQUEST_NAME
    existing.write_bytes(b"owner-controlled-existing\n")
    existing.chmod(0o400)

    with pytest.raises(
        committer.CommitError, match="RUNTIME_COMMIT_TARGET_ALREADY_EXISTS",
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
