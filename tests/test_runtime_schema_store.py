import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.runtime_schema_store import (
    SQLiteRuntimeSchemaStore,
    _BOT_REQUIRED_COLUMNS,
    _REQUIRED_COLUMNS,
)


def create_contract(conn, required):
    for table, columns in required.items():
        definitions = ",".join(f'"{column}" TEXT' for column in sorted(columns))
        conn.execute(f'CREATE TABLE "{table}"({definitions})')


with tempfile.TemporaryDirectory() as td:
    missing_path = Path(td) / "missing.db"
    try:
        SQLiteRuntimeSchemaStore(str(missing_path)).validate(profile="bot")
        raise AssertionError("missing SQLite database accepted")
    except RuntimeError as exc:
        assert str(exc) == "database_schema_unavailable"
    assert not missing_path.exists(), "validation created a missing database file"

    fresh_path = str(Path(td) / "fresh.db")
    with sqlite3.connect(fresh_path):
        pass
    try:
        SQLiteRuntimeSchemaStore(fresh_path).validate(profile="bot")
        raise AssertionError("fresh SQLite schema accepted")
    except RuntimeError as exc:
        assert str(exc).startswith("database_schema_incomplete:")
        assert "orders(" in str(exc)
        assert "bot_users(" in str(exc)
    with sqlite3.connect(fresh_path) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == [], "validation created runtime schema"


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "schema.db")
    with sqlite3.connect(path) as conn:
        create_contract(conn, _REQUIRED_COLUMNS)
    store = SQLiteRuntimeSchemaStore(path)
    store.validate()
    try:
        store.validate(profile="bot")
        raise AssertionError("shared-only SQLite schema accepted for bot")
    except RuntimeError as exc:
        assert "database_schema_incomplete:bot_users(" in str(exc)
    with sqlite3.connect(path) as conn:
        create_contract(conn, _BOT_REQUIRED_COLUMNS)
    store.validate(profile="bot")
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE user_vip_volume RENAME TO user_vip_volume_complete")
        conn.execute("CREATE TABLE user_vip_volume(user_id INTEGER)")
    try:
        store.validate(profile="bot")
        raise AssertionError("incomplete bot SQLite schema accepted")
    except RuntimeError as exc:
        assert "user_vip_volume(total_rub,updated_at)" in str(exc)

bot_source = (ROOT / "bot" / "main_bot.py").read_text(encoding="utf-8")
main_body = bot_source.split("async def main():", 1)[1].split(
    'if __name__ == "__main__":', 1
)[0]
validation_at = main_body.index('_runtime_schema.validate(profile="bot")')
assert validation_at < main_body.index("asyncio.create_task(")
for forbidden in (
    "def init_db", "db_conn", "CREATE TABLE", "ALTER TABLE",
    "PRAGMA table_info", "PRAGMA journal_mode", "_db_runtime.sqlite_connect",
):
    assert forbidden not in bot_source, f"runtime schema mutation remains: {forbidden}"

print("SQLite runtime-schema validation checks: OK")
