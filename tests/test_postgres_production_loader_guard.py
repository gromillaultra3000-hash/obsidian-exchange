import subprocess
import sys
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))

from load_production_snapshot import (
    CONFIRMATION_TOKEN,
    validate_confirmation,
    validate_snapshot_path,
    validate_source_inventory,
    validate_target_dsn,
    verify_write_freeze,
)
from load_sqlite_snapshot import TABLE_ORDER


validate_confirmation(
    initial_empty_load=True,
    confirmation=CONFIRMATION_TOKEN,
)
for initial, token in ((False, CONFIRMATION_TOKEN), (True, "wrong")):
    try:
        validate_confirmation(initial_empty_load=initial, confirmation=token)
    except RuntimeError:
        pass
    else:
        raise AssertionError("unsafe production confirmation accepted")

validate_target_dsn(
    "postgresql://obsidian_migrator@127.0.0.1:5432/obsidian_exchange"
)
for dsn in (
    "postgresql://obsidian_migrator@127.0.0.1:5432/postgres",
    "postgresql://obsidian_app@127.0.0.1:5432/obsidian_exchange",
    "postgresql://obsidian_migrator@10.0.0.1:5432/obsidian_exchange",
    "postgresql://obsidian_migrator@127.0.0.1:55432/obsidian_exchange",
):
    try:
        validate_target_dsn(dsn)
    except RuntimeError:
        pass
    else:
        raise AssertionError(f"unsafe production DSN accepted: {dsn}")

try:
    validate_snapshot_path("/tmp/exchange-pre-cutover.db")
except RuntimeError as exc:
    assert str(exc) == "refusing_unexpected_snapshot_path"
else:
    raise AssertionError("unexpected snapshot path accepted")

with tempfile.TemporaryDirectory() as temp_dir:
    incomplete = Path(temp_dir) / "incomplete.db"
    with sqlite3.connect(incomplete) as conn:
        conn.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY)")
    try:
        validate_source_inventory(incomplete)
    except RuntimeError as exc:
        assert str(exc).startswith("frozen_snapshot_inventory_mismatch:missing=")
        assert "user_vip_volume" in str(exc)
        assert "web_sessions" in str(exc)
    else:
        raise AssertionError("incomplete frozen source inventory accepted")

    unexpected = Path(temp_dir) / "unexpected.db"
    with sqlite3.connect(unexpected) as conn:
        for table in TABLE_ORDER:
            conn.execute(f'CREATE TABLE "{table}"(placeholder TEXT)')
        conn.execute("CREATE TABLE unexpected_rogue(placeholder TEXT)")
    try:
        validate_source_inventory(unexpected)
    except RuntimeError as exc:
        assert str(exc).endswith(";unexpected=unexpected_rogue")
        assert "missing=;" in str(exc)
    else:
        raise AssertionError("unexpected frozen source table accepted")


def frozen_runner(args, **_kwargs):
    if args[0] == "systemctl":
        return subprocess.CompletedProcess(args, 3, "inactive\n", "")
    return subprocess.CompletedProcess(args, 1, "", "")


verify_write_freeze(runner=frozen_runner, which=lambda _name: "/usr/bin/fuser")


def active_runner(args, **_kwargs):
    if args[0] == "systemctl" and args[-1] == "exchange-bot.service":
        return subprocess.CompletedProcess(args, 0, "active\n", "")
    if args[0] == "systemctl":
        return subprocess.CompletedProcess(args, 3, "inactive\n", "")
    return subprocess.CompletedProcess(args, 1, "", "")


try:
    verify_write_freeze(runner=active_runner, which=lambda _name: "/usr/bin/fuser")
except RuntimeError as exc:
    assert "exchange-bot.service:active" in str(exc)
else:
    raise AssertionError("active writer accepted")


def holder_runner(args, **_kwargs):
    if args[0] == "systemctl":
        return subprocess.CompletedProcess(args, 3, "inactive\n", "")
    return subprocess.CompletedProcess(args, 0, "123", "")


try:
    verify_write_freeze(runner=holder_runner, which=lambda _name: "/usr/bin/fuser")
except RuntimeError as exc:
    assert str(exc) == "authoritative_sqlite_has_open_holders"
else:
    raise AssertionError("open SQLite holder accepted")

production_source = (ROOT / "deploy/postgres/load_production_snapshot.py").read_text("utf-8")
assert "TRUNCATE" not in production_source
assert "production_target_not_empty" in (
    ROOT / "deploy/postgres/load_sqlite_snapshot.py"
).read_text("utf-8")

print("PostgreSQL production-loader target/freeze/holder guards: OK")
