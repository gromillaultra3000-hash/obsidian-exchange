import tempfile
import re
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "postgres"))

from cutover_preflight import inspect


with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    (root / "deploy/postgres").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    (root / "relay/repositories").mkdir(parents=True)
    (root / "relay/core").mkdir(parents=True)
    (root / "deploy/postgres/001_one.sql").write_text("SELECT 1;", encoding="utf-8")
    (root / "deploy/postgres/002_two.sql").write_text("SELECT 2;", encoding="utf-8")
    (root / "deploy/postgres/003_three.sql").write_text("SELECT 3;", encoding="utf-8")
    for version in range(4, 24):
        (root / f"deploy/postgres/{version:03d}_migration.sql").write_text(
            f"SELECT {version};", encoding="utf-8"
        )
    (root / "deploy/postgres/024_e3_paper_evidence.sql").write_text(
        "SELECT 24;", encoding="utf-8"
    )
    def binding(path):
        return {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    production_entries = [
        binding(path) for path in sorted(
            (root / "deploy/postgres").glob("0[0-1][0-9]_*.sql")
        ) if int(path.name[:3]) <= 19
    ] + [
        binding(path) for path in sorted(
            (root / "deploy/postgres").glob("02[0-3]_*.sql")
        )
    ]
    profile = {
        "schemaVersion": "obsidian-postgres-migration-profile.v1",
        "productionCutover": {
            "profileStatus": "FROZEN_001_023_SOURCE_PROFILE",
            "maximumVersion": 23,
            "sourceTableCount": 54,
            "migrations": production_entries,
        },
        "postCutoverDormant": {
            "disposition": "REPOSITORY_PRESENT_PRODUCTION_STATE_UNKNOWN_NOT_REOBSERVED",
            "migrations": [binding(root / "deploy/postgres/024_e3_paper_evidence.sql")],
            "addsTables": ["e3_paper_evidence", "e3_paper_evidence_heads"],
            "addsFunctions": [
                "e3_reject_evidence_mutation()",
                "e3_append_paper_evidence(text,text,text,bigint,text,text,jsonb)",
            ],
        },
        "authority": {
            "migrationApplyAuthorized": False,
            "productionContactAuthorized": False,
            "aclGrantAuthorized": False,
            "principalProvisioningAuthorized": False,
            "actionAllowed": False,
        },
    }
    (root / "deploy/postgres/migration-profile.v1.json").write_text(
        json.dumps(profile), encoding="utf-8"
    )
    (root / "deploy/postgres/reconcile_snapshot.py").write_text(
        "# cutover CLI contract: --critical-invariants\n", encoding="utf-8"
    )
    (root / "deploy/postgres/load_production_snapshot.py").write_text(
        'PRODUCTION_DATABASE = "obsidian_exchange"\n'
        'PRODUCTION_SNAPSHOT = "/var/lib/obsidian-exchange/cutover/'
        'exchange-pre-cutover.db"\n'
        'CONFIRMATION_TOKEN = "FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE"\n'
        '# --initial-empty-load --confirm-frozen\n'
        'load_empty_snapshot(source, target)\n'
        'verify_write_freeze()\n',
        encoding="utf-8",
    )
    good_runbook = (
        "reconcile_snapshot.py --critical-invariants\n"
        "load_production_snapshot.py --initial-empty-load --confirm-frozen "
        "FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE\n"
        "migration_profile.py --profile production-cutover --paths\n"
    )
    (root / "docs/postgresql-cutover-runbook.md").write_text(
        good_runbook, encoding="utf-8"
    )
    (root / "relay/repositories/store.py").write_text(
        "db_runtime.sqlite_connect(path)\n"
        "conn.execute('SELECT 1')\n", encoding="utf-8"
    )
    result = inspect(root)
    assert result["status"] == "GO"
    assert result["critical_invariant_gate_ok"]
    assert result["migration_profile_ok"]
    assert result["migrations"][-1] == "023_migration.sql"
    assert result["dormant_migrations"] == ["024_e3_paper_evidence.sql"]

    # A runbook which can omit the semantic gate cannot receive GO.
    (root / "docs/postgresql-cutover-runbook.md").write_text(
        "reconcile_snapshot.py\n"
        "load_production_snapshot.py FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE\n",
        encoding="utf-8",
    )
    result = inspect(root)
    assert result["status"] == "NO-GO"
    assert not result["critical_invariant_gate_ok"]
    assert not result["critical_invariant_gate_checks"][
        "runbook_requires_critical_invariants"
    ]
    (root / "docs/postgresql-cutover-runbook.md").write_text(
        good_runbook, encoding="utf-8"
    )

    loader = root / "deploy/postgres/load_production_snapshot.py"
    safe_loader = loader.read_text("utf-8")
    loader.write_text(
        safe_loader.replace("FROZEN_INITIAL_LOAD_OBSIDIAN_EXCHANGE", "unsafe"),
        encoding="utf-8",
    )
    result = inspect(root)
    assert result["status"] == "NO-GO"
    assert not result["production_loader_gate_ok"]
    loader.write_text(safe_loader, encoding="utf-8")

    (root / "relay/core/live.py").write_text(
        "db_runtime.sqlite_connect(path)\n", encoding="utf-8"
    )
    result = inspect(root)
    assert result["status"] == "NO-GO"
    assert result["runtime_sqlite_blockers"] == ["relay/core/live.py"]
    assert result["runtime_authoritative_db_residuals"] == [{
        "path": "relay/core/live.py",
        "findings": [{"line": 1, "kind": "direct_sqlite_access"}],
    }]

    # Removing only the wrapper must not turn an adapter with raw SQL green.
    (root / "relay/core/live.py").write_text(
        "def load(cursor):\n"
        "    return cursor.execute('SELECT * FROM orders').fetchall()\n",
        encoding="utf-8",
    )
    result = inspect(root)
    assert result["runtime_sqlite_blockers"] == []
    assert result["status"] == "NO-GO"
    assert result["runtime_authoritative_db_residuals"] == [{
        "path": "relay/core/live.py",
        "findings": [{"line": 2, "kind": "raw_adapter_sql"}],
    }]

    (root / "relay/core/live.py").write_text(
        "def load(cursor, sql):\n"
        "    return cursor.execute(sql).fetchall()\n",
        encoding="utf-8",
    )
    result = inspect(root)
    assert result["runtime_authoritative_db_residuals"][0]["findings"] == [
        {"line": 2, "kind": "dynamic_adapter_db_execute"}
    ]

    # Direct sqlite3 access is independently reported even without db_runtime.
    (root / "relay/core/live.py").write_text(
        "import sqlite3\nconn = sqlite3.connect(path)\n",
        encoding="utf-8",
    )
    result = inspect(root)
    assert result["runtime_sqlite_blockers"] == []
    assert result["runtime_authoritative_db_residuals"][0]["findings"] == [
        {"line": 2, "kind": "direct_sqlite_access"}
    ]

    # Local support-bot routing state is not part of the authoritative DB.
    (root / "relay/core/live.py").write_text(
        "conn = db_runtime.auxiliary_sqlite_connect(path)\n"
        "conn.execute('CREATE TABLE local_messages (id INTEGER)')\n",
        encoding="utf-8",
    )
    assert inspect(root)["status"] == "GO"

    # Explicit inactive/tooling exclusions retain their existing behaviour.
    (root / "bot").mkdir()
    (root / "bot/winback_fix_campaign.py").write_text(
        "import sqlite3\nsqlite3.connect(path).execute('DELETE FROM orders')\n",
        encoding="utf-8",
    )
    assert inspect(root)["status"] == "GO"

    (root / "deploy/postgres/002_two.sql").unlink()
    assert not inspect(root)["migration_sequence_ok"]

print("PostgreSQL cutover preflight checks: OK")

source_flags = set()
for path in (ROOT / "relay" / "repositories").glob("*.py"):
    source_flags.update(
        flag for flag in re.findall(
            r"[A-Z][A-Z0-9_]+_POSTGRES_ENABLED", path.read_text("utf-8")
        )
        # E4 proposal gates are deliberately outside the completed E0
        # production-cutover profile and have their own promotion runbook.
        if not flag.startswith("E4_")
    )
runbook = (ROOT / "docs" / "postgresql-cutover-runbook.md").read_text("utf-8")
missing_flags = sorted(flag for flag in source_flags if f"{flag}=1" not in runbook)
assert not missing_flags, f"runbook is missing PostgreSQL gates: {missing_flags}"
print(f"PostgreSQL cutover runbook gate inventory: {len(source_flags)} flags OK")
