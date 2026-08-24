import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))

from backup_restore_smoke import guarded_database_name


for accepted in (
    "obsidian_restore_smoke_20260810",
    "restore_contract_1",
    "obsidian_rehearsal_restore",
):
    assert guarded_database_name(accepted) == accepted

for rejected in (
    "obsidian_exchange",
    "postgres",
    "template1",
    "Restore_Smoke",
    "restore-smoke",
    "restore_smoke;drop database postgres",
    "",
):
    try:
        guarded_database_name(rejected)
    except RuntimeError:
        pass
    else:
        raise AssertionError(f"unsafe restore target accepted: {rejected!r}")

print("PostgreSQL backup/restore destructive-target guard: OK")
