#!/usr/bin/env python3
"""Create, verify and remove a guarded PostgreSQL backup-restore scratch DB."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from verify_runtime_privileges import inspect as inspect_privileges


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_OWNER = "obsidian_migrator"
SAFE_TARGET_MARKERS = ("restore_smoke", "rehearsal", "staging", "contract")
PG_ENV_KEYS = {
    "host": "PGHOST",
    "hostaddr": "PGHOSTADDR",
    "port": "PGPORT",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "dbname": "PGDATABASE",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "options": "PGOPTIONS",
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
    "sslcrl": "PGSSLCRL",
    "ssl_min_protocol_version": "PGSSLMINPROTOCOLVERSION",
    "ssl_max_protocol_version": "PGSSLMAXPROTOCOLVERSION",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}


def guarded_database_name(name: str) -> str:
    candidate = str(name or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", candidate):
        raise RuntimeError("unsafe_restore_database_name")
    if not any(marker in candidate for marker in SAFE_TARGET_MARKERS):
        raise RuntimeError("refusing_non_smoke_database")
    return candidate


def _dsn_database(dsn: str) -> str:
    return str(conninfo_to_dict(dsn).get("dbname") or "").strip()


def _target_dsn(admin_dsn: str, database: str) -> str:
    values = conninfo_to_dict(admin_dsn)
    values["dbname"] = database
    return make_conninfo(**values)


def _client_environment(dsn: str, *, database: str | None = None,
                        role: str | None = None) -> dict[str, str]:
    values = conninfo_to_dict(dsn)
    if database:
        values["dbname"] = database
    if role:
        existing = str(values.get("options") or "").strip()
        values["options"] = f"{existing} -c role={role}".strip()
    environment = os.environ.copy()
    for key, env_key in PG_ENV_KEYS.items():
        value = values.get(key)
        if value not in (None, ""):
            environment[env_key] = str(value)
        else:
            environment.pop(env_key, None)
    return environment


def _client_major(binary: str) -> int:
    result = subprocess.run(
        [binary, "--version"], check=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    match = re.search(r"(\d+)(?:\.\d+)*", result.stdout)
    if not match:
        raise RuntimeError(f"cannot_parse_client_version:{Path(binary).name}")
    return int(match.group(1))


def _run_client(args: list[str], *, environment: dict[str, str],
                stdin: Any = None, stdout: Any = subprocess.PIPE) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            env=environment,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        # Do not echo libpq command lines, environment variables or provider
        # payloads into logs.  The operator can inspect the retained command
        # name and exit code without leaking a DSN/password.
        raise RuntimeError(
            f"postgres_client_failed:{Path(args[0]).name}:exit_{exc.returncode}"
        ) from exc


def _inventory(dsn: str) -> dict[str, Any]:
    inventory: dict[str, Any] = {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname"
        )
        tables = [row[0] for row in cur.fetchall()]
        table_content = {}
        for table in tables:
            cur.execute(sql.SQL(
                "SELECT to_jsonb(item)::text FROM {} AS item ORDER BY 1"
            ).format(sql.Identifier(table)))
            digest = hashlib.sha256()
            count = 0
            while rows := cur.fetchmany(1000):
                for (row_text,) in rows:
                    encoded = row_text.encode("utf-8")
                    digest.update(len(encoded).to_bytes(8, "big"))
                    digest.update(encoded)
                    count += 1
            table_content[table] = {"rows": count, "sha256": digest.hexdigest()}
        inventory["table_content"] = table_content

        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='S' ORDER BY c.relname"
        )
        sequences = [row[0] for row in cur.fetchall()]
        sequence_state = {}
        for sequence in sequences:
            cur.execute(sql.SQL("SELECT last_value,is_called FROM {}").format(
                sql.Identifier(sequence)
            ))
            last_value, is_called = cur.fetchone()
            sequence_state[sequence] = [int(last_value), bool(is_called)]
        inventory["sequence_state"] = sequence_state

        cur.execute(
            "SELECT table_name,column_name,ordinal_position,"
            "format_type(a.atttypid,a.atttypmod),a.attnotnull,"
            "COALESCE(pg_get_expr(d.adbin,d.adrelid),'') "
            "FROM information_schema.columns i "
            "JOIN pg_class c ON c.relname=i.table_name "
            "JOIN pg_namespace n ON n.oid=c.relnamespace AND n.nspname=i.table_schema "
            "JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname=i.column_name "
            "LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum "
            "WHERE i.table_schema='public' ORDER BY table_name,ordinal_position"
        )
        inventory["columns"] = [list(row) for row in cur.fetchall()]

        cur.execute(
            "SELECT c.relname,con.conname,con.contype,pg_get_constraintdef(con.oid) "
            "FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid "
            "JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' ORDER BY c.relname,con.conname"
        )
        inventory["constraints"] = [list(row) for row in cur.fetchall()]

        cur.execute(
            "SELECT tablename,indexname,indexdef FROM pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename,indexname"
        )
        inventory["indexes"] = [list(row) for row in cur.fetchall()]

        cur.execute(
            "SELECT p.proname,pg_get_function_identity_arguments(p.oid),"
            "pg_get_function_result(p.oid),md5(pg_get_functiondef(p.oid)) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='public' ORDER BY p.proname,2"
        )
        inventory["functions"] = [list(row) for row in cur.fetchall()]
    return inventory


def run_smoke(*, source_dsn: str, admin_dsn: str, restore_database: str,
              pg_dump_bin: str = "pg_dump", pg_restore_bin: str = "pg_restore",
              expected_major: int = 17,
              privileges_path: Path | None = None) -> dict[str, Any]:
    restore_database = guarded_database_name(restore_database)
    if restore_database in {_dsn_database(source_dsn), _dsn_database(admin_dsn)}:
        raise RuntimeError("restore_database_must_be_scratch")

    dump_binary = shutil.which(pg_dump_bin)
    restore_binary = shutil.which(pg_restore_bin)
    if not dump_binary or not restore_binary:
        raise RuntimeError("postgresql_client_tools_missing")

    with psycopg.connect(source_dsn) as conn:
        server_major = int(conn.execute(
            "SHOW server_version_num"
        ).fetchone()[0]) // 10000
    versions = {
        "server": server_major,
        "pg_dump": _client_major(dump_binary),
        "pg_restore": _client_major(restore_binary),
    }
    if any(version != expected_major for version in versions.values()):
        raise RuntimeError(f"postgres_major_mismatch:{versions}")

    privileges_path = privileges_path or Path(__file__).with_name(
        "runtime_privileges.sql"
    )
    prepare_path = Path(__file__).with_name("prepare_database.sql")
    target_dsn = _target_dsn(admin_dsn, restore_database)
    created = False
    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            if conn.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s", (restore_database,)
            ).fetchone():
                raise RuntimeError("restore_database_already_exists")
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(restore_database), sql.Identifier(MIGRATION_OWNER)
            ))
            created = True

        with psycopg.connect(target_dsn) as conn:
            conn.execute(prepare_path.read_text(encoding="utf-8"))

        source_inventory = _inventory(source_dsn)
        with tempfile.TemporaryDirectory(prefix="obsidian-pg-restore-") as temp_dir:
            archive = Path(temp_dir) / "backup.dump"
            with archive.open("wb") as output:
                _run_client(
                    [dump_binary, "--format=custom", "--no-owner", "--no-privileges"],
                    environment=_client_environment(source_dsn),
                    stdout=output,
                )
            if archive.stat().st_size <= 0:
                raise RuntimeError("empty_pg_dump_archive")
            with archive.open("rb") as source:
                _run_client(
                    [restore_binary, "--list"],
                    environment=_client_environment(admin_dsn),
                    stdin=source,
                )
            with archive.open("rb") as source:
                _run_client(
                    [restore_binary, "--exit-on-error", "--single-transaction",
                     "--no-owner", "--no-privileges"],
                    environment=_client_environment(
                        admin_dsn, database=restore_database, role=MIGRATION_OWNER
                    ),
                    stdin=source,
                )

        with psycopg.connect(target_dsn) as conn:
            conn.execute(privileges_path.read_text(encoding="utf-8"))

        restored_inventory = _inventory(target_dsn)
        differences = [
            section for section in sorted(source_inventory)
            if source_inventory[section] != restored_inventory.get(section)
        ]
        privilege_report = inspect_privileges(target_dsn)
        status = (
            "match"
            if not differences and privilege_report["status"] == "match"
            else "mismatch"
        )
        return {
            "status": status,
            "versions": versions,
            "restore_database": restore_database,
            "inventory": {
                "tables": len(source_inventory["table_content"]),
                "sequences": len(source_inventory["sequence_state"]),
                "functions": len(source_inventory["functions"]),
            },
            "differences": differences,
            "privileges": privilege_report,
        }
    finally:
        if created:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    sql.Identifier(restore_database)
                ))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--admin", required=True)
    parser.add_argument("--restore-database", required=True)
    parser.add_argument("--pg-dump", default="pg_dump")
    parser.add_argument("--pg-restore", default="pg_restore")
    parser.add_argument("--expected-major", type=int, default=17)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    report = run_smoke(
        source_dsn=args.source,
        admin_dsn=args.admin,
        restore_database=args.restore_database,
        pg_dump_bin=args.pg_dump,
        pg_restore_bin=args.pg_restore,
        expected_major=args.expected_major,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    if args.json_out:
        args.json_out.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "match" else 2


if __name__ == "__main__":
    raise SystemExit(main())
