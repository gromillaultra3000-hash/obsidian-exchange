"""Pure fail-closed evidence contract for independent shadow backups."""

from __future__ import annotations

import re
from typing import Any

PROBES_SCHEMA = "shadow-backup-restore-probes.v1"
EVIDENCE_SCHEMA = "shadow-backup-restore-evidence.v1"
_PROBE_KEYS = {
    "schemaVersion", "sourceDevice", "primaryConfigured", "primaryDevice",
    "secondaryConfigured", "secondaryDevice", "primaryVerified",
    "secondaryVerified", "restoreRehearsed", "sourceHash", "primaryHash",
    "secondaryHash", "restoredHash",
}
CHECKS = (
    ("PRIMARY_CONFIGURED", "primaryConfigured", "PRIMARY_BACKUP_NOT_CONFIGURED"),
    ("SECONDARY_CONFIGURED", "secondaryConfigured", "SECONDARY_BACKUP_NOT_CONFIGURED"),
    ("THREE_FAILURE_DOMAINS", "threeFailureDomains", "BACKUPS_NOT_INDEPENDENT"),
    ("PRIMARY_VERIFIED", "primaryVerified", "PRIMARY_BACKUP_UNVERIFIED"),
    ("SECONDARY_VERIFIED", "secondaryVerified", "SECONDARY_BACKUP_UNVERIFIED"),
    ("RESTORE_REHEARSED", "restoreRehearsed", "RESTORE_NOT_REHEARSED"),
    ("ALL_HASHES_MATCH", "allHashesMatch", "RESTORE_HASH_MISMATCH"),
)
_EVIDENCE_KEYS = {
    "schemaVersion", "status", "ready", "independentBackup", "checks",
    "blockers", "executionEffect", "actionAllowed",
}


def _boolean(value: Any) -> bool:
    return type(value) is bool


def _device(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def assess_backup_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PROBE_KEYS \
            or value.get("schemaVersion") != PROBES_SCHEMA \
            or not _device(value.get("sourceDevice")) \
            or any(not _boolean(value.get(name)) for name in (
                "primaryConfigured", "secondaryConfigured", "primaryVerified",
                "secondaryVerified", "restoreRehearsed")) \
            or not _hash(value.get("sourceHash")):
        raise ValueError("shadow backup evidence probes differ")
    for prefix in ("primary", "secondary"):
        configured = value[f"{prefix}Configured"]
        device = value[f"{prefix}Device"]
        verified = value[f"{prefix}Verified"]
        digest = value[f"{prefix}Hash"]
        if configured != _device(device) \
                or (verified and (not configured or not _hash(digest))) \
                or (not verified and digest is not None):
            raise ValueError("shadow backup evidence copy probes are inconsistent")
    restored = value["restoredHash"]
    if value["restoreRehearsed"]:
        if not value["primaryVerified"] or not value["secondaryVerified"] \
                or not _hash(restored):
            raise ValueError("shadow backup restore probes are inconsistent")
    elif restored is not None:
        raise ValueError("shadow backup restore hash is unexpected")
    devices = (
        value["sourceDevice"], value["primaryDevice"], value["secondaryDevice"])
    three_domains = all(_device(item) for item in devices) \
        and len(set(devices)) == 3
    hashes_match = value["restoreRehearsed"] \
        and value["primaryVerified"] and value["secondaryVerified"] \
        and value["sourceHash"] == value["primaryHash"] \
        == value["secondaryHash"] == restored
    fields = {
        "primaryConfigured": value["primaryConfigured"],
        "secondaryConfigured": value["secondaryConfigured"],
        "threeFailureDomains": three_domains,
        "primaryVerified": value["primaryVerified"],
        "secondaryVerified": value["secondaryVerified"],
        "restoreRehearsed": value["restoreRehearsed"],
        "allHashesMatch": hashes_match,
    }
    checks = [
        {"checkId": check_id, "ready": fields[field]}
        for check_id, field, _ in CHECKS
    ]
    blockers = [
        blocker for item, (_, _, blocker) in zip(checks, CHECKS)
        if not item["ready"]
    ]
    ready = not blockers
    return validate_backup_evidence({
        "schemaVersion": EVIDENCE_SCHEMA,
        "status": "READY" if ready else "NO_GO",
        "ready": ready,
        "independentBackup": ready,
        "checks": checks,
        "blockers": blockers,
        "executionEffect": "NONE",
        "actionAllowed": False,
    })


def validate_backup_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _EVIDENCE_KEYS \
            or value.get("schemaVersion") != EVIDENCE_SCHEMA \
            or value.get("status") not in {"READY", "NO_GO"} \
            or not _boolean(value.get("ready")) \
            or not _boolean(value.get("independentBackup")) \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("shadow backup evidence fields differ")
    checks = value.get("checks")
    expected_ids = [check_id for check_id, _, _ in CHECKS]
    if not isinstance(checks, list) or len(checks) != len(CHECKS) \
            or any(not isinstance(item, dict) or set(item) != {"checkId", "ready"}
                   or not _boolean(item.get("ready")) for item in checks) \
            or [item["checkId"] for item in checks] != expected_ids:
        raise ValueError("shadow backup evidence checks differ")
    expected_blockers = [
        blocker for item, (_, _, blocker) in zip(checks, CHECKS)
        if not item["ready"]
    ]
    ready = not expected_blockers
    if value.get("blockers") != expected_blockers \
            or value["ready"] != ready \
            or value["independentBackup"] != ready \
            or value["status"] != ("READY" if ready else "NO_GO"):
        raise ValueError("shadow backup evidence result is inconsistent")
    return value
