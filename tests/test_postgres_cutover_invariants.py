import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))

from reconcile_snapshot import reconcile_cutover_invariants


dsn = os.environ["TEST_POSTGRES_DSN"]
schema = "cutover_invariant_gate_contract"
scoped_dsn = make_conninfo(dsn, options=f"-csearch_path={schema}")

with tempfile.TemporaryDirectory() as td:
    source = str(Path(td) / "source.db")
    with sqlite3.connect(source) as conn:
        conn.executescript(
            """
            CREATE TABLE orders(
                order_id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,status TEXT NOT NULL
            );
            CREATE TABLE user_vip_volume(
                user_id INTEGER PRIMARY KEY,total_rub REAL
            );
            CREATE TABLE referral_bonuses(
                id INTEGER PRIMARY KEY,bonus_amount REAL NOT NULL DEFAULT 0
            );
            INSERT INTO orders VALUES
                (1,101,'sent'),(2,101,'completed'),(3,101,'paid'),
                (4,202,'sent'),(5,303,'pending'),(6,404,'failed');
            INSERT INTO user_vip_volume VALUES
                (101,1000.10),(202,40382.73);
            """
        )

    try:
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)
            ))
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

        with psycopg.connect(scoped_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE orders("
                "order_id bigint PRIMARY KEY,user_id bigint NOT NULL,status text NOT NULL)"
            )
            cur.execute(
                "CREATE TABLE user_vip_volume("
                "user_id bigint PRIMARY KEY,total_rub numeric(20,2))"
            )
            cur.execute(
                "CREATE TABLE referral_bonuses("
                "id bigint PRIMARY KEY,bonus_amount numeric(30,12) NOT NULL DEFAULT 0)"
            )
            cur.execute(
                "INSERT INTO orders VALUES"
                "(1,101,'sent'),(2,101,'completed'),(3,101,'paid'),"
                "(4,202,'sent'),(5,303,'pending'),(6,404,'failed')"
            )
            cur.execute(
                "INSERT INTO user_vip_volume VALUES"
                "(101,1000.10),(202,40382.73)"
            )

        report = reconcile_cutover_invariants(source, scoped_dsn)
        assert report["status"] == "match", report
        success = report["critical"]["successful_orders_by_user"]
        assert success["sqlite_user_count"] == success["postgres_user_count"] == 2
        assert success["sqlite_order_count"] == success["postgres_order_count"] == 3
        vip = report["critical"]["user_vip_volume"]
        assert vip["sqlite_total_rub"] == vip["postgres_total_rub"] == "41382.83"
        assert report["informational"]["referral_bonuses"]["blocking"] is False
        assert report["informational"]["referral_bonuses"]["sqlite_zero"] is True
        assert report["informational"]["referral_bonuses"]["postgres_zero"] is True
        order_diagnostics = report["informational"]["order_status_counts"]
        assert order_diagnostics["blocking"] is False
        assert order_diagnostics["status"] == "match"
        assert order_diagnostics["included_statuses"] == ["paid", "pending"]
        assert order_diagnostics["sqlite"] == {"paid": 1, "pending": 1}
        assert order_diagnostics["postgres"] == {"paid": 1, "pending": 1}

        # Losing one successful status must block with an exact per-user diff.
        with psycopg.connect(scoped_dsn) as conn, conn.cursor() as cur:
            cur.execute("UPDATE orders SET status='paid' WHERE order_id=2")
        report = reconcile_cutover_invariants(source, scoped_dsn)
        assert report["status"] == "critical_mismatch", report
        assert report["critical"]["successful_orders_by_user"]["differences"] == [
            {"user_id": 101, "sqlite_count": 2, "postgres_count": 1}
        ]

        with psycopg.connect(scoped_dsn) as conn, conn.cursor() as cur:
            cur.execute("UPDATE orders SET status='completed' WHERE order_id=2")
            cur.execute("UPDATE user_vip_volume SET total_rub=40382.74 WHERE user_id=202")
        report = reconcile_cutover_invariants(source, scoped_dsn)
        assert report["status"] == "critical_mismatch", report
        assert report["critical"]["user_vip_volume"]["differences"] == [{
            "user_id": 202,
            "sqlite_present": True,
            "postgres_present": True,
            "sqlite_total_rub": "40382.73",
            "postgres_total_rub": "40382.74",
        }]

        # A missing VIP user is also critical, not hidden by an aggregate total.
        with psycopg.connect(scoped_dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM user_vip_volume WHERE user_id=202")
        report = reconcile_cutover_invariants(source, scoped_dsn)
        assert report["status"] == "critical_mismatch", report
        assert report["critical"]["user_vip_volume"]["differences"] == [{
            "user_id": 202,
            "sqlite_present": True,
            "postgres_present": False,
            "sqlite_total_rub": "40382.73",
            "postgres_total_rub": None,
        }]

        # Referral and paid/pending drift remains visible but non-blocking.
        with psycopg.connect(scoped_dsn) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO user_vip_volume VALUES(202,40382.73)")
            cur.execute("INSERT INTO referral_bonuses VALUES(1,0.0001)")
            cur.execute("UPDATE orders SET status='failed' WHERE order_id=5")
        report = reconcile_cutover_invariants(source, scoped_dsn)
        assert report["status"] == "match", report
        assert report["informational"]["referral_bonuses"]["status"] == "attention"
        assert report["informational"]["referral_bonuses"]["postgres_zero"] is False
        assert report["informational"]["referral_bonuses"]["postgres_row_count"] == 1
        assert report["informational"]["order_status_counts"]["postgres"] == {
            "paid": 1,
            "pending": 0,
        }
        assert report["informational"]["order_status_counts"]["status"] == "different"
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema)
            ))

print("PostgreSQL cutover critical-invariant and drift checks: OK")
