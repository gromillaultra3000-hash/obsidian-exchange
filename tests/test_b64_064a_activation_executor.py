from __future__ import annotations

import hashlib
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

activation = importlib.import_module("b64_064a_activation_entrypoint")
executor = importlib.import_module("b64_064a_activation_executor")


def _target() -> dict[str, str]:
    return {
        "containerName": "b64-hba-contract-1700000000",
        "containerId": "1" * 64,
        "imageId": "sha256:" + "2" * 64,
        "systemIdentifier": "1234567890123456789",
    }


def _journal(tmp_path: Path) -> executor.ExecutorResourceJournal:
    tmp_path.chmod(0o700)
    return executor.ExecutorResourceJournal(
        root=tmp_path, run_nonce="YWN0aXZhdGlvbi1ydW4tMDE",
        environment="DISPOSABLE_CONTRACT", target=_target(),
        plan_sha256="3" * 64, decision_sha256="4" * 64,
        derived_plan_sha256="5" * 64,
    )


def test_resource_journal_is_digest_bound_monotonic_and_replay_closed(tmp_path):
    journal = _journal(tmp_path)
    journal.create()
    assert journal.inspect()["derivedExecutionPlanSha256"] == "5" * 64
    with pytest.raises(
        executor.ExecutorError, match="EXECUTOR_RESOURCE_JOURNAL_REPLAY"
    ):
        journal.create()
    journal.update(state="RUNNING", credentialIssued=True)
    journal.update(proxyPid=123, proxyStartTime=456)
    with pytest.raises(
        executor.ExecutorError, match="EXECUTOR_RESOURCE_JOURNAL_REGRESSION"
    ):
        journal.update(proxyPid=124)
    journal.update(state="HOLD")
    journal.update(state="RECONCILED_HOLD", credentialReconciled=True)
    with pytest.raises(
        executor.ExecutorError, match="EXECUTOR_RESOURCE_STATE_CONFLICT"
    ):
        journal.update(state="HOLD")


def test_resource_journal_symlink_is_never_followed(tmp_path):
    journal = _journal(tmp_path)
    journal.path.symlink_to(tmp_path / "foreign")
    with pytest.raises(executor.ExecutorError):
        journal.create()
    with pytest.raises(executor.ExecutorError):
        journal.inspect()


def test_workspace_reconcile_preserves_replaced_inode_and_canary(tmp_path):
    workspace_parent = tmp_path / "workspaces"
    workspace_parent.mkdir(mode=0o700)
    journal = _journal(tmp_path)
    journal.create()
    workspace = workspace_parent / journal.initial["workspaceName"]
    workspace.mkdir(mode=0o700)
    original = workspace.stat()
    journal.update(state="RUNNING")
    journal.update(
        workspaceDev=original.st_dev, workspaceIno=original.st_ino,
    )
    original_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
    workspace.rmdir()
    workspace.mkdir(mode=0o700)
    canary = workspace / "snapshot.dump"
    canary.write_bytes(b"preserve-me")
    canary.chmod(0o600)
    bound = object.__new__(executor.BoundActivationExecutor)
    bound.workspace_parent = workspace_parent
    try:
        with pytest.raises(
            executor.ExecutorError,
            match="RECONCILE_WORKSPACE_BINDING_MISMATCH",
        ):
            bound._reconcile_workspace(journal.inspect())
    finally:
        os.close(original_fd)
    assert canary.read_bytes() == b"preserve-me"


def test_workspace_reconcile_durably_removes_exact_bound_inode(tmp_path):
    workspace_parent = tmp_path / "workspaces"
    workspace_parent.mkdir(mode=0o700)
    journal = _journal(tmp_path)
    journal.create()
    journal.update(state="RUNNING")
    workspace = workspace_parent / journal.initial["workspaceName"]
    workspace.mkdir(mode=0o700)
    metadata = workspace.stat()
    transient = workspace / "snapshot.dump"
    transient.write_bytes(b"synthetic")
    transient.chmod(0o600)
    journal.update(
        workspaceDev=metadata.st_dev, workspaceIno=metadata.st_ino,
    )
    bound = object.__new__(executor.BoundActivationExecutor)
    bound.workspace_parent = workspace_parent
    assert bound._reconcile_workspace(journal.inspect()) is True
    assert not workspace.exists()


def test_dangling_resource_symlink_is_not_absent(tmp_path):
    candidate = tmp_path / "resource"
    candidate.symlink_to(tmp_path / "missing")
    assert executor._path_entry_absent(candidate) is False


