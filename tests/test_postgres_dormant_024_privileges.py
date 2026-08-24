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

from load_sqlite_snapshot import (
    DORMANT_MIGRATION_TABLE_ORDER,
)
from migration_profile import selected_paths


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


def test_dormant_024_stays_outside_every_runtime_role():
    base_dsn = os.environ["TEST_POSTGRES_DSN"]
    database = f"dormant_024_contract_{time.time_ns()}"
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
        # PostgreSQL's built-in function default grants PUBLIC EXECUTE.  Prove
        # the creator-role global default revoke applies to a future function,
        # then remove the probe before exercising the exact 024 inventory.
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SET ROLE obsidian_migrator")
            cur.execute(
                "CREATE FUNCTION future_acl_probe() RETURNS integer "
                "LANGUAGE sql AS 'SELECT 1'"
            )
            cur.execute("RESET ROLE")
            assert not cur.execute(
                "SELECT has_function_privilege("
                "'public','public.future_acl_probe()','EXECUTE')"
            ).fetchone()[0]
            cur.execute("SET ROLE obsidian_migrator")
            cur.execute("DROP FUNCTION future_acl_probe()")
        with psycopg.connect(dsn) as conn:
            conn.execute("SET ROLE obsidian_migrator")
            for migration in selected_paths(ROOT, "post-cutover-dormant"):
                conn.execute(migration.read_text(encoding="utf-8"))

        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            assert cur.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n "
                "ON n.oid=c.relnamespace WHERE n.nspname='public' "
                "AND c.relkind IN ('r','p')"
            ).fetchone()[0] == 56
            assert cur.execute(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n "
                "ON n.oid=p.pronamespace WHERE n.nspname='public'"
            ).fetchone()[0] == 4
            functions = (
                "e3_reject_evidence_mutation()",
                "e3_append_paper_evidence(text,text,text,bigint,text,text,jsonb)",
            )
            for function in functions:
                assert not cur.execute(
                    "SELECT has_function_privilege('public',%s::regprocedure,'EXECUTE')",
                    (f"public.{function}",),
                ).fetchone()[0]
            for role in ("obsidian_app", "obsidian_readonly", "obsidian_payout"):
                for table in DORMANT_MIGRATION_TABLE_ORDER:
                    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                        assert not cur.execute(
                            "SELECT has_table_privilege(%s,%s::regclass,%s)",
                            (role, f"public.{table}", privilege),
                        ).fetchone()[0]
                for function in functions:
                    assert not cur.execute(
                        "SELECT has_function_privilege(%s,%s::regprocedure,'EXECUTE')",
                        (role, f"public.{function}"),
                    ).fetchone()[0]

        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute("SET ROLE obsidian_app")
            cur.execute("SELECT count(*) FROM orders")
            denied(cur, "SELECT count(*) FROM e3_paper_evidence")
        with psycopg.connect(dsn) as conn:
            try:
                conn.execute((MIGRATIONS / "runtime_privileges.sql").read_text("utf-8"))
            except psycopg.errors.RaiseException as exc:
                assert "requires exact 001-023 table inventory" in str(exc)
            else:
                raise AssertionError("runtime ACL accepted dormant migration 024")
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                sql.Identifier(database)
            ))


if __name__ == "__main__":
    test_dormant_024_stays_outside_every_runtime_role()
    print("Dormant PostgreSQL 024 ACL isolation: OK")
