#!/usr/bin/env python3
"""Produce READY evidence only after real independent backup/restore verification."""
from __future__ import annotations
import argparse, json, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for item in (str(ROOT / "kairos"), str(ROOT / "lumi")):
    if item not in sys.path: sys.path.insert(0, item)
from app.shadow_journal_operations import ShadowJournalOperations
from lumi.app.integration.shadow_backup_evidence import assess_backup_evidence

def _device(path: Path) -> int:
    info = path.lstat()
    if not path.is_dir() or path.is_symlink(): raise RuntimeError("unsafe storage directory")
    return info.st_dev

def produce(journal: Path, primary: Path, secondary: Path, scratch: Path) -> dict:
    devices = (_device(journal.parent), _device(primary), _device(secondary))
    if len(set(devices)) != 3: raise RuntimeError("source and backups require three devices")
    _device(scratch)
    operations = ShadowJournalOperations(journal)
    replay = operations.verify_all()
    if replay["recordCount"] == 0: raise RuntimeError("empty journal cannot produce READY evidence")
    backups = operations.backup_twice(primary, secondary)
    restored = operations.rehearse_restore(Path(backups[0]["bundle"]), scratch)
    first, second = backups[0]["manifestHash"], backups[1]["manifestHash"]
    evidence = assess_backup_evidence({
        "schemaVersion":"shadow-backup-restore-probes.v1", "sourceDevice":devices[0],
        "primaryConfigured":True, "primaryDevice":devices[1],
        "secondaryConfigured":True, "secondaryDevice":devices[2],
        "primaryVerified":backups[0]["replay"] == replay,
        "secondaryVerified":backups[1]["replay"] == replay,
        "restoreRehearsed":restored["replay"] == replay,
        "sourceHash":first, "primaryHash":first, "secondaryHash":second,
        "restoredHash":first})
    if not evidence["ready"]: raise RuntimeError("backup evidence is not READY")
    return evidence

def atomic_write(path: Path, value: dict, *, group: int) -> None:
    parent = path.parent.resolve()
    if not parent.is_dir() or path.is_symlink(): raise RuntimeError("unsafe evidence target")
    fd, temporary = tempfile.mkstemp(prefix=".shadow-backup-evidence-", dir=parent)
    try:
        os.fchmod(fd, 0o640); os.fchown(fd, 0, group)
        os.write(fd, json.dumps(value, sort_keys=True, separators=(",", ":")).encode()+b"\n")
        os.fsync(fd); os.close(fd); fd = -1; os.replace(temporary, path)
        directory = os.open(parent, os.O_RDONLY); os.fsync(directory); os.close(directory)
    finally:
        if fd >= 0: os.close(fd)
        if os.path.exists(temporary): os.unlink(temporary)

def main() -> int:
    parser=argparse.ArgumentParser()
    for name in ("journal","primary","secondary","scratch","output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--group", type=int, required=True); args=parser.parse_args()
    try:
        evidence=produce(args.journal,args.primary,args.secondary,args.scratch)
        atomic_write(args.output,evidence,group=args.group)
    except Exception as exc:
        print(json.dumps({"schemaVersion":"shadow-backup-evidence-producer.v1","status":"NO_GO","reason":str(exc),"actionAllowed":False},sort_keys=True)); return 1
    print(json.dumps(evidence,sort_keys=True)); return 0
if __name__ == "__main__": raise SystemExit(main())
