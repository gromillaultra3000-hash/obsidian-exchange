"""Disposable two-connection credential lease and exported-snapshot test."""
import atexit
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

import b64_snapshot_reader_runtime as runtime
import b64_064a_hardened_refresh as refresh

issue_credential_lease = runtime.issue_credential_lease
reconcile_credential = runtime.reconcile_credential
from migration_profile import selected_paths
from verify_b64_snapshot_reader import inspect


ROLE = "obsidian_b64_snapshot_reader"
CONTAINER = os.environ["TEST_POSTGRES_CONTAINER"]
DSN = os.environ["TEST_POSTGRES_DSN"]
NONCE = "1234567890abcdef1234567890abcdef"


def execute_bound(conn, path: Path):
    conn.execute(sql.SQL(
        "SET obsidian.snapshot_reader_expected_database = {}"
    ).format(sql.Literal("obsidian_exchange")))
    conn.execute("SET obsidian.snapshot_reader_require_absent = 'on'")
    conn.execute(sql.SQL(
        "SET obsidian.snapshot_reader_deployment_nonce = {}"
    ).format(sql.Literal(NONCE)))
    conn.execute(path.read_text("utf-8"))


container = json.loads(subprocess.run(
    ["docker", "inspect", CONTAINER], check=True,
    capture_output=True, text=True,
).stdout)[0]
container_id = container["Id"].removeprefix("sha256:")
container_pid = container["State"]["Pid"]
image_id = container["Image"]
admin_dsn = make_conninfo(
    host=f"/proc/{container_pid}/root/var/run/postgresql",
    dbname="obsidian_exchange", user="postgres", port=5432,
    connect_timeout=5, sslmode="disable",
    target_session_attrs="read-write",
)

with psycopg.connect(DSN, autocommit=True) as conn:
    conn.execute((POSTGRES / "bootstrap_roles.sql").read_text("utf-8"))
with psycopg.connect(DSN) as conn:
    conn.execute((POSTGRES / "prepare_database.sql").read_text("utf-8"))
with psycopg.connect(DSN) as conn:
    conn.execute("SET ROLE obsidian_migrator")
    for migration in selected_paths(ROOT, "production-cutover"):
        conn.execute(migration.read_text("utf-8"))
with psycopg.connect(DSN, autocommit=True) as conn:
    conn.execute((POSTGRES / "runtime_privileges.sql").read_text("utf-8"))
    execute_bound(conn, POSTGRES / "provision_b64_snapshot_reader.sql")

# The retained production-original HBA requires SCRAM even for the disposable
# cluster's loopback observation DSN.  Give only the disposable postgres role a
# random verifier, then convey it to this process and its exact HBA subprocesses
# through a sealed anonymous passfile FD.  The password never enters argv, a
# DSN, a filesystem path, or a subprocess environment value; the observation
# DSN contains only the non-secret /proc/self/fd reference.
observation_password = secrets.token_urlsafe(48)
with psycopg.connect(DSN, autocommit=True) as conn:
    conn.execute(sql.SQL("ALTER ROLE postgres PASSWORD {}").format(
        sql.Literal(observation_password)
    ))
observation_port = conninfo_to_dict(DSN)["port"]
observation_passfile_fd = runtime._sealed_pgpass_memfd(
    (
        f"127.0.0.1:{observation_port}:obsidian_exchange:postgres:"
        f"{observation_password}\n"
    ).encode("utf-8"),
    "b64-contract-observation-pgpass",
)
observation_password = ""
DSN = make_conninfo(
    DSN, passfile=f"/proc/self/fd/{observation_passfile_fd}"
)

