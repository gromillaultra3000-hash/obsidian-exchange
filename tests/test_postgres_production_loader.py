import os
import sqlite3
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "deploy/postgres"
sys.path.insert(0, str(MIGRATIONS))

from load_sqlite_snapshot import TABLE_ORDER, load_empty_snapshot
from migration_profile import selected_paths


def target_dsn(base: str, name: str) -> str:
    values = conninfo_to_dict(base)
    values["dbname"] = name
    return make_conninfo(**values)


base_dsn = os.environ["TEST_POSTGRES_DSN"]
database = f"production_loader_contract_{time.time_ns()}"
dsn = target_dsn(base_dsn, database)

with tempfile.TemporaryDirectory() as temp_dir:
    snapshot = str(Path(temp_dir) / "exchange-pre-cutover.db")
    with sqlite3.connect(snapshot) as source:
        for table in TABLE_ORDER:
            if table == "orders":
                source.execute(
                    "CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,"
                    "username TEXT,currency TEXT,rub_amount REAL,crypto_address TEXT,"
                    "status TEXT)"
                )
            elif table == "user_vip_volume":
                source.execute(
                    "CREATE TABLE user_vip_volume(user_id INTEGER PRIMARY KEY,"
                    "total_rub REAL)"
                )
            elif table == "web_users":
                source.execute(
                    "CREATE TABLE web_users(id INTEGER PRIMARY KEY,email TEXT,"
                    "password_hash TEXT)"
                )
            elif table == "web_sessions":
                source.execute(
                    "CREATE TABLE web_sessions(token TEXT PRIMARY KEY,web_user_id INTEGER,"
                    "csrf_token TEXT,expires_at TEXT)"
                )
            else:
                source.execute(f'CREATE TABLE "{table}"(placeholder TEXT)')
        source.executemany(
            "INSERT INTO orders VALUES(?,?,?,?,?,?,?)",
            [
                (1, 101, "user", "BTC", 1000.10, "address", "sent"),
                (2, 101, "user", "LTC", 500.20, "address", "completed"),
            ],
        )
        source.execute("INSERT INTO user_vip_volume VALUES(101,1500.30)")
        source.execute(
            "INSERT INTO web_users VALUES(201,'contract@example.invalid','hash')"
        )
        source.execute(
            "INSERT INTO web_sessions VALUES("
            "'session',201,'csrf','2030-01-01 00:00:00')"
        )

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

        def fail_before_commit():
            raise RuntimeError("freeze_lost_before_commit")

        try:
            load_empty_snapshot(
                snapshot,
                dsn,
                expected_database=database,
                expected_tables=TABLE_ORDER,
                before_commit=fail_before_commit,
            )
        except RuntimeError as exc:
            assert str(exc) == "freeze_lost_before_commit"
        else:
            raise AssertionError("before-commit freeze failure was ignored")
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0

        report = load_empty_snapshot(
            snapshot,
            dsn,
            expected_database=database,
            expected_tables=TABLE_ORDER,
        )
        assert len(report) == 54
        assert all(item["status"] == "loaded" for item in report)
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 2
            assert conn.execute(
                "SELECT total_rub FROM user_vip_volume WHERE user_id=101"
            ).fetchone()[0] == Decimal("1500.30")
            assert conn.execute("SELECT count(*) FROM web_sessions").fetchone()[0] == 1

        try:
            load_empty_snapshot(
                snapshot,
                dsn,
                expected_database=database,
                expected_tables=TABLE_ORDER,
            )
        except RuntimeError as exc:
            assert str(exc).startswith("production_target_not_empty:")
        else:
            raise AssertionError("non-empty production target accepted")
        with psycopg.connect(dsn) as conn:
            assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 2
            conn.execute("DROP TABLE alert_watermark")
        try:
            load_empty_snapshot(
                snapshot,
                dsn,
                expected_database=database,
                expected_tables=TABLE_ORDER,
            )
        except RuntimeError as exc:
            assert "unexpected_target_inventory:missing=alert_watermark" in str(exc)
        else:
            raise AssertionError("incomplete 54-table target accepted")
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                sql.Identifier(database)
            ))

print("PostgreSQL production initial-empty loader atomic/refusal checks: OK")