@pytest.mark.parametrize("resource_state", ["PREPARED", "RUNNING", "HOLD"])
def test_resource_reconcile_closes_each_crash_state(
    monkeypatch, tmp_path, resource_state,
):
    workspace = tmp_path / "workspace"
    proxy = tmp_path / "proxy"
    resources_root = tmp_path / "resources"
    for path in (workspace, proxy, resources_root):
        path.mkdir(mode=0o700)
    run_nonce = "YWN0aXZhdGlvbi1ydW4tMDE"
    target = _target()
    derived = {"bound": "derived-plan"}
    verified = activation.VerifiedActivation(
        environment="DISPOSABLE_CONTRACT", run_nonce=run_nonce,
        plan_sha256="3" * 64, decision_sha256="4" * 64,
        keyring_sha256="5" * 64,
        derived_execution_plan_sha256=hashlib.sha256(
            activation._canonical(derived)
        ).hexdigest(),
        expires_at_epoch=2_000_000_000, target=target,
        limits=dict(activation.LIMITS),
        _verification_seal=activation._VERIFIED_ACTIVATION_SEAL,
        _capability_state=activation._ExecutionCapabilityState(),
    )
    journal = executor.ExecutorResourceJournal(
        root=resources_root, run_nonce=run_nonce,
        environment=verified.environment, target=target,
        plan_sha256=verified.plan_sha256,
        decision_sha256=verified.decision_sha256,
        derived_plan_sha256=verified.derived_execution_plan_sha256,
    )
    journal.create()
    if resource_state in {"RUNNING", "HOLD"}:
        journal.update(state="RUNNING")
    if resource_state == "HOLD":
        journal.update(state="HOLD")
    bound = executor.BoundActivationExecutor(
        production_contact=False, observation_dsn="unused",
        admin_dsn="unused", container=target["containerName"],
        container_id=target["containerId"], image_id=target["imageId"],
        system_identifier=target["systemIdentifier"],
        workspace_parent=workspace, proxy_parent=proxy,
        resource_journal_root=resources_root,
    )
    monkeypatch.setattr(
        activation, "derive_execution_plan", lambda **_kwargs: derived,
    )
    monkeypatch.setattr(
        executor.runtime, "reconcile_credential", lambda **_kwargs: {
            "loginState": "DISABLED", "credentialState": "ABSENT",
            "activeSessions": 0,
        },
    )
    monkeypatch.setattr(bound, "_reconcile_proxy", lambda _value: True)
    monkeypatch.setattr(bound, "_reconcile_container", lambda **_kwargs: True)
    monkeypatch.setattr(bound, "_reconcile_workspace", lambda _value: True)
    monkeypatch.setattr(executor, "_inspect_container", lambda _name: None)
    result = bound.reconcile_resources(
        plan={"artifactsSha256": {}}, authorization=verified,
    )
    assert result["status"] == "EXECUTOR_RESOURCES_RECONCILED_HOLD"
    assert journal.inspect()["state"] == "RECONCILED_HOLD"
    repeated = bound.reconcile_resources(
        plan={"artifactsSha256": {}}, authorization=verified,
    )
    assert repeated["status"] == "EXECUTOR_RESOURCES_RECONCILED_HOLD"
    assert journal.inspect()["state"] == "RECONCILED_HOLD"


def test_inspection_distinguishes_exact_absence_from_daemon_failure(monkeypatch):
    reference = "b64-064a-dump-" + "a" * 20
    monkeypatch.setattr(
        executor, "_run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 1, "", f"Error: No such object: {reference}\n"
        ),
    )
    assert executor._inspect_container(reference) is None
    monkeypatch.setattr(
        executor, "_run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 1, "", "permission denied\n"
        ),
    )
    with pytest.raises(
        executor.ExecutorError, match="CONTAINER_INSPECTION_UNAVAILABLE"
    ):
        executor._inspect_container(reference)


def test_production_executor_rejects_caller_selected_state_roots(tmp_path):
    roots = []
    for name in ("workspace", "proxy", "resources"):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        roots.append(path)
    with pytest.raises(
        executor.ExecutorError, match="PRODUCTION_EXECUTOR_BINDING_MISMATCH"
    ):
        executor.BoundActivationExecutor(
            production_contact=True,
            observation_dsn="unused", admin_dsn="unused",
            container=activation.PRODUCTION_CONTAINER,
            container_id="1" * 64,
            image_id=activation.PRODUCTION_IMAGE_ID,
            system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
            workspace_parent=roots[0], proxy_parent=roots[1],
            resource_journal_root=roots[2],
        )


