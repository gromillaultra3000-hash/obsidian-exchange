#!/usr/bin/env python3
"""Static GO/NO-GO guard for an authoritative PostgreSQL cutover."""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

from migration_profile import MigrationProfileError, load_profile


ACTIVE_SCOPES = ("bot", "relay", "relay-fastapi", "payment", "monitoring", "support_bot")
EXCLUDED = {
    "relay/core/db_runtime.py",
    "bot/winback_fix_campaign.py",
    "bot/utils/security.py",
    "relay/utils/security.py",
    # Superseded entrypoints and one-shot migration helpers. None is referenced
    # by the production systemd units; keep this list explicit so a new runtime
    # module cannot silently inherit an exemption.
    "relay/app.py",
    "relay/main.py",
    "relay/main_docker.py",
    "relay-fastapi/main_bot.py",
    "relay-fastapi/migrate_webaccounts.py",
    "relay-fastapi/pay_handler.py",
    "relay-fastapi/relay_main.py",
    "relay-fastapi/utils/security.py",
}
SQLITE_CALL = re.compile(r"\b(?:db_runtime|_db_runtime)\.sqlite_connect\s*\(")
MIGRATION_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
SQL_START = re.compile(
    r"^\s*(?:--[^\n]*\n\s*)*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|"
    r"REPLACE|PRAGMA|VACUUM|WITH)\b",
    re.IGNORECASE,
)