original_hba = os.environ.get("TEST_POSTGRES_ORIGINAL_HBA")
if original_hba:
    original_bytes = Path(original_hba).read_bytes()
    assert hashlib.sha256(original_bytes).hexdigest() == \
        "45b68cd420caab6d19725857c309871880a66a4c195bcd7e1604e7c334b6be82"
    copied = subprocess.run(
        ["docker", "cp", original_hba,
         f"{CONTAINER}:/var/lib/postgresql/data/pg_hba.conf"],
        check=False, capture_output=True, text=True,
    )
    assert copied.returncode == 0, (copied.stdout, copied.stderr)
    subprocess.run(
        ["docker", "exec", "-u", "0", CONTAINER, "chown", "70:70",
         "/var/lib/postgresql/data/pg_hba.conf"], check=True,
        capture_output=True, text=True,
    )
    subprocess.run(
        ["docker", "exec", "-u", "0", CONTAINER, "chmod", "0600",
         "/var/lib/postgresql/data/pg_hba.conf"], check=True,
        capture_output=True, text=True,
    )
    with psycopg.connect(DSN, autocommit=True) as conn:
        assert conn.execute("SELECT pg_reload_conf()").fetchone()[0] is True

environment = dict(os.environ)
environment["EXCHANGE_DATABASE_URL"] = DSN
environment["B64_LOCAL_ADMIN_DSN"] = admin_dsn
hba_command = [
    sys.executable, str(POSTGRES / "deploy_b64_snapshot_reader_hba.py"),
    "--postgres-env", "EXCHANGE_DATABASE_URL",
    "--admin-postgres-env", "B64_LOCAL_ADMIN_DSN",
    "--container", CONTAINER,
    "--expected-container-id", container_id,
    "--expected-image-id", image_id,
    "--allow-contract-container",
]
hba_apply = subprocess.run(
    hba_command + ["--apply"], env=environment, check=False,
    capture_output=True, text=True,
    pass_fds=(observation_passfile_fd,),
)
assert hba_apply.returncode == 0, (hba_apply.stdout, hba_apply.stderr)
assert json.loads(hba_apply.stdout)["status"] == \
    "HBA_DEPLOYED_PARSED_DORMANT"

lease = None
source_adapter = None
exporter = None
cleanup_needed = True


def emergency_cleanup():
    if not cleanup_needed:
        return
    if exporter is not None and exporter.poll() is None:
        try:
            assert exporter.stdin is not None
            exporter.stdin.write("CLOSE\n")
            exporter.stdin.flush()
            exporter.communicate(timeout=5)
        except Exception:
            exporter.kill()
    if lease is not None:
        try:
            if source_adapter is not None:
                source_adapter.close()
            else:
                lease.close()
        except Exception:
            pass
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL(
                "ALTER ROLE {} NOLOGIN PASSWORD NULL VALID UNTIL 'infinity'"
            ).format(sql.Identifier(ROLE)))
        subprocess.run(
            hba_command + ["--reconcile"], env=environment, check=False,
            capture_output=True, text=True,
            pass_fds=(observation_passfile_fd,),
        )
    except Exception:
        pass


atexit.register(emergency_cleanup)

lease = issue_credential_lease(
    observation_dsn=DSN, admin_dsn=admin_dsn,
    container=CONTAINER, expected_container_id=container_id,
    expected_image_id=image_id, ttl_seconds=120,
    allow_contract_container=True,
)
assert lease.source_fd != lease.dump_fd
assert inspect(admin_dsn, expected_login=True)["status"] == "match"

helper_environment = {
    "PATH": "/usr/bin:/bin",
    "PYTHONPATH": "/usr/lib/python3/dist-packages",
    "LC_ALL": "C",
}
helper_base = [
    "nsenter", "--target", str(container_pid), "--net",
    "/opt/lumi/venv/bin/python",
    str(POSTGRES / "b64_snapshot_reader_runtime.py"),
]
expiry = lease.expires_at.isoformat()
helper_binding = [
    "--lease-nonce", lease.lease_nonce,
    "--expected-netns-inode", str(lease.source_netns_inode),
    "--expected-system-identifier", lease.system_identifier,
]
frozen_plan = json.loads((
    ROOT / "docs/e0-3-bot-b5-3-064a-hardened-refresh-plan.v1.json"
).read_text("utf-8"))
source_adapter = runtime.ProductionSourceAdapter(lease)
source_fd = os.dup(lease.source_fd)
try:
    source_attestation, exported_snapshot = source_adapter.open(
        frozen_plan, source_fd, time.monotonic() + 120,
    )
