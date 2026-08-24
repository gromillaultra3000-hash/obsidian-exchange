import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
sys.path.insert(0, str(ROOT / "deploy/postgres"))

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from repositories.runtime_schema_store import (
    PostgresRuntimeSchemaStore,
    _BOT_REQUIRED_COLUMNS,
    _REQUIRED_COLUMNS,
)
from migration_profile import selected_paths


def create_contract(conn, required):
    for table, columns in required.items():
        definitions = sql.SQL(",").join(
            sql.SQL("{} text").format(sql.Identifier(column))
            for column in sorted(columns)
        )
        conn.execute(
            sql.SQL("CREATE TABLE {}({})").format(
                sql.Identifier(table), definitions
            )
        )


base_dsn = os.environ["TEST_POSTGRES_DSN"]
schema = f"runtime_schema_{time.time_ns()}"
dsn = make_conninfo(base_dsn, options=f"-c search_path={schema}")
with psycopg.connect(base_dsn) as conn:
    conn.execute(f'CREATE SCHEMA "{schema}"')
try:
    store = PostgresRuntimeSchemaStore(dsn)
    try:
        store.validate(profile="bot")
        raise AssertionError("fresh PostgreSQL schema accepted")
    except RuntimeError as exc:
        assert str(exc).startswith("database_schema_incomplete:")
        assert "orders(" in str(exc)
        assert "bot_users(" in str(exc)
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=current_schema()"
        ).fetchall() == [], "validation created runtime schema"
        create_contract(conn, _REQUIRED_COLUMNS)
    store.validate()
    try:
        store.validate(profile="bot")
        raise AssertionError("shared-only PostgreSQL schema accepted for bot")
    except RuntimeError as exc:
        assert "database_schema_incomplete:bot_users(" in str(exc)
    with psycopg.connect(dsn) as conn:
        create_contract(conn, _BOT_REQUIRED_COLUMNS)
    store.validate(profile="bot")
    with psycopg.connect(dsn) as conn:
        conn.execute("ALTER TABLE user_vip_volume DROP COLUMN total_rub")
    try:
        store.validate(profile="bot")
        raise AssertionError("incomplete bot PostgreSQL schema accepted")
    except RuntimeError as exc:
        assert "user_vip_volume(total_rub)" in str(exc)
finally:
    with psycopg.connect(base_dsn) as conn:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')

# The validator contract must match the canonical deployment migrations, not
# only synthetic tables assembled by this test.
migration_schema = f"runtime_migrations_{time.time_ns()}"
migration_dsn = make_conninfo(base_dsn, options=f"-c search_path={migration_schema}")
with psycopg.connect(base_dsn) as conn:
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(migration_schema)))
try:
    with psycopg.connect(migration_dsn) as conn:
        for migration in selected_paths(ROOT, "production-cutover"):
            conn.execute(migration.read_text(encoding="utf-8"))
    PostgresRuntimeSchemaStore(migration_dsn).validate(profile="bot")
finally:
    with psycopg.connect(base_dsn) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(
            sql.Identifier(migration_schema)
        ))

print("PostgreSQL runtime-schema validation checks: OK")
