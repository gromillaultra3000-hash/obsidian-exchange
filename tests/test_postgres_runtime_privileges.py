import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "deploy/postgres"
sys.path.insert(0, str(MIGRATIONS))

from verify_runtime_privileges import inspect
from migration_profile import selected_paths


def target_dsn(base: str, name: str) -> str:
    values = conninfo_to_dict(base)
    values["dbname"] = name
    return make_conninfo(**values)


def denied(cur, statement: str, params=()):
    cur.execute("SAVEPOINT expected_denial")
    try:
        cur.execute(statement, params)
    except psycopg.errors.InsufficientPrivilege:
        cur.execute("ROLLBACK TO SAVEPOINT expected_denial")
    else:
        cur.execute("ROLLBACK TO SAVEPOINT expected_denial")
        raise AssertionError(f"unexpectedly allowed: {statement}")


base_dsn = os.environ["TEST_POSTGRES_DSN"]
database = f"privilege_contract_{time.time_ns()}"
dsn = target_dsn(base_dsn, database)

with psycopg.connect(base_dsn, autocommit=True) as conn:
    conn.execute((MIGRATIONS / "bootstrap_roles.sql").read_text("utf-8"))
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

try:
    with psycopg.connect(dsn) as conn:
        conn.execute((MIGRATIONS / "prepare_database.sql").read_text("utf-8"))

    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_migrator")
        for migration in selected_paths(ROOT, "production-cutover"):
            conn.execute(migration.read_text(encoding="utf-8"))

    with psycopg.connect(dsn) as conn:
        conn.execute((MIGRATIONS / "runtime_privileges.sql").read_text("utf-8"))

    report = inspect(dsn)
    assert report["status"] == "match", report
    assert report["inventory"] == {
        "tables": 54,
        "sequences": 29,
        "functions": 2,
        "readonly_tables": 54,
    }

    # Future functions must remain private to their creator. Re-granting the
    # PostgreSQL built-in PUBLIC default must be visible before any new object
    # exists, not only after an exposure has occurred.
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator "
            "GRANT EXECUTE ON FUNCTIONS TO PUBLIC"
        )
    drift = inspect(dsn)
    assert any(item.startswith("default_function_acl:")
               for item in drift["violations"]), drift
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator "
            "REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
        )
    assert inspect(dsn)["status"] == "match"

    # No role may inherit a runtime role, and no runtime role may inherit any
    # other role. Both directions are independently mutation-tested.
    intruder = f"privilege_contract_intruder_{time.time_ns()}"
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(intruder)))
    try:
        for grant_sql, expected in (
            (sql.SQL("GRANT obsidian_app TO {}").format(sql.Identifier(intruder)),
             f"role_membership:obsidian_app:{intruder}"),
            (sql.SQL("GRANT {} TO obsidian_app").format(sql.Identifier(intruder)),
             f"role_membership:{intruder}:obsidian_app"),
        ):
            with psycopg.connect(base_dsn, autocommit=True) as conn:
                conn.execute(grant_sql)
            drift = inspect(dsn)
            assert expected in drift["violations"], drift
            with psycopg.connect(dsn) as conn:
                try:
                    conn.execute((MIGRATIONS / "bootstrap_roles.sql").read_text("utf-8"))
                except psycopg.errors.RaiseException as exc:
                    assert "participates in membership" in str(exc)
                else:
                    raise AssertionError("bootstrap accepted runtime role membership")
            with psycopg.connect(base_dsn, autocommit=True) as conn:
                if expected.startswith("role_membership:obsidian_app"):
                    conn.execute(sql.SQL("REVOKE obsidian_app FROM {}").format(
                        sql.Identifier(intruder)
                    ))
                else:
                    conn.execute(sql.SQL("REVOKE {} FROM obsidian_app").format(
                        sql.Identifier(intruder)
                    ))
        assert inspect(dsn)["status"] == "match"
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("REVOKE obsidian_app FROM {}").format(
                sql.Identifier(intruder)
            ))
            conn.execute(sql.SQL("REVOKE {} FROM obsidian_app").format(
                sql.Identifier(intruder)
            ))
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(
                sql.Identifier(intruder)
            ))

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET ROLE obsidian_app")
        cur.execute("INSERT INTO audit_log(event,details) VALUES('acl','app') RETURNING id")
        assert cur.fetchone()[0] == 1
        cur.execute("UPDATE audit_log SET details='updated' WHERE id=1")
        cur.execute("SELECT details FROM audit_log WHERE id=1")
        assert cur.fetchone()[0] == "updated"
        cur.execute("DELETE FROM audit_log WHERE id=1")
        denied(cur, "CREATE TABLE forbidden_app(id bigint)")
        denied(cur, "SELECT * FROM claim_next_order_payout()")

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET ROLE obsidian_readonly")
        cur.execute("SELECT count(*) FROM orders")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM payout_intents")
        assert cur.fetchone()[0] == 0
        denied(cur, "INSERT INTO blocked_users(user_id) VALUES(991)")
        denied(cur, "CREATE TEMP TABLE forbidden_readonly(id bigint)")

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO payout_intents("
                    "order_id,idempotency_key,source,rub_amount,crypto_amount,"
                    "currency,destination) VALUES(9001,'payout_9001','test',100,0.1,'BTC','addr')")
        cur.execute("INSERT INTO referral_payout_intents("
                    "user_id,idempotency_key,crypto_amount,destination) "
                    "VALUES(9002,'referral_9002_1',0.1,'addr')")

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SET ROLE obsidian_payout")
        cur.execute("SELECT order_id,state FROM claim_next_order_payout()")
        assert cur.fetchone() == (9001, "processing")
        cur.execute("UPDATE payout_intents SET state='succeeded',txid='tx',"
                    "finished_at=now(),updated_at=now() "
                    "WHERE order_id=9001 AND state='processing'")
        assert cur.rowcount == 1
        cur.execute("SELECT id,state FROM claim_next_referral_payout()")
        referral_id, state = cur.fetchone()
        assert state == "processing"
        cur.execute("UPDATE referral_payout_intents SET state='review',"
                    "error_code='test',finished_at=now(),updated_at=now() "
                    "WHERE id=%s AND state='processing'", (referral_id,))
        assert cur.rowcount == 1
        denied(cur, "UPDATE payout_intents SET destination='other' WHERE order_id=9001")
        denied(cur, "INSERT INTO payout_intents("
                    "order_id,idempotency_key,source,rub_amount,crypto_amount,"
                    "currency,destination) VALUES(9003,'payout_9003','test',1,1,'BTC','x')")
        denied(cur, "SELECT count(*) FROM orders")
        denied(cur, "SELECT nextval('payout_intents_id_seq')")
        denied(cur, "CREATE TABLE forbidden_payout(id bigint)")
finally:
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
            sql.Identifier(database)
        ))

print("PostgreSQL runtime least-privilege matrix and denial checks: OK")