def _call_name(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _literal_text(node: ast.AST) -> str | None:
    """Return statically visible text, including adjacent/concatenated literals."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_text(node.left)
        right = _literal_text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _authoritative_residuals(path: Path, source: str) -> list[dict]:
    """Find DB access that cannot be hidden by deleting a connection wrapper.

    Auxiliary SQLite is deliberately local state (for example support-bot
    message routing), so neither its connector nor SQL executed in a module
    which uses only that connector belongs to the exchange DB cutover.
    """
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [{"line": exc.lineno or 0, "kind": "syntax_error"}]

    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = [_call_name(node.func) for node in calls]
    has_auxiliary = any(name.endswith("auxiliary_sqlite_connect") for name in names)
    has_authoritative_connect = any(
        name.endswith("sqlite_connect") and not name.endswith("auxiliary_sqlite_connect")
        or name in {"sqlite3.connect", "connect"}
        for name in names
    )
    auxiliary_only = has_auxiliary and not has_authoritative_connect

    findings: list[dict] = []
    for node, name in zip(calls, names):
        if name.endswith("auxiliary_sqlite_connect"):
            continue
        if (name.endswith("sqlite_connect") or name in {"sqlite3.connect", "connect"}):
            findings.append({"line": node.lineno, "kind": "direct_sqlite_access"})
            continue
        if auxiliary_only or name.rsplit(".", 1)[-1] not in {
            "execute", "executemany", "executescript",
        } or not node.args:
            continue
        sql = _literal_text(node.args[0])
        if sql is None:
            findings.append({"line": node.lineno, "kind": "dynamic_adapter_db_execute"})
        elif SQL_START.search(sql):
            findings.append({"line": node.lineno, "kind": "raw_adapter_sql"})
    return sorted(findings, key=lambda item: (item["line"], item["kind"]))


def inspect(root: Path) -> dict:
    blockers = []
    residuals = []
    for scope in ACTIVE_SCOPES:
        base = root / scope
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if (
                rel in EXCLUDED
                or "/venv/" in f"/{rel}/"
                or any("gold_" in part for part in path.parts)
            ):
                continue
            if rel.startswith("relay/repositories/"):
                continue
            source = path.read_text("utf-8")
            if SQLITE_CALL.search(source):
                blockers.append(rel)
            findings = _authoritative_residuals(path, source)
            if findings:
                residuals.append({"path": rel, "findings": findings})

    migration_dir = root / "deploy" / "postgres"
    migration_profile_error = None
    try:
        migration_profile = load_profile(root)
    except MigrationProfileError as exc:
        migration_profile = None
        migration_profile_error = str(exc)
    migration_profile_ok = migration_profile is not None
    if migration_profile is None:
        production_migrations = []
        dormant_migrations = []
    else:
        production_migrations = [
            Path(item["path"]).name
            for item in migration_profile["productionCutover"]["migrations"]
        ]
        dormant_migrations = [
            Path(item["path"]).name
            for item in migration_profile["postCutoverDormant"]["migrations"]
        ]
    migration_sequence_ok = migration_profile_ok

    reconciler_path = migration_dir / "reconcile_snapshot.py"
    production_loader_path = migration_dir / "load_production_snapshot.py"
    runbook_path = root / "docs" / "postgresql-cutover-runbook.md"
    reconciler_source = (
        reconciler_path.read_text("utf-8") if reconciler_path.is_file() else ""
    )
    runbook_source = runbook_path.read_text("utf-8") if runbook_path.is_file() else ""
    production_loader_source = (
        production_loader_path.read_text("utf-8")
        if production_loader_path.is_file() else ""
    )
    critical_invariant_gate_checks = {
        "reconciler_supports_critical_invariants": (
            "--critical-invariants" in reconciler_source
        ),
        "runbook_requires_critical_invariants": (
            "reconcile_snapshot.py" in runbook_source
            and "--critical-invariants" in runbook_source
        ),
    }
    critical_invariant_gate_ok = all(critical_invariant_gate_checks.values())
    production_loader_gate_checks = {
        "loader_requires_exact_database": (
            'PRODUCTION_DATABASE = "obsidian_exchange"' in production_loader_source
        ),
        "loader_requires_exact_snapshot": (
            "/var/lib/obsidian-exchange/cutover/exchange-pre-cutover.db"
            in production_loader_source
        ),
        "loader_requires_frozen_confirmation": (
            "FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE" in production_loader_source
            and "--initial-empty-load" in production_loader_source
            and "--confirm-frozen" in production_loader_source
        ),
        "loader_requires_empty_atomic_target": (
            "load_empty_snapshot" in production_loader_source
            and "verify_write_freeze" in production_loader_source
            and "TRUNCATE" not in production_loader_source
        ),
        "runbook_requires_production_loader": (
            "load_production_snapshot.py" in runbook_source
            and "FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE" in runbook_source
        ),
        "runbook_requires_exact_migration_profile": (
            "migration_profile.py" in runbook_source
            and "--profile production-cutover --paths" in runbook_source
        ),
    }
    production_loader_gate_ok = all(production_loader_gate_checks.values())

    return {
        "status": (
            "GO"
            if (
                not blockers
                and not residuals
                and migration_profile_ok
                and critical_invariant_gate_ok
                and production_loader_gate_ok
            )
            else "NO-GO"
        ),
        "runtime_sqlite_blockers": blockers,
        "runtime_sqlite_blocker_count": len(blockers),
        "runtime_authoritative_db_residuals": residuals,
        "runtime_authoritative_db_residual_count": sum(
            len(item["findings"]) for item in residuals
        ),
        "migration_profile_ok": migration_profile_ok,
        "migration_profile_error": migration_profile_error,
        "migration_sequence_ok": migration_sequence_ok,
        "migrations": production_migrations,
        "dormant_migrations": dormant_migrations,
        "critical_invariant_gate_ok": critical_invariant_gate_ok,
        "critical_invariant_gate_checks": critical_invariant_gate_checks,
        "production_loader_gate_ok": production_loader_gate_ok,
        "production_loader_gate_checks": production_loader_gate_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = inspect(args.root.resolve())
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
        print(f"migrations: {len(result['migrations'])}, contiguous={result['migration_sequence_ok']}")
        print(
            "critical invariant gate: "
            f"configured={result['critical_invariant_gate_ok']}"
        )
        for check, passed in result["critical_invariant_gate_checks"].items():
            print(f"  - {check}: {passed}")
        print(
            "production loader gate: "
            f"configured={result['production_loader_gate_ok']}"
        )
        for check, passed in result["production_loader_gate_checks"].items():
            print(f"  - {check}: {passed}")
        print(f"runtime SQLite blockers: {result['runtime_sqlite_blocker_count']}")
        for path in result["runtime_sqlite_blockers"]:
            print(f"  - {path}")
        print(
            "authoritative DB residuals: "
            f"{result['runtime_authoritative_db_residual_count']}"
        )
        for item in result["runtime_authoritative_db_residuals"]:
            details = ", ".join(
                f"{finding['kind']}:{finding['line']}" for finding in item["findings"]
            )
            print(f"  - {item['path']}: {details}")
    raise SystemExit(0 if result["status"] == "GO" else 2)


if __name__ == "__main__":
    main()
