import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

import deploy_b64_snapshot_reader as module


NONCE = "a" * 32
ADMIN_DSN = (
    "host=/proc/12345/root/var/run/postgresql "
    "dbname=obsidian_exchange user=postgres port=5432 connect_timeout=5 "
    "sslmode=disable target_session_attrs=read-write"
)
CONTAINER = {
    "containerId": "b" * 64,
    "imageId": "sha256:" + "c" * 64,
    "status": "running",
    "health": "healthy",
    "hostPort": 5432,
    "containerPid": 12345,
}


def _prepare(monkeypatch):
    monkeypatch.setenv("EXCHANGE_DATABASE_URL", "synthetic-dsn")
    monkeypatch.setenv("B64_LOCAL_ADMIN_DSN", ADMIN_DSN)
    monkeypatch.setattr(module.secrets, "token_hex", lambda _size: NONCE)
    monkeypatch.setattr(module, "_load_and_bind_plan", lambda: {})
    monkeypatch.setattr(module, "_inspect_container", lambda *args: dict(CONTAINER))
    monkeypatch.setattr(module, "_catalog_preflight", lambda *args: {
        "roleAbsent": True,
    })
    monkeypatch.setattr(module, "_admin_preflight", lambda *args: {
        "currentUser": "postgres",
        "database": "obsidian_exchange",
        "superuser": True,
        "createRole": True,
        "transactionReadOnly": False,
        "unixSocketTransport": True,
    })
    monkeypatch.setattr(sys, "argv", [
        "deploy_b64_snapshot_reader.py",
        "--admin-postgres-env", "B64_LOCAL_ADMIN_DSN",
        "--expected-database", "obsidian_exchange",
        "--container", "obsidian-postgres",
        "--expected-container-id", "b" * 64,
        "--expected-image-id", "sha256:" + "c" * 64,
        "--require-role-absent", "--apply",
    ])


def _report(capsys):
    return json.loads(capsys.readouterr().out)


def test_ambiguous_commit_is_reconciled_and_rolled_back(
        monkeypatch, capsys):
    _prepare(monkeypatch)
    calls = []

    def execute(_dsn, _database, path, **_kwargs):
        calls.append(path.name)
        if path == module.PROVISION_PATH:
            raise OSError("synthetic lost acknowledgement")

    role_states = iter((True, False))
    monkeypatch.setattr(module, "_execute_bound_sql", execute)
    monkeypatch.setattr(module, "_role_exists", lambda _dsn: next(role_states))
    monkeypatch.setattr(module, "inspect", lambda _dsn: {
        "deploymentNonce": NONCE,
    })
    assert module.main() == 2
    report = _report(capsys)
    assert report["status"] == "FAILED_ROLLED_BACK"
    assert report["rollbackAttempted"] is True
    assert report["rollbackVerified"] is True
    assert calls == [module.PROVISION_PATH.name, module.ROLLBACK_PATH.name]


def test_changed_container_forbids_compensating_mutation(monkeypatch, capsys):
    _prepare(monkeypatch)
    inspections = 0

    def inspect_container(*_args):
        nonlocal inspections
        inspections += 1
        if inspections == 1:
            return dict(CONTAINER)
        raise module.DeploymentError("CONTAINER_IDENTITY_MISMATCH")

    mutations = []
    monkeypatch.setattr(module, "_inspect_container", inspect_container)
    monkeypatch.setattr(
        module, "_execute_bound_sql",
        lambda *_args, **_kwargs: (
            mutations.append("apply"),
            (_ for _ in ()).throw(OSError("synthetic disconnect")),
        )[-1],
    )
    assert module.main() == 2
    report = _report(capsys)
    assert report["status"] == "ROLLBACK_UNCERTAIN"
    assert report["compensationState"] == "TARGET_OR_STATE_UNCONFIRMED"
    assert mutations == ["apply"]


def test_failed_role_probe_returns_bounded_unknown_receipt(monkeypatch, capsys):
    _prepare(monkeypatch)
    monkeypatch.setattr(
        module, "_execute_bound_sql",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("lost ack")),
    )
    monkeypatch.setattr(
        module, "_role_exists",
        lambda _dsn: (_ for _ in ()).throw(OSError("reconnect failed")),
    )
    assert module.main() == 2
    report = _report(capsys)
    assert report["status"] == "ROLLBACK_UNCERTAIN"
    assert report["rollbackAttempted"] is False
    assert report["rollbackVerified"] is False


def test_post_commit_verifier_failure_rolls_back(monkeypatch, capsys):
    _prepare(monkeypatch)
    calls = []

    def execute(_dsn, _database, path, **_kwargs):
        calls.append(path.name)

    inspections = iter((
        {"status": "mismatch"},
        {"deploymentNonce": NONCE},
    ))
    role_states = iter((True, False))
    monkeypatch.setattr(module, "_execute_bound_sql", execute)
    monkeypatch.setattr(module, "inspect", lambda _dsn: next(inspections))
    monkeypatch.setattr(module, "_role_exists", lambda _dsn: next(role_states))
    assert module.main() == 2
    report = _report(capsys)
    assert report["reason"] == "POST_APPLY_VERIFICATION_FAILED"
    assert report["status"] == "FAILED_ROLLED_BACK"
    assert calls == [module.PROVISION_PATH.name, module.ROLLBACK_PATH.name]


def test_admin_authority_failure_precedes_apply(monkeypatch, capsys):
    _prepare(monkeypatch)
    mutations = []
    monkeypatch.setattr(
        module, "_admin_preflight",
        lambda *_args: (_ for _ in ()).throw(
            module.DeploymentError("ADMIN_AUTHORITY_INSUFFICIENT")
        ),
    )
    monkeypatch.setattr(
        module, "_execute_bound_sql",
        lambda *_args, **_kwargs: mutations.append("unexpected"),
    )
    assert module.main() == 2
    report = _report(capsys)
    assert report["reason"] == "ADMIN_AUTHORITY_INSUFFICIENT"
    assert report["status"] == "FAILED"
    assert report["rollbackAttempted"] is False
    assert mutations == []


def test_container_admin_dsn_is_secretless_and_pid_bound():
    pid = 12345
    dsn = ADMIN_DSN
    module._validate_container_admin_dsn(dsn, "obsidian_exchange", pid)
    with pytest.raises(module.DeploymentError,
                       match="ADMIN_DSN_NOT_BOUND_TO_CONTAINER_SOCKET"):
        module._validate_container_admin_dsn(
            dsn.replace("12345", "12346"), "obsidian_exchange", pid
        )
    with pytest.raises(module.DeploymentError,
                       match="ADMIN_DSN_CREDENTIAL_FORBIDDEN"):
        module._validate_container_admin_dsn(
            dsn + " password=forbidden", "obsidian_exchange", pid
        )


def test_apply_requires_separate_admin_channel(monkeypatch, capsys):
    _prepare(monkeypatch)
    monkeypatch.delenv("B64_LOCAL_ADMIN_DSN")
    sys.argv.remove("--admin-postgres-env")
    sys.argv.remove("B64_LOCAL_ADMIN_DSN")
    assert module.main() == 2
    report = _report(capsys)
    assert report["reason"] == "ADMIN_POSTGRES_ENV_REQUIRED_FOR_APPLY"
    assert report["rollbackAttempted"] is False


def test_container_admin_dsn_rejects_ambient_libpq(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "forbidden")
    with pytest.raises(module.DeploymentError,
                       match="AMBIENT_LIBPQ_ENV_FORBIDDEN"):
        module._validate_container_admin_dsn(
            ADMIN_DSN, "obsidian_exchange", 12345
        )
