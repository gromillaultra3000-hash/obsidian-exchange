#!/usr/bin/env python3
"""Export one read-only snapshot, fingerprint it, and pg_dump that exact snapshot."""
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from psycopg import sql
from check_b64_notification_migration import (
    inspect as inspect_dirty_data,
    valid_snapshot_scan,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_CONTAINER = "obsidian-postgres"
CATALOG_SQL = ROOT / "deploy/postgres/b64_catalog_security_fingerprint.sql"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_path() -> Path:
    path = Path(os.environ.get("B64_ARCHIVE_PATH", ""))
    if not path.is_absolute() or not str(path).startswith("/tmp/b64-"):
        raise RuntimeError("unsafe_b64_archive_path")
    if path.exists() or not path.parent.is_dir():
        raise RuntimeError("b64_archive_path_not_new")
    if stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
        raise RuntimeError("b64_archive_parent_not_0700")
    return path


def _write_manifest(entries: list[list[object]], env_name: str) -> None:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return
    path = Path(raw)
    if (not path.is_absolute() or not str(path).startswith("/tmp/b64-")
            or path.exists() or path.parent.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_b64_manifest_path")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(entries, output, separators=(",", ":"))


def _catalog_fingerprint(conn) -> tuple[list[list[object]], str]:
    source = CATALOG_SQL.read_text(encoding="utf-8")
    cursor = conn.execute(source)
    rows = None
    while True:
        if cursor.description:
            rows = cursor.fetchall()
        if not cursor.nextset():
            break
    if rows is None:
        raise RuntimeError("b64_catalog_fingerprint_missing_result")
    expected = {
        "column_acl", "default_acl", "membership", "db_role_setting",
        "relation_security", "constraint_security", "index_security",
        "trigger_security", "function_security", "policy_security",
        "sequence_definition", "type_security", "extension_security",
    }
    entries = [[version, section, int(count), digest]
               for version, section, count, digest in rows]
    if (len(entries) != len(expected)
            or {row[1] for row in entries} != expected
            or any(row[0] != "b64-catalog-security-fingerprint.v2" for row in entries)
            or any(len(row[3]) != 64 for row in entries)):
        raise RuntimeError("b64_catalog_fingerprint_shape_invalid")
    encoded = json.dumps(entries, separators=(",", ":")).encode()
    return entries, hashlib.sha256(encoded).hexdigest()


def _table_fingerprint(conn) -> tuple[list[list[object]], str]:
    tables = [row[0] for row in conn.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN('r','p') ORDER BY c.relname"
    ).fetchall()]
    entries = []
    for table in tables:
        count, digest = conn.execute(sql.SQL(
            "SELECT count(*),encode(sha256(convert_to(COALESCE("
            "string_agg(to_jsonb(t)::text,chr(10) ORDER BY to_jsonb(t)::text),''),'UTF8')),'hex') "
            "FROM public.{} t"
        ).format(sql.Identifier(table))).fetchone()
        entries.append([table, int(count), digest])
    encoded = json.dumps(entries, separators=(",", ":")).encode()
    return entries, hashlib.sha256(encoded).hexdigest()


def run() -> dict:
    import psycopg
    dsn = os.environ.get("B64_READONLY_DATABASE_URL", "").strip()
    expected_db = os.environ.get("B64_EXPECTED_DATABASE", "").strip()
    if not dsn or not expected_db:
        raise RuntimeError("b64_source_configuration_missing")
    archive = _archive_path()
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        conn.execute("SET LOCAL statement_timeout='60s'")
        target = conn.execute(
            "SELECT current_database()=%s,current_setting('server_version_num')::integer/10000,"
            "current_setting('transaction_read_only'),pg_export_snapshot(),"
            "(SELECT system_identifier::text FROM pg_control_system())", (expected_db,),
        ).fetchone()
        if target[0] is not True or target[1] != 17 or target[2] != "on":
            raise RuntimeError("b64_source_attestation_failed")
        snapshot, cluster_id = target[3], target[4]
        dirty_data = inspect_dirty_data(conn, configure_transaction=False)
        if not valid_snapshot_scan(dirty_data):
            raise RuntimeError("b64_dirty_data_scan_failed")
        table_entries, table_sha = _table_fingerprint(conn)
        catalog_entries, catalog_sha = _catalog_fingerprint(conn)
        _write_manifest(table_entries, "B64_FINGERPRINT_MANIFEST_PATH")
        _write_manifest(catalog_entries, "B64_CATALOG_MANIFEST_PATH")
        descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output:
                result = subprocess.run(
                    ["docker", "exec", SOURCE_CONTAINER, "pg_dump", "-U", "postgres",
                     "-d", expected_db, "--format=custom", "--no-owner", "--no-privileges",
                     "--snapshot", snapshot], stdout=output, stderr=subprocess.PIPE,
                )
        except Exception:
            archive.unlink(missing_ok=True)
            raise
        if result.returncode or archive.stat().st_size <= 0:
            archive.unlink(missing_ok=True)
            raise RuntimeError(f"b64_pg_dump_failed:exit_{result.returncode}")
    return {
        "schemaVersion": "b64-snapshot-dump.v1", "status": "CREATED",
        "sourceClusterSha256": hashlib.sha256(cluster_id.encode()).hexdigest(),
        "tables": len(table_entries), "tableFingerprintSha256": table_sha,
        "catalogSections": len(catalog_entries),
        "catalogFingerprintSha256": catalog_sha,
        "dirtyDataScan": dirty_data,
        "archiveBytes": archive.stat().st_size,
        "archiveSha256": _file_sha256(archive),
        "containsProductionData": True, "retention": "DELETE_AFTER_REHEARSAL",
    }


def main() -> int:
    try:
        print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "errorType": type(exc).__name__}, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.exit(main())
