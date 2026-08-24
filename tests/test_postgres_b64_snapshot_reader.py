import os
import json
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

from migration_profile import selected_paths
from verify_b64_snapshot_reader import ROLE, inspect


def target_dsn(base: str, name: str) -> str:
    values = conninfo_to_dict(base)
    values["dbname"] = name
    return make_conninfo(**values)


def denied(cur, statement: str):
    cur.execute("SAVEPOINT expected_denial")
    try:
        cur.execute(statement)
    except psycopg.errors.InsufficientPrivilege:
        cur.execute("ROLLBACK TO SAVEPOINT expected_denial")
    else:
        cur.execute("ROLLBACK TO SAVEPOINT expected_denial")
        raise AssertionError(f"unexpectedly allowed: {statement}")


base_dsn = os.environ["TEST_POSTGRES_DSN"]
database = f"b64_reader_contract_{time.time_ns()}"
dsn = target_dsn(base_dsn, database)
provision = (POSTGRES / "provision_b64_snapshot_reader.sql").read_text("utf-8")
rollback = (POSTGRES / "rollback_b64_snapshot_reader.sql").read_text("utf-8")
DEPLOYMENT_NONCE = "0123456789abcdef0123456789abcdef"


def execute_bound(conn, source: str, deployment_nonce: str = DEPLOYMENT_NONCE):
    conn.execute(sql.SQL("SET obsidian.snapshot_reader_expected_database = {}")
                 .format(sql.Literal(database)))
    conn.execute(sql.SQL("SET obsidian.snapshot_reader_deployment_nonce = {}")
                 .format(sql.Literal(deployment_nonce)))
    conn.execute(source)

with psycopg.connect(base_dsn, autocommit=True) as conn:
    conn.execute((POSTGRES / "bootstrap_roles.sql").read_text("utf-8"))
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

