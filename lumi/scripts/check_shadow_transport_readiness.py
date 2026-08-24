#!/usr/bin/env python3
"""Read-only production probe for dormant E2 shadow transport prerequisites."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Mapping

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lumi.app.integration.shadow_public_keyring import load_keyring, resolve_public_key
from lumi.app.integration.shadow_backup_evidence import validate_backup_evidence
from lumi.app.integration.shadow_replay_ledger import validate_snapshot
from lumi.app.integration.shadow_replay_store import MAX_STATE_BYTES
from lumi.app.integration.shadow_transport_readiness import PROBES_SCHEMA, assess_readiness

MAX_EVIDENCE_BYTES = 16 * 1024


def _enabled(environment: Mapping[str, str], name: str) -> bool:
    return str(environment.get(name) or "0") == "1"


def _safe_replay(path: Path) -> tuple[bool, bool]:
    try:
        parent = path.parent.lstat()
        parent_safe = stat.S_ISDIR(parent.st_mode) and not stat.S_ISLNK(parent.st_mode) \
            and not parent.st_mode & 0o022 and os.access(path.parent, os.W_OK)
    except OSError:
        return False, False
    if not parent_safe:
        return False, False
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) \
                or info.st_size > MAX_STATE_BYTES or info.st_mode & 0o077:
            return True, False
        value = json.loads(path.read_bytes())
        validate_snapshot(value)
    except Exception:
        return True, False
    return True, True


def _independent_backup_evidence(environment: Mapping[str, str]) -> bool:
    raw = str(environment.get("LUMI_E2_SHADOW_BACKUP_EVIDENCE") or "").strip()
    if not raw:
        return False
    path = Path(raw)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) \
                or info.st_uid != 0 or info.st_gid != os.getgid() \
                or stat.S_IMODE(info.st_mode) != 0o640 \
                or info.st_size > MAX_EVIDENCE_BYTES:
            return False
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            actual = os.fstat(fd)
            if actual.st_dev != info.st_dev or actual.st_ino != info.st_ino \
                    or actual.st_size != info.st_size:
                return False
            raw_value = os.read(fd, MAX_EVIDENCE_BYTES + 1)
        finally:
            os.close(fd)
        evidence = validate_backup_evidence(json.loads(raw_value))
        return evidence["independentBackup"] is True
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def probe_runtime(
    *, environment: Mapping[str, str], now_epoch: int,
    dependency_available: bool,
) -> dict:
    keyring_raw = str(environment.get("LUMI_E2_SHADOW_KEYRING") or "").strip()
    keyring_configured = bool(keyring_raw)
    keyring_valid = False
    active_key = False
    if keyring_configured:
        try:
            keyring = load_keyring(Path(keyring_raw))
            keyring_valid = True
            active = [item for item in keyring["keys"] if item["status"] == "ACTIVE"]
            if len(active) == 1:
                resolve_public_key(keyring, key_id=active[0]["keyId"], at_epoch=now_epoch)
                active_key = True
        except ValueError:
            pass

    replay_raw = str(environment.get("LUMI_E2_SHADOW_REPLAY_FILE") or "").strip()
    replay_configured = bool(replay_raw)
    replay_parent_safe, replay_valid = (False, False)
    if replay_configured:
        replay_parent_safe, replay_valid = _safe_replay(Path(replay_raw))
    probes = {
        "schemaVersion": PROBES_SCHEMA,
        "ed25519Dependency": dependency_available,
        "keyringConfigured": keyring_configured, "keyringValid": keyring_valid,
        "activeKeyAvailable": active_key,
        "replayPathConfigured": replay_configured,
        "replayParentSafe": replay_parent_safe, "replayStateValid": replay_valid,
        "kairosTransportEnabled": _enabled(environment, "KAIROS_E2_LUMI_TRANSPORT_ENABLED"),
        "lumiEndpointEnabled": _enabled(environment, "LUMI_E2_SHADOW_ENDPOINT_ENABLED"),
        "kairosIngressEnabled": _enabled(environment, "KAIROS_E2_SHADOW_INGRESS_ENABLED"),
        "relayProducerEnabled": _enabled(environment, "RELAY_E2_SHADOW_PRODUCER_ENABLED"),
        "independentBackup": _independent_backup_evidence(environment),
    }
    return assess_readiness(probes)


def main() -> int:
    try:
        dependency = importlib.util.find_spec(
            "cryptography.hazmat.primitives.asymmetric.ed25519") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        dependency = False
    try:
        result = probe_runtime(
            environment=os.environ, now_epoch=int(time.time()),
            dependency_available=dependency)
    except Exception:
        result = {
            "schemaVersion": "shadow-transport-readiness.v1", "status": "NO_GO",
            "ready": False, "checks": [], "blockers": ["PROBE_FAILED"],
            "executionEffect": "NONE", "actionAllowed": False,
        }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
