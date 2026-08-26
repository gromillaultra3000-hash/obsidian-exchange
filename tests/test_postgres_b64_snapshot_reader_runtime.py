import fcntl
import hashlib
import hmac
import importlib.util
import datetime as dt
import inspect
import os
import socket
import stat
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy/postgres/b64_snapshot_reader_runtime.py"
sys.path.insert(0, str(ROOT / "deploy/postgres"))
SPEC = importlib.util.spec_from_file_location(
    "b64_snapshot_reader_runtime", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_sealed_pgpass_memfds_are_independent_and_read_only():
    payload = (
        b"127.0.0.1:5432:obsidian_exchange:"
        b"obsidian_b64_snapshot_reader:synthetic-only\n"
    )
    first = MODULE._sealed_pgpass_memfd(payload, "runtime-unit-first")
    second = MODULE._sealed_pgpass_memfd(payload, "runtime-unit-second")
    try:
        first_stat = MODULE._validate_credential_fd(first)
        second_stat = MODULE._validate_credential_fd(second)
        assert (first_stat.st_dev, first_stat.st_ino) != \
            (second_stat.st_dev, second_stat.st_ino)
        assert stat.S_IMODE(first_stat.st_mode) == 0o600
        assert first_stat.st_nlink == 0
        assert fcntl.fcntl(first, fcntl.F_GET_SEALS) & \
            MODULE.REQUIRED_SEALS == MODULE.REQUIRED_SEALS
        with pytest.raises(OSError):
            os.write(first, b"x")
        assert os.read(first, 4096) == payload
        assert os.read(second, 4096) == payload
    finally:
        os.close(first)
        os.close(second)


def test_credential_owner_fd_must_be_cloexec():
    payload = (
        b"127.0.0.1:5432:obsidian_exchange:"
        b"obsidian_b64_snapshot_reader:synthetic-only\n"
    )
    fd = MODULE._sealed_pgpass_memfd(payload, "runtime-unit-cloexec")
    try:
        os.set_inheritable(fd, True)
        with pytest.raises(
            MODULE.RuntimeContractError, match="INVALID_CREDENTIAL_FD"
        ):
            MODULE._validate_credential_fd(fd)
        MODULE._validate_credential_fd(fd, require_cloexec=False)
    finally:
        os.close(fd)


def test_observation_dsn_rejects_inline_secret_and_accepts_sealed_fd():
    with pytest.raises(
        MODULE.RuntimeContractError,
        match="OBSERVATION_DSN_INLINE_SECRET_FORBIDDEN",
    ):
        MODULE._validate_observation_dsn_secret_boundary(
            "postgresql://observer:inline-secret@127.0.0.1:5432/"
            "obsidian_exchange"
        )
    with pytest.raises(
        MODULE.RuntimeContractError,
        match="OBSERVATION_PASSFILE_REQUIRED",
    ):
        MODULE._validate_observation_dsn_secret_boundary(
            "host=127.0.0.1 port=5432 dbname=obsidian_exchange "
            "user=observer"
        )
    fd = MODULE._sealed_pgpass_memfd(
        b"127.0.0.1:5432:obsidian_exchange:observer:synthetic-only\n",
        "runtime-unit-observation",
    )
    try:
        MODULE._validate_observation_dsn_secret_boundary(
            "host=127.0.0.1 port=5432 dbname=obsidian_exchange "
            f"user=observer passfile=/proc/self/fd/{fd}"
        )
    finally:
        os.close(fd)


@pytest.mark.parametrize("value", [
    "00000003-0000001B-1", "A:B-C", "0" * 128,
])
def test_exported_snapshot_token_is_closed(value):
    assert MODULE._snapshot(value) == value


@pytest.mark.parametrize("value", ["", "x", "a/b", "0" * 129])
def test_exported_snapshot_token_rejects_unbounded_values(value):
    with pytest.raises(MODULE.RuntimeContractError,
                       match="INVALID_EXPORTED_SNAPSHOT"):
        MODULE._snapshot(value)


def test_credential_ttl_is_short_and_integer_only():
    for value in (29, 181, 90.0, True):
        with pytest.raises(MODULE.RuntimeContractError,
                           match="INVALID_CREDENTIAL_TTL"):
            MODULE.issue_credential_lease(
                observation_dsn="unused", admin_dsn="unused",
                container="unused", expected_container_id="a" * 64,
                expected_image_id="sha256:" + "b" * 64,
                ttl_seconds=value,
            )


def test_production_login_activation_is_hard_disabled_before_contact(
        monkeypatch):
    monkeypatch.setattr(
        MODULE, "_inspect_container",
        lambda *args, **kwargs: pytest.fail("production was contacted"),
    )
    with pytest.raises(
        MODULE.RuntimeContractError,
        match="PRODUCTION_LOGIN_ACTIVATION_NOT_AUTHORIZED",
    ):
        MODULE.issue_credential_lease(
            observation_dsn="credential-bearing-observation-dsn",
            admin_dsn="credential-free-admin-dsn",
            container="obsidian-postgres",
            expected_container_id="a" * 64,
            expected_image_id="sha256:" + "b" * 64,
            ttl_seconds=90,
        )


def test_exact_binding_failure_stops_before_credential_issuance(monkeypatch):
    """A rejected observation DSN cannot reach ALTER ROLE issuance."""
    class Lock:
        closed = False

        def close(self):
            self.closed = True

    observed = []
    lock = Lock()
    passfile_fd = os.open("/dev/null", os.O_RDONLY)
    monkeypatch.setattr(
        MODULE, "_validate_observation_dsn_secret_boundary",
        lambda _dsn: None,
    )
    monkeypatch.setattr(
        MODULE, "_inspect_container",
        lambda *_args, **_kwargs: {"containerPid": 123},
    )
    monkeypatch.setattr(
        MODULE, "_validate_container_admin_dsn", lambda *_args: None,
    )
    monkeypatch.setattr(
        MODULE, "_bind_empty_memfd_passfile",
        lambda _dsn: (passfile_fd, "bound-admin-dsn"),
    )
    monkeypatch.setattr(
        MODULE, "_acquire_runtime_lock", lambda *_args: lock,
    )
    monkeypatch.setattr(
        MODULE, "_minimal_mutation_binding", lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        MODULE, "_role_auth_state_on",
        lambda _lock: {
            "login": False, "passwordAbsent": True,
            "sessions": 0, "validUntil": "",
        },
    )

    def reject_observation_dsn(**kwargs):
        observed.append(kwargs)
        raise MODULE.RuntimeContractError("OBSERVATION_DSN_READ_ONLY_REQUIRED")

    monkeypatch.setattr(MODULE, "_exact_runtime_binding", reject_observation_dsn)
    monkeypatch.setattr(
        MODULE, "_set_short_lived_verifier",
        lambda *_args: pytest.fail("credential issuance was reached"),
    )

    with pytest.raises(
        MODULE.RuntimeContractError,
        match="OBSERVATION_DSN_READ_ONLY_REQUIRED",
    ):
        MODULE.issue_credential_lease(
            observation_dsn="sealed-observation-dsn",
            admin_dsn="admin-dsn", container="b64-hba-contract-123",
            expected_container_id="a" * 64,
            expected_image_id="sha256:" + "b" * 64,
            allow_contract_container=True,
        )

    assert len(observed) == 1
    assert observed[0]["observation_dsn"] == "sealed-observation-dsn"
    assert observed[0]["expected_login"] is False
    assert lock.closed is True


def test_lease_repr_never_exposes_stored_dsns():
    lease = object.__new__(MODULE.CredentialLease)
    for field_name in MODULE.CredentialLease.__dataclass_fields__:
        setattr(lease, field_name, "synthetic-secret-dsn")
    rendered = repr(lease)
    assert "synthetic-secret-dsn" not in rendered
    assert rendered.startswith("<")


def test_scram_verifier_matches_postgresql_rfc_5803_shape():
    password = b"A" * 43
    salt = bytes(range(16))
    verifier = MODULE._scram_verifier(password, 4096, salt=salt)
    salted = hashlib.pbkdf2_hmac("sha256", password, salt, 4096)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    assert verifier == (
        "SCRAM-SHA-256$4096:AAECAwQFBgcICQoLDA0ODw==$"
        + __import__("base64").b64encode(stored_key).decode("ascii")
        + ":"
        + __import__("base64").b64encode(server_key).decode("ascii")
    )


@pytest.mark.parametrize("iterations", [1, 4095, 1_000_001, True])
def test_scram_verifier_rejects_unsafe_iteration_policy(iterations):
    with pytest.raises(MODULE.RuntimeContractError,
                       match="UNSAFE_SCRAM_ITERATIONS"):
        MODULE._scram_verifier(b"A" * 43, iterations)


def test_runtime_source_has_no_secret_environment_or_receipt_path():
    source = MODULE_PATH.read_text("utf-8")
    assert "_reject_ambient_libpq_environment" in source
    assert "password.decode" not in source
    assert "_set_short_lived_verifier" in source
    assert 'require_auth="scram-sha-256"' in source
    assert "credentialExposed\": False" in source
    assert "MFD_ALLOW_SEALING" in source
    assert "F_SEAL_WRITE" in source
    assert "PASSWORD NULL" in source
    assert "NOLOGIN" in source
    assert "log_min_error_statement='panic'" in source
    assert "ABANDONED_LEASE_REVOKED_VERIFIED" in source
    assert "ACTIVE_SESSIONS_PREVENT_CREDENTIAL_RECONCILE" not in source
    assert "pg_terminate_backend" in source
    assert "pg_try_advisory_lock" in source
    assert "transaction_timeout" in source
    assert "sys.stdin.readline" not in source
    assert "_load_and_bind_plan" in source
    assert "target_session_attrs=\"read-write\"" not in source
    assert "pg_export_snapshot" in source
    assert "SET TRANSACTION SNAPSHOT" in source
    assert "customerRowsRead\": False" in source


def test_helper_error_receipt_never_contains_exception_text(
        monkeypatch, capsys):
    for name in tuple(os.environ):
        if name.startswith("PG"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(sys, "argv", [
        "b64_snapshot_reader_runtime.py", "--import-helper",
        "--credential-fd", "999999", "--expires-at",
        "2026-08-23T00:00:00+00:00", "--snapshot",
        "00000003-0000001B-1", "--lease-nonce", "a" * 32,
        "--expected-netns-inode", str(os.stat("/proc/self/ns/net").st_ino),
        "--expected-system-identifier", "1234567890123456789",
    ])
    assert MODULE.main() == 2
    output = capsys.readouterr().out
    assert "INVALID_CREDENTIAL_FD" in output
    assert "999999" not in output
    assert "credentialExposed" in output


def test_helper_rejects_ambient_libpq_environment(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "synthetic-never-used")
    with pytest.raises(MODULE.RuntimeContractError,
                       match="AMBIENT_LIBPQ_ENVIRONMENT_FORBIDDEN"):
        MODULE._helper_connection(
            999999, "a" * 32, os.stat("/proc/self/ns/net").st_ino,
            "1234567890123456789", "import",
        )


def test_partial_close_command_cannot_block_past_deadline(monkeypatch):
    read_fd, write_fd = os.pipe()
    client, peer = socket.socketpair()

    class StdinFd:
        def fileno(self):
            return read_fd

    class ConnectionFd:
        def fileno(self):
            return client.fileno()

    monkeypatch.setattr(sys, "stdin", StdinFd())
    try:
        os.write(write_fd, b"C")
        started = time.monotonic()
        with pytest.raises(MODULE.RuntimeContractError,
                           match="EXPORT_LEASE_DEADLINE_EXPIRED"):
            MODULE._wait_for_export_close(
                ConnectionFd(), time.monotonic() + 0.05
            )
        assert time.monotonic() - started < 0.5
    finally:
        os.close(read_fd)
        os.close(write_fd)
        client.close()
        peer.close()


def test_runtime_lock_deadline_is_one_atomic_server_statement():
    class Cursor:
        def fetchone(self):
            return ("1000ms", 1000)

    class Connection:
        def __init__(self):
            self.queries = []

        def execute(self, query):
            self.queries.append(query)
            return Cursor()

    conn = Connection()
    MODULE._arm_runtime_lock_deadline(
        conn, dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)
    )
    assert len(conn.queries) == 1
    statement = conn.queries[0].as_string(None)
    assert "clock_timestamp()" in statement
    assert "set_config('idle_session_timeout'" in statement
    assert "WITH obsidian_deadline AS MATERIALIZED" in statement


def test_scram_verifier_query_is_built_only_after_log_suppression():
    acquire_source = inspect.getsource(MODULE._acquire_runtime_lock)
    verifier_source = inspect.getsource(MODULE._set_short_lived_verifier)
    for setting in (
        "log_statement='none'",
        "log_min_duration_statement=-1",
        "log_min_error_statement='panic'",
    ):
        assert setting in acquire_source
        assert setting not in verifier_source
    assert "ALTER ROLE" in verifier_source
    assert "_execute_commands_with_deadline" in verifier_source