finally:
    os.close(source_fd)
assert refresh.validate_source_attestation(source_attestation) == \
    source_attestation
assert source_attestation["credentialNotAfterEpoch"] == int(
    lease.expires_at.timestamp()
)
remaining_ms = int(
    (lease.expires_at.timestamp() - time.time() - 5) * 1000
)
assert 1 <= remaining_ms <= 180_000
dump_command = refresh.compile_dump_command(
    frozen_plan, exported_snapshot, container_id,
    transaction_timeout_ms=remaining_ms,
    lease_not_after_epoch=source_attestation["credentialNotAfterEpoch"],
)
with tempfile.TemporaryFile() as archive:
    os.lseek(lease.dump_fd, 0, os.SEEK_SET)
    dumped = subprocess.run(
        dump_command, stdin=lease.dump_fd, stdout=archive,
        stderr=subprocess.PIPE, check=False,
        timeout=max(1.0, lease.expires_at.timestamp() - time.time() + 10),
    )
    assert dumped.returncode == 0, dumped.stderr.decode("utf-8", "replace")
    assert dumped.stderr == b""
    assert archive.tell() > 0
    archive.seek(0)
    listed = subprocess.run(
        [
            "docker", "run", "-i", "--rm", "--pull=never",
            "--platform=linux/amd64", "--network=none", "--read-only",
            "--user=70:70", "--cap-drop=ALL",
            "--security-opt=no-new-privileges=true", "--pids-limit=32",
            "--memory=128m", "--cpus=1", refresh.IMAGE_REF,
            "pg_restore", "--list",
        ],
        stdin=archive, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    assert listed.returncode == 0, listed.stderr.decode("utf-8", "replace")
    assert b"TABLE DATA public orders" in listed.stdout

stale_fd = os.dup(lease.dump_fd)
try:
    revoked = source_adapter.close()
    assert revoked == {
        "sourceSessionClosed": True,
        "credentialRevocationAttested": True,
        "loginState": "DISABLED",
        "credentialState": "ABSENT",
        "activeSessions": 0,
    }
    source_adapter = None
    assert inspect(admin_dsn)["status"] == "match"
    denied = subprocess.run(
        helper_base + [
            "--import-helper", "--credential-fd", str(stale_fd),
            "--expires-at", expiry, "--snapshot", exported_snapshot,
        ] + helper_binding,
        check=False, capture_output=True, text=True,
        pass_fds=(stale_fd,), env=helper_environment,
    )
    assert denied.returncode == 2
    denial = json.loads(denied.stdout)
    assert denial["status"] == "ERROR"
    assert denial["credentialExposed"] is False
    assert denial["customerRowsRead"] is False
finally:
    os.close(stale_fd)

# Model a supervisor/issuer death with an active exporter.  The advisory-lock
# session and all inherited descriptors disappear; fresh reconcile must first
# disable authentication, then terminate the dedicated-role backend.
orphaned = issue_credential_lease(
    observation_dsn=DSN, admin_dsn=admin_dsn,
    container=CONTAINER, expected_container_id=container_id,
    expected_image_id=image_id, ttl_seconds=60,
    allow_contract_container=True,
)
orphaned_expiry = orphaned.expires_at.isoformat()
orphaned_binding = [
    "--lease-nonce", orphaned.lease_nonce,
    "--expected-netns-inode", str(orphaned.source_netns_inode),
    "--expected-system-identifier", orphaned.system_identifier,
]
orphaned_exporter = subprocess.Popen(
    helper_base + [
        "--export-helper", "--credential-fd", str(orphaned.source_fd),
        "--expires-at", orphaned_expiry,
    ] + orphaned_binding,
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, pass_fds=(orphaned.source_fd,), env=helper_environment,
)
exporter = orphaned_exporter
assert orphaned_exporter.stdout is not None
orphaned_export = json.loads(orphaned_exporter.stdout.readline())
assert orphaned_export["status"] == "SNAPSHOT_EXPORTED_HELD"
for name in ("source_fd", "dump_fd", "_admin_passfile_fd"):
    os.close(getattr(orphaned, name))
    setattr(orphaned, name, -1)
orphaned._lock_conn.close()
orphaned._lock_conn = None
recovered = reconcile_credential(
    observation_dsn=DSN, admin_dsn=admin_dsn,
    container=CONTAINER, expected_container_id=container_id,
    expected_image_id=image_id, allow_contract_container=True,
)
assert recovered == {
    "activeSessions": 0,
    "credentialState": "ABSENT",
    "customerRowsRead": False,
    "loginState": "DISABLED",
    "status": "ABANDONED_LEASE_REVOKED_VERIFIED",
}
orphaned_stdout, orphaned_stderr = orphaned_exporter.communicate(timeout=10)
assert orphaned_exporter.returncode == 2, (
    orphaned_stdout, orphaned_stderr
)
terminated = json.loads(orphaned_stdout)
assert terminated["reason"] == "EXPORT_SESSION_TERMINATED"
exporter = None
assert reconcile_credential(
    observation_dsn=DSN, admin_dsn=admin_dsn,
    container=CONTAINER, expected_container_id=container_id,
    expected_image_id=image_id, allow_contract_container=True,
)["status"] == "ALREADY_DORMANT_VERIFIED"

# A first recovery process can itself die or freeze before revoke.  Its
# reconcile-specific lock deadline is short and absolute, so a second recovery
# process takes over and removes both the credential and arbitrary sessions.
runtime.MIN_TTL_SECONDS = 2
original_reconcile_cleanup_seconds = runtime.RECONCILE_CLEANUP_SECONDS
runtime.RECONCILE_CLEANUP_SECONDS = 2
stalled_lease = None
stalled_session = None
original_minimal_binding = runtime._minimal_mutation_binding
stalled_errors = []
try:
    stalled_lease = issue_credential_lease(
        observation_dsn=DSN, admin_dsn=admin_dsn,
        container=CONTAINER, expected_container_id=container_id,
        expected_image_id=image_id, ttl_seconds=8,
        allow_contract_container=True,
    )
    lease = stalled_lease
    stalled_code = (
        "import sys,psycopg;"
        "from psycopg.conninfo import make_conninfo;"
        "fd=int(sys.argv[1]);"
        "dsn=make_conninfo(host='127.0.0.1',port=5432,"
        "dbname='obsidian_exchange',user='obsidian_b64_snapshot_reader',"
        "passfile=f'/proc/self/fd/{fd}',sslmode='disable',"
        "require_auth='scram-sha-256',application_name='stalled-reconcile');"
        "conn=psycopg.connect(dsn,autocommit=True,connect_timeout=5);"
        "print('CONNECTED',flush=True);conn.execute('SELECT pg_sleep(20)')"
    )
    stalled_session = subprocess.Popen(
        [
            "nsenter", "--target", str(container_pid), "--net",
            "/opt/lumi/venv/bin/python", "-c", stalled_code,
            str(stalled_lease.dump_fd),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        pass_fds=(stalled_lease.dump_fd,), env=helper_environment,
    )
    assert stalled_session.stdout is not None
    assert stalled_session.stdout.readline().strip() == "CONNECTED"
    for name in ("source_fd", "dump_fd", "_admin_passfile_fd"):
        os.close(getattr(stalled_lease, name))
        setattr(stalled_lease, name, -1)
    stalled_lease._lock_conn.close()
    stalled_lease._lock_conn = None

    first_recovery_holds_lock = threading.Event()

    def stall_first_recovery(*args, **kwargs):
        if threading.current_thread().name == "stalled-reconcile":
            first_recovery_holds_lock.set()
            time.sleep(3)
        return original_minimal_binding(*args, **kwargs)

    runtime._minimal_mutation_binding = stall_first_recovery

    def run_stalled_recovery():
        try:
            reconcile_credential(
                observation_dsn=DSN, admin_dsn=admin_dsn,
                container=CONTAINER, expected_container_id=container_id,
                expected_image_id=image_id, allow_contract_container=True,
            )
        except BaseException as exc:
            stalled_errors.append(exc)

    stalled_thread = threading.Thread(
        target=run_stalled_recovery, name="stalled-reconcile"
    )
    stalled_thread.start()
    assert first_recovery_holds_lock.wait(timeout=5)
    runtime._minimal_mutation_binding = original_minimal_binding
    try:
        reconcile_credential(
            observation_dsn=DSN, admin_dsn=admin_dsn,
            container=CONTAINER, expected_container_id=container_id,
            expected_image_id=image_id, allow_contract_container=True,
        )
        raise AssertionError("second recovery bypassed live recovery lock")
    except runtime.RuntimeContractError as exc:
        assert str(exc) == "CREDENTIAL_RUNTIME_BUSY"
    time.sleep(2.3)
    takeover = reconcile_credential(
        observation_dsn=DSN, admin_dsn=admin_dsn,
        container=CONTAINER, expected_container_id=container_id,
        expected_image_id=image_id, allow_contract_container=True,
    )
    assert takeover["status"] == "ABANDONED_LEASE_REVOKED_VERIFIED"
    stalled_thread.join(timeout=5)
    assert not stalled_thread.is_alive()
    assert stalled_errors
    assert inspect(admin_dsn)["credentialState"] == "ABSENT"
    assert runtime._role_auth_state(admin_dsn)["sessions"] == 0
finally:
    runtime._minimal_mutation_binding = original_minimal_binding
    runtime.RECONCILE_CLEANUP_SECONDS = original_reconcile_cleanup_seconds
    runtime.MIN_TTL_SECONDS = 30
    if stalled_session is not None and stalled_session.poll() is None:
        stalled_session.terminate()
        stalled_session.communicate(timeout=5)
    if stalled_lease is not None:
        for name in ("source_fd", "dump_fd", "_admin_passfile_fd"):
            fd = getattr(stalled_lease, name)
            if fd >= 0:
                os.close(fd)
                setattr(stalled_lease, name, -1)
        if stalled_lease._lock_conn is not None:
            stalled_lease._lock_conn.close()
            stalled_lease._lock_conn = None
lease = None

# Model an ALTER ROLE commit followed by lost acknowledgement.  Compensation
# must observe/revoke through fresh connections and close every secret FD.
original_set_verifier = runtime._set_short_lived_verifier
fd_count_before = len(os.listdir("/proc/self/fd"))


def committed_issue_then_lost_ack(*args, **kwargs):
    original_set_verifier(*args, **kwargs)
    raise ConnectionError("synthetic ack loss; must never escape")


runtime._set_short_lived_verifier = committed_issue_then_lost_ack
try:
    try:
        issue_credential_lease(
            observation_dsn=DSN, admin_dsn=admin_dsn,
            container=CONTAINER, expected_container_id=container_id,
            expected_image_id=image_id, ttl_seconds=30,
            allow_contract_container=True,
        )
        raise AssertionError("ambiguous issuance unexpectedly succeeded")
    except runtime.RuntimeContractError as exc:
        assert str(exc) == "LEASE_ISSUE_FAILED_REVOKED"
finally:
    runtime._set_short_lived_verifier = original_set_verifier
assert len(os.listdir("/proc/self/fd")) == fd_count_before
assert inspect(admin_dsn)["credentialState"] == "ABSENT"

# Model a committed revoke followed by lost acknowledgement.  Fresh state
# observation must turn the ambiguous outcome into a verified closed status.
ambiguous_revoke_lease = issue_credential_lease(
    observation_dsn=DSN, admin_dsn=admin_dsn,
    container=CONTAINER, expected_container_id=container_id,
    expected_image_id=image_id, ttl_seconds=30,
    allow_contract_container=True,
)
lease = ambiguous_revoke_lease
try:
    reconcile_credential(
        observation_dsn=DSN, admin_dsn=admin_dsn,
        container=CONTAINER, expected_container_id=container_id,
        expected_image_id=image_id, allow_contract_container=True,
    )
    raise AssertionError("concurrent reconcile unexpectedly acquired lock")
except runtime.RuntimeContractError as exc:
    assert str(exc) == "CREDENTIAL_RUNTIME_BUSY"

original_revoke = runtime._revoke


def committed_revoke_then_lost_ack(*args, **kwargs):
    original_revoke(*args, **kwargs)
    raise ConnectionError("synthetic revoke ack loss; must never escape")


runtime._revoke = committed_revoke_then_lost_ack
try:
    ambiguous_result = ambiguous_revoke_lease.close()
finally:
    runtime._revoke = original_revoke
assert ambiguous_result["status"] == \
    "REVOKED_AFTER_AMBIGUOUS_ACK_VERIFIED"
assert inspect(admin_dsn)["credentialState"] == "ABSENT"

# Mutable health drift plus supervisor death must never block authority
# reduction.  Fresh reconcile ignores health for its minimal target,
# revokes/terminates first, then reports the broad post-verification drift.
health_drift_lease = issue_credential_lease(
    observation_dsn=DSN, admin_dsn=admin_dsn,
    container=CONTAINER, expected_container_id=container_id,
    expected_image_id=image_id, ttl_seconds=30,
    allow_contract_container=True,
)
lease = health_drift_lease
subprocess.run(
    ["docker", "exec", CONTAINER, "touch", "/tmp/force-unhealthy"],
    check=True, capture_output=True, text=True,
)
for _attempt in range(400):
    health = json.loads(subprocess.run(
        ["docker", "inspect", CONTAINER], check=True,
        capture_output=True, text=True,
    ).stdout)[0]["State"]["Health"]["Status"]
    if health == "unhealthy":
        break
    time.sleep(0.1)
assert health == "unhealthy"
for name in ("source_fd", "dump_fd", "_admin_passfile_fd"):
    os.close(getattr(health_drift_lease, name))
    setattr(health_drift_lease, name, -1)
health_drift_lease._lock_conn.close()
health_drift_lease._lock_conn = None
try:
    reconcile_credential(
        observation_dsn=DSN, admin_dsn=admin_dsn,
        container=CONTAINER, expected_container_id=container_id,
        expected_image_id=image_id, allow_contract_container=True,
    )
    raise AssertionError("health drift unexpectedly passed full postverify")
except runtime.RuntimeContractError as exc:
    assert str(exc) == "CREDENTIAL_REVOKED_POSTVERIFY_DRIFT"
assert inspect(admin_dsn)["credentialState"] == "ABSENT"
assert runtime._role_auth_state(admin_dsn)["sessions"] == 0
subprocess.run(
    ["docker", "exec", CONTAINER, "rm", "/tmp/force-unhealthy"],
    check=True, capture_output=True, text=True,
)
for _attempt in range(30):
    health = json.loads(subprocess.run(
        ["docker", "inspect", CONTAINER], check=True,
        capture_output=True, text=True,
    ).stdout)[0]["State"]["Health"]["Status"]
    if health == "healthy":
        break
    time.sleep(0.1)
assert health == "healthy"
lease = None

# A late lock-backend query must re-arm only the residual absolute lease time,
# never the original relative timeout.  Then a hung supervisor cannot retain
# the advisory lock beyond expires_at, and fresh reconcile terminates even a
# deliberately non-helper role session.
runtime.MIN_TTL_SECONDS = 2
expired_lock_lease = None
arbitrary_session = None
try:
    expired_lock_lease = issue_credential_lease(
        observation_dsn=DSN, admin_dsn=admin_dsn,
        container=CONTAINER, expected_container_id=container_id,
        expected_image_id=image_id, ttl_seconds=3,
        allow_contract_container=True,
    )
    lease = expired_lock_lease
    arbitrary_code = (
        "import sys,time,psycopg;"
        "from psycopg.conninfo import make_conninfo;"
        "fd=int(sys.argv[1]);"
        "dsn=make_conninfo(host='127.0.0.1',port=5432,"
        "dbname='obsidian_exchange',user='obsidian_b64_snapshot_reader',"
        "passfile=f'/proc/self/fd/{fd}',sslmode='disable',"
        "require_auth='scram-sha-256',application_name='synthetic-arbitrary');"
        "conn=psycopg.connect(dsn,autocommit=True,connect_timeout=5);"
        "print('CONNECTED',flush=True);time.sleep(20)"
    )
    arbitrary_session = subprocess.Popen(
        [
            "nsenter", "--target", str(container_pid), "--net",
            "/opt/lumi/venv/bin/python", "-c", arbitrary_code,
            str(expired_lock_lease.dump_fd),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        pass_fds=(expired_lock_lease.dump_fd,), env=helper_environment,
    )
    assert arbitrary_session.stdout is not None
    assert arbitrary_session.stdout.readline().strip() == "CONNECTED"
    late_delay = expired_lock_lease.expires_at.timestamp() \
        - time.time() - 1.0
    if late_delay > 0:
        time.sleep(late_delay)
    runtime._assert_runtime_lock(
        expired_lock_lease._lock_conn, expired_lock_lease.expires_at
    )
    past_expiry_delay = expired_lock_lease.expires_at.timestamp() \
        - time.time() + 0.5
    if past_expiry_delay > 0:
        time.sleep(past_expiry_delay)
    expired_reconcile = reconcile_credential(
        observation_dsn=DSN, admin_dsn=admin_dsn,
        container=CONTAINER, expected_container_id=container_id,
        expected_image_id=image_id, allow_contract_container=True,
    )
    assert expired_reconcile["status"] == \
        "ABANDONED_LEASE_REVOKED_VERIFIED"
    with psycopg.connect(admin_dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE usename=%s",
            (ROLE,),
        ).fetchone()[0] == 0
finally:
    runtime.MIN_TTL_SECONDS = 30
    if arbitrary_session is not None and arbitrary_session.poll() is None:
        arbitrary_session.terminate()
        arbitrary_session.communicate(timeout=5)
    if expired_lock_lease is not None:
        for name in ("source_fd", "dump_fd", "_admin_passfile_fd"):
            fd = getattr(expired_lock_lease, name)
            if fd >= 0:
                os.close(fd)
                setattr(expired_lock_lease, name, -1)
        if expired_lock_lease._lock_conn is not None:
            expired_lock_lease._lock_conn.close()
            expired_lock_lease._lock_conn = None

hba_rollback = subprocess.run(
    hba_command + ["--rollback"], env=environment, check=False,
    capture_output=True, text=True,
    pass_fds=(observation_passfile_fd,),
)
assert hba_rollback.returncode == 0, (
    hba_rollback.stdout, hba_rollback.stderr
)
assert json.loads(hba_rollback.stdout)["status"] == "ROLLED_BACK"
cleanup_needed = False
os.close(observation_passfile_fd)

print("PostgreSQL B64 short-lived two-FD exported snapshot lifecycle: OK")
