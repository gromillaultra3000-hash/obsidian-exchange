#!/usr/bin/env python3
"""One-shot frozen SQLite -> empty production PostgreSQL loader."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
from pathlib import Path
from typing import Any, Callable

from psycopg.conninfo import conninfo_to_dict

from load_sqlite_snapshot import TABLE_ORDER, load_empty_snapshot


PRODUCTION_DATABASE = "obsidian_exchange"
PRODUCTION_SNAPSHOT = Path(
    "/var/lib/obsidian-exchange/cutover/exchange-pre-cutover.db"
)
AUTHORITATIVE_SQLITE = Path("/var/lib/obsidian-exchange/exchange.db")
CONFIRMATION_TOKEN = "FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE"
WRITER_SERVICES = (
    "relay-fastapi.service",
    "exchange-bot.service",
    "obsidian-payout-worker.service",
    "exchange-notifier.service",
    "obsidian-monitor.service",
    "admin-panel.service",
    "support-bot.service",
)


def validate_confirmation(*, initial_empty_load: bool, confirmation: str) -> None:
    if not initial_empty_load:
        raise RuntimeError("initial_empty_load_flag_required")
    if confirmation != CONFIRMATION_TOKEN:
        raise RuntimeError("frozen_confirmation_token_required")


def validate_target_dsn(dsn: str) -> None:
    values = conninfo_to_dict(dsn)
    if values.get("dbname") != PRODUCTION_DATABASE:
        raise RuntimeError("refusing_non_production_database")
    if values.get("user") != "obsidian_migrator":
        raise RuntimeError("production_loader_requires_migrator_role")
    host = values.get("host") or ""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("production_loader_requires_loopback")
    port = str(values.get("port") or "5432")
    if port != "5432":
        raise RuntimeError("production_loader_requires_port_5432")


def validate_snapshot_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate != PRODUCTION_SNAPSHOT:
        raise RuntimeError("refusing_unexpected_snapshot_path")
    component = candidate
    while component != component.parent:
        if component.is_symlink():
            raise RuntimeError("snapshot_path_must_not_contain_symlink")
        component = component.parent
    info = candidate.stat()
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError("snapshot_must_be_regular_file")
    if info.st_uid != 0:
        raise RuntimeError("snapshot_must_be_root_owned")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise RuntimeError("snapshot_permissions_too_open")
    with sqlite3.connect(
        f"file:{candidate}?mode=ro&immutable=1", uri=True
    ) as conn:
        result = conn.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError("snapshot_quick_check_failed")
    return candidate


def snapshot_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source_inventory(path: Path) -> None:
    with sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True) as conn:
        source_tables = {
            str(row[0]) for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
    expected = set(TABLE_ORDER)
    missing = expected - source_tables
    unexpected = source_tables - expected
    if missing or unexpected:
        raise RuntimeError(
            "frozen_snapshot_inventory_mismatch:missing="
            + ",".join(sorted(missing))
            + ";unexpected=" + ",".join(sorted(unexpected))
        )


def verify_write_freeze(
    *,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> None:
    active = []
    for service in WRITER_SERVICES:
        result = runner(
            ["systemctl", "is-active", service],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        state = str(result.stdout or "").strip()
        if state != "inactive":
            active.append(f"{service}:{state or 'unknown'}")
    if active:
        raise RuntimeError("writers_not_inactive:" + ",".join(active))

    fuser = which("fuser")
    if not fuser:
        raise RuntimeError("fuser_required_for_sqlite_holder_check")
    holders = runner(
        [fuser, str(AUTHORITATIVE_SQLITE)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if holders.returncode == 0:
        raise RuntimeError("authoritative_sqlite_has_open_holders")
    if holders.returncode != 1:
        raise RuntimeError("sqlite_holder_check_failed")


def load_production(*, sqlite_path: str, postgres_dsn: str,
                    initial_empty_load: bool, confirmation: str,
                    freeze_check: Callable[[], None] = verify_write_freeze) -> dict[str, Any]:
    validate_confirmation(
        initial_empty_load=initial_empty_load,
        confirmation=confirmation,
    )
    validate_target_dsn(postgres_dsn)
    snapshot = validate_snapshot_path(sqlite_path)
    validate_source_inventory(snapshot)
    frozen_hash = snapshot_sha256(snapshot)
    freeze_check()

    def before_commit() -> None:
        freeze_check()
        if snapshot_sha256(snapshot) != frozen_hash:
            raise RuntimeError("frozen_snapshot_changed_during_load")

    table_report = load_empty_snapshot(
        str(snapshot),
        postgres_dsn,
        expected_database=PRODUCTION_DATABASE,
        expected_tables=TABLE_ORDER,
        before_commit=before_commit,
    )
    if len(table_report) != len(TABLE_ORDER):
        raise RuntimeError("production_load_report_inventory_mismatch")
    return {
        "status": "loaded",
        "mode": "frozen_initial_empty_load",
        "database": PRODUCTION_DATABASE,
        "snapshot": str(snapshot),
        "snapshot_sha256": frozen_hash,
        "tables": len(table_report),
        "rows": sum(int(item["rows"]) for item in table_report),
        "source_missing": sorted(
            item["table"] for item in table_report
            if item["status"] == "source_missing"
        ),
        "table_report": table_report,
    }


def _validate_report_path(path: Path) -> Path:
    target = path.absolute()
    if target.parent != PRODUCTION_SNAPSHOT.parent:
        raise RuntimeError("report_must_be_in_cutover_directory")
    if target.exists() or target.is_symlink():
        raise RuntimeError("refusing_existing_production_load_report")
    return target


def _write_report(path: Path, rendered: str) -> None:
    target = _validate_report_path(path)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(rendered)
        output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--initial-empty-load", action="store_true")
    parser.add_argument("--confirm-frozen", required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    _validate_report_path(args.json_out)
    report = load_production(
        sqlite_path=args.sqlite,
        postgres_dsn=args.postgres,
        initial_empty_load=args.initial_empty_load,
        confirmation=args.confirm_frozen,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    _write_report(args.json_out, rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
