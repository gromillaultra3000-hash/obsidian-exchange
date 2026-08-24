"""Pure fail-closed preflight for reviewing the dormant E4 SQL proposal."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "e4-promotion-preflight.v1"
MAX_EVIDENCE_AGE_MS = 24 * 60 * 60 * 1000
FUTURE_SKEW_MS = 1_000

CHECKS = (
    ("snapshotRehearsalPassed", "SNAPSHOT_REHEARSAL_MISSING"),
    ("tableInventoryVerified", "TABLE_INVENTORY_UNVERIFIED"),
    ("aclInventoryVerified", "ACL_INVENTORY_UNVERIFIED"),
    ("rollbackBoundaryVerified", "ROLLBACK_BOUNDARY_UNVERIFIED"),
    ("handoffGateExplicitlyFalse", "HANDOFF_GATE_NOT_FALSE"),
    ("routeGateExplicitlyFalse", "ROUTE_GATE_NOT_FALSE"),
    ("routeAbsent", "ROUTE_PRESENT"),
    ("activeMigrationAbsent", "ACTIVE_MIGRATION_PRESENT"),
    ("proposalMigrationPresent", "PROPOSAL_MIGRATION_MISSING"),
    ("proposalAclPresent", "PROPOSAL_ACL_MISSING"),
)


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} is invalid")
    return value


def build_promotion_preflight(*, evidence: Mapping[str, Any],
                              evaluated_at_epoch_ms: int) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence is invalid")
    expected = {field for field, _ in CHECKS} | {
        "collectedAtEpochMs", "snapshotSha256", "tableInventorySha256",
        "aclInventorySha256", "rollbackPlanSha256", "proposalMigrationSha256",
        "proposalAclSha256",
    }
    if set(evidence) != expected:
        raise ValueError("evidence fields differ")
    if any(type(evidence.get(field)) is not bool for field, _ in CHECKS):
        raise ValueError("preflight checks must be boolean")
    collected = _epoch(evidence["collectedAtEpochMs"], "collectedAtEpochMs")
    evaluated = _epoch(evaluated_at_epoch_ms, "evaluatedAtEpochMs")
    blockers = [blocker for field, blocker in CHECKS if not evidence[field]]
    age = evaluated - collected
    if age < -FUTURE_SKEW_MS:
        blockers.append("EVIDENCE_FROM_FUTURE")
    elif age > MAX_EVIDENCE_AGE_MS:
        blockers.append("EVIDENCE_STALE")
    digests = {
        field: _digest(evidence[field], field) for field in (
            "snapshotSha256", "tableInventorySha256", "aclInventorySha256",
            "rollbackPlanSha256", "proposalMigrationSha256", "proposalAclSha256")
    }
    eligible = not blockers
    unsigned = {
        "schemaVersion": SCHEMA,
        "status": "PROMOTION_REVIEW_READY_OFFLINE" if eligible else "NO_GO",
        "promotionReviewEligible": eligible,
        "blockers": blockers,
        "checks": [{"checkId": field, "passed": evidence[field]}
                   for field, _ in CHECKS],
        "collectedAtEpochMs": collected,
        "evaluatedAtEpochMs": evaluated,
        **digests,
        "migrationPromotionPerformed": False,
        "productionMigrationApplied": False,
        "productionAclApplied": False,
        "routeConnected": False,
        "featureGatesChanged": False,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "preflightId": "e4pf_" + _hash(unsigned)}


def validate_promotion_preflight(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schemaVersion", "preflightId", "status", "promotionReviewEligible",
        "blockers", "checks", "collectedAtEpochMs", "evaluatedAtEpochMs",
        "snapshotSha256", "tableInventorySha256", "aclInventorySha256",
        "rollbackPlanSha256", "proposalMigrationSha256", "proposalAclSha256",
        "migrationPromotionPerformed", "productionMigrationApplied",
        "productionAclApplied", "routeConnected", "featureGatesChanged",
        "executionEffect", "actionAllowed",
    }
    if not isinstance(value, Mapping) or set(value) != expected \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("status") not in {"PROMOTION_REVIEW_READY_OFFLINE", "NO_GO"} \
            or type(value.get("promotionReviewEligible")) is not bool \
            or any(value.get(field) is not False for field in (
                "migrationPromotionPerformed", "productionMigrationApplied",
                "productionAclApplied", "routeConnected", "featureGatesChanged",
                "actionAllowed")) \
            or value.get("executionEffect") != "NONE":
        raise ValueError("promotion preflight schema is invalid")
    checks = value.get("checks")
    if not isinstance(checks, list) or len(checks) != len(CHECKS) \
            or any(not isinstance(item, dict) or set(item) != {"checkId", "passed"}
                   or type(item.get("passed")) is not bool for item in checks) \
            or [item["checkId"] for item in checks] != [field for field, _ in CHECKS]:
        raise ValueError("promotion preflight checks are invalid")
    expected_blockers = [
        blocker for item, (_, blocker) in zip(checks, CHECKS) if not item["passed"]]
    collected = _epoch(value.get("collectedAtEpochMs"), "collectedAtEpochMs")
    evaluated = _epoch(value.get("evaluatedAtEpochMs"), "evaluatedAtEpochMs")
    age = evaluated - collected
    if age < -FUTURE_SKEW_MS:
        expected_blockers.append("EVIDENCE_FROM_FUTURE")
    elif age > MAX_EVIDENCE_AGE_MS:
        expected_blockers.append("EVIDENCE_STALE")
    for field in ("snapshotSha256", "tableInventorySha256", "aclInventorySha256",
                  "rollbackPlanSha256", "proposalMigrationSha256", "proposalAclSha256"):
        _digest(value.get(field), field)
    eligible = not expected_blockers
    if value.get("blockers") != expected_blockers \
            or value.get("promotionReviewEligible") != eligible \
            or value.get("status") != (
                "PROMOTION_REVIEW_READY_OFFLINE" if eligible else "NO_GO"):
        raise ValueError("promotion preflight result is inconsistent")
    unsigned = dict(value)
    identifier = unsigned.pop("preflightId", None)
    if identifier != "e4pf_" + _hash(unsigned):
        raise ValueError("promotion preflight hash is invalid")
    return dict(value)
