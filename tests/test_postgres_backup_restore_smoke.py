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

from backup_restore_smoke import run_smoke
from migration_profile import selected_paths


def target_dsn(base: str, name: str) -> str:
    values = conninfo_to_dict(base)
    values["dbname"] = name
    return make_conninfo(**values)


base_dsn = os.environ["TEST_POSTGRES_DSN"]
source_database = f"backup_source_contract_{time.time_ns()}"
restore_database = f"backup_restore_smoke_{time.time_ns()}"
source_dsn = target_dsn(base_dsn, source_database)

with psycopg.connect(base_dsn, autocommit=True) as conn:
    conn.execute((MIGRATIONS / "bootstrap_roles.sql").read_text("utf-8"))
    conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(source_database)))

try:
    with psycopg.connect(source_dsn) as conn:
        conn.execute((MIGRATIONS / "prepare_database.sql").read_text("utf-8"))
    with psycopg.connect(source_dsn) as conn:
        conn.execute("SET ROLE obsidian_migrator")
        for migration in selected_paths(ROOT, "production-cutover"):
            conn.execute(migration.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO orders(order_id,user_id,username,currency,rub_amount,"
            "crypto_address,status) VALUES"
            "(7001,701,'backup','BTC',1000.10,'address','sent'),"
            "(7002,701,'backup','LTC',500.20,'address','completed')"
        )
        conn.execute(
            "INSERT INTO user_vip_volume(user_id,total_rub) VALUES(701,1500.30)"
        )
        conn.execute(
            "INSERT INTO web_users(id,email,password_hash) "
            "VALUES(801,'backup@example.invalid','not-a-real-hash')"
        )
        conn.execute(
            "INSERT INTO web_sessions(token,web_user_id,csrf_token,expires_at) "
            "VALUES('backup-session',801,'csrf',now()+interval '1 hour')"
        )
    with psycopg.connect(source_dsn) as conn:
        conn.execute((MIGRATIONS / "runtime_privileges.sql").read_text("utf-8"))

    report = run_smoke(
        source_dsn=source_dsn,
        admin_dsn=base_dsn,
        restore_database=restore_database,
        pg_dump_bin=os.getenv("TEST_PG_DUMP", "pg_dump"),
        pg_restore_bin=os.getenv("TEST_PG_RESTORE", "pg_restore"),
    )
    assert report["status"] == "match", report
    assert report["differences"] == []
    assert report["inventory"] == {"tables": 54, "sequences": 29, "functions": 2}
    assert report["privileges"]["status"] == "match"
finally:
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
            sql.Identifier(source_database)
        ))

print("PostgreSQL 17 pg_dump/pg_restore + schema/data/ACL smoke: OK")