def test_proxy_journal_failure_kills_unregistered_child(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    real_popen = subprocess.Popen
    child: subprocess.Popen[bytes] | None = None

    def harmless_popen(*_args, **_kwargs):
        nonlocal child
        child = real_popen(
            ["/usr/bin/sleep", "30"], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return child

    class BrokenJournal:
        def update(self, **_changes):
            raise executor.ExecutorError("SYNTHETIC_JOURNAL_FAILURE")

    monkeypatch.setattr(executor.subprocess, "Popen", harmless_popen)
    monkeypatch.setattr(executor.os, "chown", lambda *_a, **_k: None)
    netns_inode = os.stat(f"/proc/{os.getpid()}/ns/net").st_ino
    artifact_sha = hashlib.sha256(Path(executor.__file__).read_bytes()).hexdigest()
    proxy = executor.ExactProxy(
        run_nonce="YWN0aXZhdGlvbi1ydW4tMDE", parent=tmp_path,
        source_pid=os.getpid(), source_netns_inode=netns_inode,
        deadline=executor.time.monotonic() + 10,
        executor_sha256=artifact_sha, resource_journal=BrokenJournal(),
    )
    with pytest.raises(executor.ExecutorError, match="SYNTHETIC_JOURNAL_FAILURE"):
        proxy.start()
    assert child is not None
    assert child.poll() is not None
    assert not proxy.directory.exists()


def test_final_postverify_failure_puts_resource_journal_on_hold(
    monkeypatch, tmp_path,
):
    roots = []
    for name in ("workspace", "proxy", "resources"):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        roots.append(path)
    artifacts = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in activation.ARTIFACT_PATHS.items()
    }
    run_nonce = "YWN0aXZhdGlvbi1ydW4tMDE"
    plan = activation.build_plan(
        environment="DISPOSABLE_CONTRACT", run_nonce=run_nonce,
        created_at_epoch=1_800_000_000,
        container_name=_target()["containerName"],
        container_id=_target()["containerId"],
        image_id=_target()["imageId"],
        system_identifier=_target()["systemIdentifier"],
        artifacts_sha256=artifacts,
    )
    derived = activation.derive_execution_plan(
        run_nonce=run_nonce, artifacts_sha256=artifacts,
    )
    capability = activation._ExecutionCapabilityState()
    capability.begin_execution()
    verified = activation.VerifiedActivation(
        environment="DISPOSABLE_CONTRACT", run_nonce=run_nonce,
        plan_sha256=hashlib.sha256(activation._canonical(plan)).hexdigest(),
        decision_sha256="4" * 64, keyring_sha256="5" * 64,
        derived_execution_plan_sha256=hashlib.sha256(
            activation._canonical(derived)
        ).hexdigest(),
        expires_at_epoch=2_000_000_000, target=dict(plan["target"]),
        limits=dict(activation.LIMITS),
        _verification_seal=activation._VERIFIED_ACTIVATION_SEAL,
        _capability_state=capability,
    )

    class Lease:
        source_fd = 10
        dump_fd = 11
        source_netns_inode = 12

        def close(self):
            return {"loginState": "DISABLED"}

    monkeypatch.setattr(executor.runtime, "issue_credential_lease", lambda **_k: Lease())
    monkeypatch.setattr(executor.runtime, "ProductionSourceAdapter", lambda *_a, **_k: object())
    monkeypatch.setattr(
        executor.refresh, "execute_hermetic",
        lambda *_a, **_k: {
            "status": "COMPLETED", "cleanupStatus": "CLEANUP_VERIFIED",
            "archiveBytes": 100, "archiveSha256": "6" * 64,
            "cleanup": {
                "workspaceAbsent": True, "dumpContainerAbsent": True,
                "restoreContainerAbsent": True,
                "credentialRevocationAttested": True,
                "sourceSessionClosed": True,
                "containerTmpfsLifetimesEnded": True,
            },
        },
    )
    monkeypatch.setattr(
        executor, "inspect",
        lambda *_a, **_k: (_ for _ in ()).throw(
            executor.ExecutorError("SYNTHETIC_FINAL_INSPECTION_FAILURE")
        ),
    )
    bound = executor.BoundActivationExecutor(
        production_contact=False,
        observation_dsn="unused", admin_dsn="unused",
        container=plan["target"]["containerName"],
        container_id=plan["target"]["containerId"],
        image_id=plan["target"]["imageId"],
        system_identifier=plan["target"]["systemIdentifier"],
        workspace_parent=roots[0], proxy_parent=roots[1],
        resource_journal_root=roots[2],
    )
    with pytest.raises(
        executor.ExecutorError, match="SYNTHETIC_FINAL_INSPECTION_FAILURE"
    ):
        bound.execute(plan, verified, executor.time.monotonic() + 100.0)
    journal = executor.ExecutorResourceJournal(
        root=roots[2], run_nonce=run_nonce,
        environment=verified.environment, target=verified.target,
        plan_sha256=verified.plan_sha256,
        decision_sha256=verified.decision_sha256,
        derived_plan_sha256=verified.derived_execution_plan_sha256,
    )
    assert journal.inspect()["state"] == "HOLD"
