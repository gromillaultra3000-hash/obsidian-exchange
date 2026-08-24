"""Disposable PostgreSQL 17 integration for exact HBA deploy and rollback."""
import atexit
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

from migration_profile import selected_paths
from verify_b64_snapshot_reader import inspect


ROLE = "obsidian_b64_snapshot_reader"
CONTAINER = os.environ["TEST_POSTGRES_CONTAINER"]
DSN = os.environ["TEST_POSTGRES_DSN"]
SYNTHETIC_PASSWORD = "disposable-hba-contract-only"
NONCE = "1234567890abcdef1234567890abcdef"


def execute_bound(conn, path: Path):
    conn.execute(
        sql.SQL("SET obsidian.snapshot_reader_expected_database = {}")
        .format(sql.Literal("obsidian_exchange"))
    )
    conn.execute("SET obsidian.snapshot_reader_require_absent = 'on'")
    conn.execute(
        sql.SQL("SET obsidian.snapshot_reader_deployment_nonce = {}")
        .format(sql.Literal(NONCE))
    )
    conn.execute(path.read_text("utf-8"))


def nsenter_probe(pid: int, dsn: str) -> dict:
    environment = dict(os.environ)
    environment["HBA_PROBE_DSN"] = dsn
    environment["PYTHONPATH"] = "/usr/lib/python3/dist-packages"
    code = (
        "import json,os,psycopg;"
        "out={};"
        "\ntry:\n"
        " c=psycopg.connect(os.environ['HBA_PROBE_DSN'],connect_timeout=5);"
        " r=c.execute('SELECT current_user,inet_client_addr()::text').fetchone();"
        " c.close();out={'connected':True,'user':r[0],'address':r[1]}"
        "\nexcept psycopg.Error as e:\n"
        " out={'connected':False,'primary':getattr(e.diag,'message_primary',None),"
        "'message':str(e)}"
        "\nprint(json.dumps(out,sort_keys=True))"
    )
    result = subprocess.run([
        "nsenter", "--target", str(pid), "--net",
        "/opt/lumi/venv/bin/python", "-c", code,
    ], env=environment, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


container = json.loads(subprocess.run(
    ["docker", "inspect", CONTAINER], check=True,
    capture_output=True, text=True,
).stdout)[0]
container_id = container["Id"].removeprefix("sha256:")
container_pid = container["State"]["Pid"]
image_id = container["Image"]
pgdata_source = Path(next(
    item["Source"] for item in container["Mounts"]
    if item["Destination"] == "/var/lib/postgresql/data"
))
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

environment = dict(os.environ)
environment["EXCHANGE_DATABASE_URL"] = DSN
environment["B64_LOCAL_ADMIN_DSN"] = admin_dsn
command = [
    sys.executable, str(POSTGRES / "deploy_b64_snapshot_reader_hba.py"),
    "--postgres-env", "EXCHANGE_DATABASE_URL",
    "--admin-postgres-env", "B64_LOCAL_ADMIN_DSN",
    "--container", CONTAINER,
    "--expected-container-id", container_id,
    "--expected-image-id", image_id,
    "--allow-contract-container",
]
preflight = subprocess.run(
    command, env=environment, check=False, capture_output=True, text=True,
)
assert preflight.returncode == 0, (preflight.stdout, preflight.stderr)
assert json.loads(preflight.stdout)["status"] == "PREFLIGHT_PASS"

deployed = subprocess.run(
    command + ["--apply"], env=environment, check=False,
    capture_output=True, text=True,
)
assert deployed.returncode == 0, (deployed.stdout, deployed.stderr)
deployment = json.loads(deployed.stdout)
assert deployment["status"] == "HBA_DEPLOYED_PARSED_DORMANT"
assert deployment["hbaIsolationStatus"] == "EXACT"
assert deployment["roleLoginState"] == "DISABLED"
assert deployment["credentialState"] == "ABSENT"
assert inspect(admin_dsn)["hbaIsolationStatus"] == "EXACT"

cleanup_needed = True


def emergency_cleanup():
    if not cleanup_needed:
        return
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL(
                "ALTER ROLE {} NOLOGIN PASSWORD NULL"
            ).format(sql.Identifier(ROLE)))
        subprocess.run(
            command + ["--rollback"], env=environment, check=False,
            capture_output=True, text=True,
        )
    except Exception:
        pass


