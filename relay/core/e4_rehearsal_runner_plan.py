"""Non-executing plan for an isolated E4 full-snapshot rehearsal runner."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA = "e4-full-snapshot-rehearsal-runner-plan.v1"
TARGET_CLASS = "ISOLATED_DISPOSABLE_POSTGRESQL"
PRECONDITIONS = (
    "EXPLICIT_OWNER_APPROVAL",
    "DISPOSABLE_TARGET_IDENTITY_VERIFIED",
    "TARGET_ABSENT_BEFORE_START",
    "NO_PRODUCTION_NETWORK_ROUTE",
    "NO_PRODUCTION_CREDENTIALS_OR_SECRETS",
    "ENCRYPTED_SNAPSHOT_COPY_DIGEST_VERIFIED",
    "EVIDENCE_MANIFEST_VERIFIED",
    "TEARDOWN_TARGET_VERIFIED",
)
STEPS = (
    ("VERIFY_TARGET_ABSENT", "READ_ONLY"),
    ("VERIFY_MANIFEST_AND_SNAPSHOT_DIGESTS", "READ_ONLY"),
    ("CREATE_DISPOSABLE_POSTGRESQL_TARGET", "REVERSIBLE_FIXTURE_MUTATION"),
    ("LOAD_SNAPSHOT_INTO_DISPOSABLE_TARGET", "BOUNDED_FIXTURE_MUTATION"),
    ("REVOKE_POST_LOAD_WRITE_CAPABILITY", "REVERSIBLE_FIXTURE_MUTATION"),
    ("VERIFY_FULL_SNAPSHOT_MATCH", "READ_ONLY"),
    ("CAPTURE_TABLE_INVENTORY", "READ_ONLY"),
    ("CAPTURE_ACL_INVENTORY", "READ_ONLY"),
    ("VERIFY_ROUTE_GATES_AND_MIGRATION_ABSENCE", "READ_ONLY"),
    ("NORMALIZE_SECRET_FREE_EVIDENCE", "READ_ONLY"),
    ("DESTROY_DISPOSABLE_TARGET_AND_STAGED_SNAPSHOT", "ROLLBACK_MUTATION"),
    ("VERIFY_TARGET_AND_SNAPSHOT_ABSENT", "READ_ONLY"),
)
_KEYS = {
    "schemaVersion", "planId", "evidenceManifestSha256", "targetClass",
    "snapshotClass", "preconditions", "steps", "invocationLimit",
    "productionDatabaseContactAllowed", "productionNetworkAllowed",
    "productionCredentialsAllowed", "proposalApplicationAllowed",
    "postLoadWritesAllowed", "persistentTargetAllowed", "automaticRetryAllowed",
    "ownerApprovalRequired", "executionAuthorized", "containsConnectionMaterial",
    "executionEffect", "promotionAllowed", "actionAllowed",
}


def _digest(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("evidenceManifestSha256 is invalid")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def build_rehearsal_runner_plan(*, evidence_manifest_sha256: str) -> dict[str, Any]:
    unsigned = {
        "schemaVersion": SCHEMA,
        "evidenceManifestSha256": _digest(evidence_manifest_sha256),
        "targetClass": TARGET_CLASS,
        "snapshotClass": "PREEXISTING_ENCRYPTED_IMMUTABLE_SNAPSHOT_COPY",
        "preconditions": [{"checkId": item, "required": True}
                          for item in PRECONDITIONS],
        "steps": [{"sequence": index, "stepId": step, "effect": effect,
                   "automaticRetryAllowed": False}
                  for index, (step, effect) in enumerate(STEPS, start=1)],
        "invocationLimit": 1,
        "productionDatabaseContactAllowed": False,
        "productionNetworkAllowed": False,
        "productionCredentialsAllowed": False,
        "proposalApplicationAllowed": False,
        "postLoadWritesAllowed": False,
        "persistentTargetAllowed": False,
        "automaticRetryAllowed": False,
        "ownerApprovalRequired": True,
        "executionAuthorized": False,
        "containsConnectionMaterial": False,
        "executionEffect": "NONE",
        "promotionAllowed": False,
        "actionAllowed": False,
    }
    return {**unsigned, "planId": "e4rrp_" + _hash(unsigned)}


def validate_rehearsal_runner_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _KEYS \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("targetClass") != TARGET_CLASS \
            or value.get("snapshotClass") != "PREEXISTING_ENCRYPTED_IMMUTABLE_SNAPSHOT_COPY" \
            or value.get("invocationLimit") != 1 \
            or value.get("ownerApprovalRequired") is not True \
            or any(value.get(field) is not False for field in (
                "productionDatabaseContactAllowed", "productionNetworkAllowed",
                "productionCredentialsAllowed", "proposalApplicationAllowed",
                "postLoadWritesAllowed", "persistentTargetAllowed",
                "automaticRetryAllowed", "executionAuthorized",
                "containsConnectionMaterial", "promotionAllowed", "actionAllowed")) \
            or value.get("executionEffect") != "NONE":
        raise ValueError("E4 rehearsal runner plan schema is invalid")
    rebuilt = build_rehearsal_runner_plan(
        evidence_manifest_sha256=value["evidenceManifestSha256"])
    if rebuilt != dict(value):
        raise ValueError("E4 rehearsal runner plan differs from frozen workflow")
    return rebuilt
