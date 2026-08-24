"""Read-only normalizer for isolated E4 full-snapshot rehearsal evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from core.e4_promotion_preflight import build_promotion_preflight

MANIFEST_SCHEMA = "e4-full-snapshot-rehearsal-manifest.v1"
RESULT_SCHEMA = "e4-rehearsal-evidence-collection.v1"
TARGET_CLASS = "ISOLATED_DISPOSABLE_POSTGRESQL"


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def collect_rehearsal_evidence(*, manifest: Mapping[str, Any],
                               observation: Mapping[str, Any],
                               collected_at_epoch_ms: int) -> dict[str, Any]:
    """Normalize already measured, secret-free evidence; performs no probe or write."""
    manifest_fields = {
        "schemaVersion", "manifestId", "targetClass", "productionNetworkAllowed",
        "productionCredentialsAllowed", "writesAllowed", "proposalMigrationPath",
        "proposalMigrationSha256", "proposalAclPath", "proposalAclSha256",
        "rollbackPlanPath", "rollbackPlanSha256", "requiredChecks",
    }
    observation_fields = {
        "targetClass", "targetFingerprintSha256", "snapshotSha256",
        "tableInventorySha256", "aclInventorySha256", "fullSnapshotMatched",
        "tableInventoryCaptured", "aclInventoryCaptured", "rollbackBoundaryVerified",
        "handoffGateExplicitlyFalse", "routeGateExplicitlyFalse", "confirmRouteAbsent",
        "active025MigrationAbsent", "proposalMigrationSha256", "proposalAclSha256",
        "rollbackPlanSha256", "connectionMaterialPresent", "productionContacted",
        "writePerformed",
    }
    if not isinstance(manifest, Mapping) or set(manifest) != manifest_fields \
            or manifest.get("schemaVersion") != MANIFEST_SCHEMA \
            or manifest.get("targetClass") != TARGET_CLASS \
            or any(manifest.get(field) is not False for field in (
                "productionNetworkAllowed", "productionCredentialsAllowed", "writesAllowed")):
        raise ValueError("rehearsal manifest is invalid")
    if not isinstance(observation, Mapping) or set(observation) != observation_fields:
        raise ValueError("rehearsal observation fields differ")
    boolean_fields = observation_fields - {
        "targetClass", "targetFingerprintSha256", "snapshotSha256",
        "tableInventorySha256", "aclInventorySha256", "proposalMigrationSha256",
        "proposalAclSha256", "rollbackPlanSha256",
    }
    if any(type(observation[field]) is not bool for field in boolean_fields):
        raise ValueError("rehearsal observation checks must be boolean")
    digests = {field: _digest(observation[field], field) for field in (
        "targetFingerprintSha256", "snapshotSha256", "tableInventorySha256",
        "aclInventorySha256", "proposalMigrationSha256", "proposalAclSha256",
        "rollbackPlanSha256")}
    for field in ("proposalMigrationSha256", "proposalAclSha256", "rollbackPlanSha256"):
        if digests[field] != _digest(manifest[field], field):
            raise ValueError(f"{field} differs from frozen manifest")
    safe_target = observation["targetClass"] == TARGET_CLASS \
        and not observation["connectionMaterialPresent"] \
        and not observation["productionContacted"] \
        and not observation["writePerformed"]
    evidence = {
        "collectedAtEpochMs": collected_at_epoch_ms,
        "snapshotSha256": digests["snapshotSha256"],
        "tableInventorySha256": digests["tableInventorySha256"],
        "aclInventorySha256": digests["aclInventorySha256"],
        "rollbackPlanSha256": digests["rollbackPlanSha256"],
        "proposalMigrationSha256": digests["proposalMigrationSha256"],
        "proposalAclSha256": digests["proposalAclSha256"],
        "snapshotRehearsalPassed": safe_target and observation["fullSnapshotMatched"],
        "tableInventoryVerified": safe_target and observation["tableInventoryCaptured"],
        "aclInventoryVerified": safe_target and observation["aclInventoryCaptured"],
        "rollbackBoundaryVerified": observation["rollbackBoundaryVerified"],
        "handoffGateExplicitlyFalse": observation["handoffGateExplicitlyFalse"],
        "routeGateExplicitlyFalse": observation["routeGateExplicitlyFalse"],
        "routeAbsent": observation["confirmRouteAbsent"],
        "activeMigrationAbsent": observation["active025MigrationAbsent"],
        "proposalMigrationPresent": True,
        "proposalAclPresent": True,
    }
    preflight = build_promotion_preflight(
        evidence=evidence, evaluated_at_epoch_ms=collected_at_epoch_ms)
    unsigned = {
        "schemaVersion": RESULT_SCHEMA, "manifestId": manifest["manifestId"],
        "targetClass": observation["targetClass"],
        "targetFingerprintSha256": digests["targetFingerprintSha256"],
        "connectionMaterialRedacted": not observation["connectionMaterialPresent"],
        "productionContacted": observation["productionContacted"],
        "writePerformed": observation["writePerformed"], "status": preflight["status"],
        "preflight": preflight, "executionEffect": "NONE",
        "promotionPerformed": False, "actionAllowed": False,
    }
    return {**unsigned, "collectionId": "e4rec_" + _hash(unsigned)}
