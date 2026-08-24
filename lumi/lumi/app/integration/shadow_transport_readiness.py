"""Fail-closed readiness contract for the dormant KAIROS to LUMI shadow transport."""

from __future__ import annotations

from typing import Any

PROBES_SCHEMA = "shadow-transport-probes.v1"
READINESS_SCHEMA = "shadow-transport-readiness.v1"
CHECKS = (
    ("ED25519_DEPENDENCY", "ed25519Dependency", "ED25519_DEPENDENCY_MISSING"),
    ("KEYRING_CONFIGURED", "keyringConfigured", "KEYRING_NOT_CONFIGURED"),
    ("KEYRING_VALID", "keyringValid", "KEYRING_INVALID"),
    ("ACTIVE_KEY", "activeKeyAvailable", "ACTIVE_KEY_UNAVAILABLE"),
    ("REPLAY_PATH_CONFIGURED", "replayPathConfigured", "REPLAY_PATH_NOT_CONFIGURED"),
    ("REPLAY_PARENT_SAFE", "replayParentSafe", "REPLAY_PARENT_UNSAFE"),
    ("REPLAY_STATE_VALID", "replayStateValid", "REPLAY_STATE_INVALID"),
    ("KAIROS_TRANSPORT_FLAG", "kairosTransportEnabled", "KAIROS_TRANSPORT_DISABLED"),
    ("LUMI_ENDPOINT_FLAG", "lumiEndpointEnabled", "LUMI_ENDPOINT_DISABLED"),
    ("KAIROS_INGRESS_FLAG", "kairosIngressEnabled", "KAIROS_INGRESS_DISABLED"),
    ("RELAY_PRODUCER_FLAG", "relayProducerEnabled", "RELAY_PRODUCER_DISABLED"),
    ("INDEPENDENT_BACKUP", "independentBackup", "INDEPENDENT_BACKUP_UNAVAILABLE"),
)
_PROBE_KEYS = {"schemaVersion", *(field for _, field, _ in CHECKS)}


def assess_readiness(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PROBE_KEYS \
            or value.get("schemaVersion") != PROBES_SCHEMA \
            or any(type(value.get(field)) is not bool for _, field, _ in CHECKS):
        raise ValueError("shadow transport readiness probes differ")
    if value["activeKeyAvailable"] and not value["keyringValid"] \
            or value["keyringValid"] and not value["keyringConfigured"] \
            or value["replayStateValid"] and not value["replayParentSafe"] \
            or value["replayParentSafe"] and not value["replayPathConfigured"]:
        raise ValueError("shadow transport readiness probes are inconsistent")
    checks = [{"checkId": check_id, "ready": value[field]}
              for check_id, field, _ in CHECKS]
    blockers = [blocker for _, field, blocker in CHECKS if not value[field]]
    return {
        "schemaVersion": READINESS_SCHEMA,
        "status": "GO" if not blockers else "NO_GO", "ready": not blockers,
        "checks": checks, "blockers": blockers,
        "executionEffect": "NONE", "actionAllowed": False,
    }