atexit.register(emergency_cleanup)

with psycopg.connect(admin_dsn, autocommit=True) as conn:
    conn.execute(sql.SQL(
        "ALTER ROLE {} LOGIN PASSWORD {}"
    ).format(
        sql.Identifier(ROLE), sql.Literal(SYNTHETIC_PASSWORD),
    ))

reader = make_conninfo(
    DSN, user=ROLE, password=SYNTHETIC_PASSWORD,
    host="127.0.0.1", port=5432,
)
allowed = nsenter_probe(container_pid, reader)
assert allowed == {
    "connected": True, "user": ROLE, "address": "127.0.0.1/32",
}

other_database = nsenter_probe(
    container_pid, make_conninfo(reader, dbname="postgres")
)
assert other_database["connected"] is False
assert "pg_hba.conf rejects connection" in (
    other_database["primary"] or other_database["message"]
)

ipv6 = nsenter_probe(container_pid, make_conninfo(reader, host="::1"))
assert ipv6["connected"] is False
assert "pg_hba.conf rejects connection" in (
    ipv6["primary"] or ipv6["message"]
)

local_socket = make_conninfo(
    reader, host=f"/proc/{container_pid}/root/var/run/postgresql"
)
try:
    psycopg.connect(local_socket, connect_timeout=5).close()
except psycopg.Error as exc:
    assert "pg_hba.conf rejects connection" in \
        (getattr(exc.diag, "message_primary", None) or str(exc))
else:
    raise AssertionError("snapshot reader local socket unexpectedly allowed")

published = make_conninfo(
    reader,
    host=conninfo_to_dict(DSN)["host"],
    port=conninfo_to_dict(DSN)["port"],
)
try:
    psycopg.connect(published, connect_timeout=5).close()
except psycopg.Error as exc:
    assert "pg_hba.conf rejects connection" in \
        (getattr(exc.diag, "message_primary", None) or str(exc))
else:
    raise AssertionError("snapshot reader non-namespace TCP unexpectedly allowed")

with psycopg.connect(admin_dsn, autocommit=True) as conn:
    conn.execute(sql.SQL(
        "ALTER ROLE {} NOLOGIN PASSWORD NULL"
    ).format(sql.Identifier(ROLE)))

# Model a process crash after installation but before final receipt persistence.
journal_path = (
    pgdata_source / ".obsidian-b64-hba-v1" / "journal.json"
)
journal = json.loads(journal_path.read_text("utf-8"))
journal.pop("verifiedAt", None)
journal["phase"] = "CANDIDATE_INSTALLED"
journal_path.write_text(
    json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
journal_path.chmod(0o600)

rolled_back = subprocess.run(
    command + ["--reconcile"], env=environment, check=False,
    capture_output=True, text=True,
)
assert rolled_back.returncode == 0, (
    rolled_back.stdout, rolled_back.stderr
)
rollback = json.loads(rolled_back.stdout)
assert rollback["status"] == "RECONCILED_ROLLED_BACK"
assert rollback["recoveredJournalPhase"] == "CANDIDATE_INSTALLED"
assert rollback["rollbackVerified"] is True
report = inspect(admin_dsn)
assert report["status"] == "match"
assert report["hbaIsolationStatus"] == "MISSING_OR_DRIFTED"

# Re-apply and exercise the strict verified-state rollback as a separate path.
redeployed = subprocess.run(
    command + ["--apply"], env=environment, check=False,
    capture_output=True, text=True,
)
assert redeployed.returncode == 0, (redeployed.stdout, redeployed.stderr)
assert json.loads(redeployed.stdout)["status"] == \
    "HBA_DEPLOYED_PARSED_DORMANT"
strict_rollback = subprocess.run(
    command + ["--rollback"], env=environment, check=False,
    capture_output=True, text=True,
)
assert strict_rollback.returncode == 0, (
    strict_rollback.stdout, strict_rollback.stderr
)
assert json.loads(strict_rollback.stdout)["status"] == "ROLLED_BACK"
cleanup_needed = False

print("PostgreSQL B64 snapshot-reader HBA deploy/deny/rollback: OK")