try:
    with psycopg.connect(dsn) as conn:
        conn.execute((POSTGRES / "prepare_database.sql").read_text("utf-8"))
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_migrator")
        for migration in selected_paths(ROOT, "production-cutover"):
            conn.execute(migration.read_text(encoding="utf-8"))
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute((POSTGRES / "runtime_privileges.sql").read_text("utf-8"))
        execute_bound(conn, provision)
        execute_bound(conn, provision)

    report = inspect(dsn)
    assert report["status"] == "match", report
    assert report["inventory"] == {
        "tables": 54,
        "sequences": 29,
        "functions": 2,
        "otherUserSchemas": 0,
        "columns": 423,
    }
    assert report["sequenceContract"] == {
        "select": True,
        "usage": False,
        "update": False,
        "reason": "PG_DUMP_READS_LAST_VALUE_AND_IS_CALLED",
    }
    assert report["credentialState"] == "ABSENT"
    assert report["loginState"] == "DISABLED"
    assert report["activationStatus"] == "BLOCKED"
    assert "CREDENTIAL_NOT_ISSUED" in report["activationBlockers"]
    assert "EXACT_HBA_FIRST_MATCH_NOT_ATTESTED" in report["activationBlockers"]

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("SET SESSION AUTHORIZATION {}").format(
            sql.Identifier(ROLE)
        ))
        cur.execute("SELECT session_user,current_user")
        assert cur.fetchone() == (ROLE, ROLE)
        cur.execute("SELECT count(*) FROM public.orders")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT last_value,is_called FROM public.orders_order_id_seq")
        assert len(cur.fetchone()) == 2
        denied(cur, "SELECT nextval('public.orders_order_id_seq')")
        denied(cur, "SELECT setval('public.orders_order_id_seq', 100)")
        denied(cur, "INSERT INTO public.blocked_users(user_id) VALUES(991)")
        denied(cur, "UPDATE public.orders SET status='paid'")
        denied(cur, "DELETE FROM public.orders")
        denied(cur, "TRUNCATE public.orders")
        denied(cur, "SELECT * FROM public.claim_next_order_payout()")
        denied(cur, "CREATE TABLE public.forbidden_reader(id bigint)")
        denied(cur, "CREATE TEMP TABLE forbidden_reader(id bigint)")
        denied(cur, "SET ROLE obsidian_app")

    # Reapplication removes stale ACLs in public and every other user schema.
    with psycopg.connect(dsn) as conn:
        conn.execute("GRANT USAGE ON SEQUENCE orders_order_id_seq TO " + ROLE)
        conn.execute("GRANT UPDATE(status) ON orders TO " + ROLE)
        conn.execute("GRANT EXECUTE ON FUNCTION claim_next_order_payout() TO " + ROLE)
        conn.execute("CREATE SCHEMA private_contract AUTHORIZATION obsidian_migrator")
        conn.execute("CREATE TABLE private_contract.hidden(id bigint)")
        conn.execute("GRANT USAGE ON SCHEMA private_contract TO " + ROLE)
        conn.execute("GRANT SELECT ON private_contract.hidden TO " + ROLE)
    drift = inspect(dsn)
    assert drift["status"] == "mismatch", drift
    assert any(item.startswith("column_privilege:orders:status:UPDATE")
               for item in drift["violations"]), drift
    assert any(item.startswith("column_direct_acl:orders:")
               for item in drift["violations"]), drift
    with psycopg.connect(dsn, autocommit=True) as conn:
        execute_bound(conn, provision)
    assert inspect(dsn)["status"] == "match"

    # Database-specific settings and stale credential state never get silently
    # absorbed by an idempotent reapply.
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} SET "
                             "statement_timeout='1ms'").format(
            sql.Identifier(ROLE), sql.Identifier(database)
        ))
    drift = inspect(dsn)
    assert any(item.startswith("per_database_role_settings:")
               for item in drift["violations"]), drift
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            execute_bound(conn, provision)
        except psycopg.errors.RaiseException as exc:
            assert "per-database settings" in str(exc)
        else:
            raise AssertionError("provisioning accepted per-database settings")
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER ROLE {} IN DATABASE {} RESET ALL").format(
            sql.Identifier(ROLE), sql.Identifier(database)
        ))
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD 'synthetic-test-only'").format(
            sql.Identifier(ROLE)
        ))
    credential_drift = inspect(dsn)
    assert credential_drift["status"] == "match", credential_drift
    assert credential_drift["credentialState"] == "PRESENT"
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            execute_bound(conn, provision)
        except psycopg.errors.RaiseException as exc:
            assert "pre-existing credential state" in str(exc)
        else:
            raise AssertionError("provisioning accepted stale credential")
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("ALTER ROLE {} PASSWORD NULL").format(
            sql.Identifier(ROLE)
        ))
    assert inspect(dsn)["credentialState"] == "ABSENT"

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA reader_owned_contract "
                             "AUTHORIZATION {}").format(sql.Identifier(ROLE)))
    owned_drift = inspect(dsn)
    assert any(item.startswith("owned_objects:")
               for item in owned_drift["violations"]), owned_drift
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            execute_bound(conn, provision)
        except psycopg.errors.RaiseException as exc:
            assert "owns database objects" in str(exc)
            conn.execute("ROLLBACK")
        else:
            raise AssertionError("provisioning accepted owned objects")
        conn.execute("DROP SCHEMA reader_owned_contract")
    assert inspect(dsn)["status"] == "match"

    # Membership is forbidden in both directions and is never auto-repaired.
    for grant, revoke, expected in (
        (f"GRANT obsidian_app TO {ROLE}", f"REVOKE obsidian_app FROM {ROLE}",
         f"role_membership:obsidian_app:{ROLE}"),
        (f"GRANT {ROLE} TO obsidian_app", f"REVOKE {ROLE} FROM obsidian_app",
         f"role_membership:{ROLE}:obsidian_app"),
    ):
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(grant)
        drift = inspect(dsn)
        assert expected in drift["violations"], drift
        with psycopg.connect(dsn, autocommit=True) as conn:
            try:
                execute_bound(conn, provision)
            except psycopg.errors.RaiseException as exc:
                assert "participates in role membership" in str(exc)
            else:
                raise AssertionError("provisioning accepted role membership")
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(revoke)
        assert inspect(dsn)["status"] == "match"

    # Migration/profile drift fails before ACL changes.
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_migrator")
        conn.execute("CREATE TABLE unexpected_profile_table(id bigint)")
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            execute_bound(conn, provision)
        except psycopg.errors.RaiseException as exc:
            assert "exact frozen 001-023 table inventory" in str(exc)
        else:
            raise AssertionError("provisioning accepted unexpected table")
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_migrator")
        conn.execute("DROP TABLE unexpected_profile_table")
    assert inspect(dsn)["status"] == "match"

    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_migrator")
        conn.execute("ALTER TABLE orders ADD COLUMN unexpected_profile_column text")
    column_drift = inspect(dsn)
    assert any(item.startswith("column_catalog:424:")
               for item in column_drift["violations"]), column_drift
    with psycopg.connect(dsn, autocommit=True) as conn:
        try:
            execute_bound(conn, provision)
        except psycopg.errors.RaiseException as exc:
            assert "exact frozen 001-023 column catalog" in str(exc)
        else:
            raise AssertionError("provisioning accepted unexpected column")
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_migrator")
        conn.execute("ALTER TABLE orders DROP COLUMN unexpected_profile_column")
    assert inspect(dsn)["status"] == "match"

    # Docker rehearsals additionally prove that a direct LOGIN (not SET ROLE)
    # can create a complete archive without USAGE/UPDATE on sequences.
    test_container = os.environ.get("TEST_POSTGRES_CONTAINER")
    if test_container:
        archive = f"/tmp/{database}.dump"
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("ALTER ROLE {} LOGIN").format(
                sql.Identifier(ROLE)
            ))
        exporter = subprocess.Popen([
            "docker", "exec", "-i", "-u", "postgres", test_container,
            "psql", "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1",
            "-U", ROLE, "-d", database,
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            assert exporter.stdin is not None and exporter.stdout is not None
            exporter.stdin.write(
                "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                "SELECT pg_export_snapshot();\n"
            )
            exporter.stdin.flush()
            snapshot = exporter.stdout.readline().strip()
            assert snapshot
            subprocess.run([
                "docker", "exec", "-u", "postgres", test_container,
                "pg_dump", "-U", ROLE, "-d", database, "--format=custom",
                "--no-owner", "--no-privileges", "--no-password",
                "--lock-wait-timeout=5000", "--schema=public",
                "--no-large-objects", "--strict-names",
                f"--snapshot={snapshot}", f"--file={archive}",
            ], check=True)
            toc = subprocess.run([
                "docker", "exec", "-u", "postgres", test_container,
                "pg_restore", "--list", archive,
            ], check=True, capture_output=True, text=True).stdout
            assert "TABLE DATA public orders" in toc
            assert "SEQUENCE SET public orders_order_id_seq" in toc
        finally:
            if exporter.stdin is not None:
                try:
                    exporter.stdin.write("ROLLBACK;\n\\q\n")
                    exporter.stdin.flush()
                except BrokenPipeError:
                    pass
                exporter.stdin.close()
            exporter.wait(timeout=10)
            subprocess.run([
                "docker", "exec", test_container, "rm", "-f", archive,
            ], check=False)
            with psycopg.connect(base_dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(
                    sql.Identifier(ROLE)
                ))
        assert inspect(dsn)["status"] == "match"

    with psycopg.connect(dsn, autocommit=True) as conn:
        execute_bound(conn, rollback)
    assert inspect(dsn)["violations"] == [f"missing_role:{ROLE}"]

    if test_container:
        container_value = json.loads(subprocess.run([
            "docker", "inspect", test_container,
        ], check=True, capture_output=True, text=True).stdout)[0]
        runner_env = dict(os.environ)
        runner_env["EXCHANGE_DATABASE_URL"] = dsn
        runner_env["B64_LOCAL_ADMIN_DSN"] = make_conninfo(
            host=(f"/proc/{container_value['State']['Pid']}/root"
                  "/var/run/postgresql"),
            dbname=database,
            user="postgres",
            connect_timeout=5,
            sslmode="disable",
            target_session_attrs="read-write",
        )
        deployed = subprocess.run([
            sys.executable,
            str(POSTGRES / "deploy_b64_snapshot_reader.py"),
            "--postgres-env", "EXCHANGE_DATABASE_URL",
            "--admin-postgres-env", "B64_LOCAL_ADMIN_DSN",
            "--expected-database", database,
            "--allow-contract-database",
            "--container", test_container,
            "--expected-container-id",
            container_value["Id"].removeprefix("sha256:"),
            "--expected-image-id", container_value["Image"],
            "--require-role-absent", "--apply",
        ], env=runner_env, check=False, capture_output=True, text=True)
        assert deployed.returncode == 0, (deployed.stdout, deployed.stderr)
        deployment_report = json.loads(deployed.stdout)
        assert deployment_report["status"] == "DEPLOYED_DORMANT"
        assert deployment_report["rollbackAttempted"] is False
        assert inspect(dsn)["status"] == "match"
        with psycopg.connect(dsn, autocommit=True) as conn:
            execute_bound(conn, rollback,
                          deployment_report["deploymentNonce"])
        assert inspect(dsn)["violations"] == [f"missing_role:{ROLE}"]
finally:
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
            sql.Identifier(database)
        ))
        conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(
            sql.Identifier(ROLE)
        ))

print("PostgreSQL B64 snapshot-reader provisioning and denials: OK")
