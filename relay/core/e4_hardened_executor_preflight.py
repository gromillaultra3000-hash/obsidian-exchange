"""Pure readiness assessment for a future hardened E4 executor.

The assessor validates a closed, secret-free proof shape for the frozen
12-step plan.  It performs no probes and has no Docker, PostgreSQL, network,
filesystem, credential or process-launch surface.  Even a complete mechanical
proof cannot produce execution authority; the authenticated trust/clock/replay
gate remains a separate prerequisite.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from core.e4_rehearsal_runner_plan import (
    STEPS, TARGET_CLASS, validate_rehearsal_runner_plan,
)


SCHEMA = "e4-hardened-executor-preflight.v1"
POSTGRES_IMAGE = (
    "postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)
TARGET_NAME = re.compile(r"^e4(?:-|_)[a-z0-9][a-z0-9_-]{0,79}$")
TOKEN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
PROOF_FIELDS = {
    "schemaVersion", "planId", "evaluatedAtEpochMs",
    "replayClaimBeforeFirstDockerEffect", "replayClaimId", "target",
    "container", "snapshot", "clock", "production", "teardown", "steps",
    "authority",
}
TARGET_FIELDS = {
    "targetRef", "targetFingerprintSha256", "absentBeforeStart",
    "ownershipTokenCaptured", "containerIdentityCaptured",
    "targetNameImmutable",
}
CONTAINER_FIELDS = {
    "image", "network", "readOnlyRoot", "publishedPorts", "persistentVolume",
    "tmpfsOnly", "noNewPrivileges", "dropAllCapabilities", "nonRoot",
    "boundedHealthcheck", "boundedShutdown", "noHostPath",
}
SNAPSHOT_FIELDS = {
    "preExisting", "encrypted", "immutableAtHandoff", "digestVerified",
    "plaintextPersistenceNone", "productionDisconnected", "absentAfterTeardown",
}
CLOCK_FIELDS = {"attested", "issuerId", "observedAtEpochMs", "expiresAtEpochMs"}
PRODUCTION_FIELDS = {
    "contacted", "credentialsPresent", "writesPerformed", "networkRouteAllowed",
}
TEARDOWN_FIELDS = {
    "targetDestroyed", "targetAbsentAfter", "snapshotDestroyed",
    "snapshotAbsentAfter", "ownershipReleased", "cleanupEvidenceCaptured",
}
AUTHORITY_FIELDS = {
    "executionAuthorized", "productionDatabaseContactAllowed",
    "productionNetworkAllowed", "productionCredentialsAllowed",
    "proposalApplicationAllowed", "persistentTargetAllowed",
    "automaticRetryAllowed", "promotionAllowed", "actionAllowed",
    "moneyActionAllowed", "executionEffect",
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _epoch(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} is invalid")
    return value


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def _closed(value: Any, fields: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{field} shape is invalid")
    return value


def _all_false(value: Mapping[str, Any], fields: set[str], field: str) -> None:
    if any(value.get(item) is not False for item in fields):
        raise ValueError(f"{field} must be fail-closed")


def validate_executor_preflight_proof(*, plan: Mapping[str, Any],
                                      proof: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the exact mechanical proof shape; this does not execute it."""
    frozen = validate_rehearsal_runner_plan(plan)
    if not isinstance(proof, Mapping) or set(proof) != PROOF_FIELDS \
            or proof.get("schemaVersion") != SCHEMA \
            or proof.get("planId") != frozen["planId"]:
        raise ValueError("executor preflight proof schema is invalid")
    _epoch(proof["evaluatedAtEpochMs"], "evaluatedAtEpochMs")
    _token(proof["replayClaimId"], "replayClaimId")
    if proof["replayClaimBeforeFirstDockerEffect"] is not True:
        raise ValueError("replay claim ordering is invalid")

    target = _closed(proof["target"], TARGET_FIELDS, "target")
    if not isinstance(target["targetRef"], str) \
            or not TARGET_NAME.fullmatch(target["targetRef"]):
        raise ValueError("target reference is invalid")
    _digest(target["targetFingerprintSha256"], "targetFingerprintSha256")
    for field in TARGET_FIELDS - {"targetRef", "targetFingerprintSha256"}:
        if target[field] is not True:
            raise ValueError(f"target proof {field} is not true")

    container = _closed(proof["container"], CONTAINER_FIELDS, "container")
    if container["image"] != POSTGRES_IMAGE or container["network"] != "none" \
            or container["publishedPorts"] != []:
        raise ValueError("container isolation is invalid")
    for field in CONTAINER_FIELDS - {"image", "network", "publishedPorts"}:
        if container[field] is not (False if field == "persistentVolume" else True):
            raise ValueError(f"container hardening {field} is invalid")

    snapshot = _closed(proof["snapshot"], SNAPSHOT_FIELDS, "snapshot")
    for field in SNAPSHOT_FIELDS:
        if snapshot[field] is not True:
            raise ValueError(f"snapshot proof {field} is not true")

    clock = _closed(proof["clock"], CLOCK_FIELDS, "clock")
    if clock["attested"] is not True:
        raise ValueError("trusted clock is not attested")
    _token(clock["issuerId"], "clock.issuerId")
    observed = _epoch(clock["observedAtEpochMs"], "clock.observedAtEpochMs")
    expires = _epoch(clock["expiresAtEpochMs"], "clock.expiresAtEpochMs")
    if not observed <= proof["evaluatedAtEpochMs"] <= expires:
        raise ValueError("trusted clock window is invalid")

    production = _closed(proof["production"], PRODUCTION_FIELDS, "production")
    _all_false(production, PRODUCTION_FIELDS, "production")
    teardown = _closed(proof["teardown"], TEARDOWN_FIELDS, "teardown")
    if any(teardown[field] is not True for field in TEARDOWN_FIELDS):
        raise ValueError("teardown proof is incomplete")

    steps = proof["steps"]
    if not isinstance(steps, list) or len(steps) != len(STEPS):
        raise ValueError("executor step count is invalid")
    expected_steps = [
        {"sequence": index, "stepId": step, "effect": effect,
         "completed": True, "evidenceCaptured": True}
        for index, (step, effect) in enumerate(STEPS, start=1)
    ]
    if steps != expected_steps:
        raise ValueError("executor step order/evidence is invalid")

    authority = _closed(proof["authority"], AUTHORITY_FIELDS, "authority")
    for field in AUTHORITY_FIELDS - {"executionEffect"}:
        if authority[field] is not False:
            raise ValueError(f"authority field {field} is not false")
    if authority["executionEffect"] != "NONE":
        raise ValueError("authority effect is invalid")
    return dict(proof)


def assess_hardened_executor_preflight(*, plan: Mapping[str, Any],
                                       proof: Mapping[str, Any]) -> dict[str, Any]:
    """Return a bounded result; never return execution eligibility."""
    try:
        frozen = validate_executor_preflight_proof(plan=plan, proof=proof)
    except (TypeError, ValueError):
        unsigned = {
            "schemaVersion": SCHEMA,
            "status": "NO_GO",
            "planId": plan.get("planId") if isinstance(plan, Mapping) else None,
            "blockers": ["PREFLIGHT_PROOF_INVALID"],
            "mechanicalPreflightPassed": False,
            "executionEligible": False,
            "executionEffect": "NONE",
            "actionAllowed": False,
        }
        return {**unsigned, "assessmentId": "e4hep_" + _hash(unsigned)}
    unsigned = {
        "schemaVersion": SCHEMA,
        "status": "MECHANICAL_PRECHECK_PASS_NON_AUTHORITATIVE",
        "planId": frozen["planId"],
        "blockers": [
            "AUTHENTICATED_TRUST_REGISTRY_REQUIRED",
            "AUTHENTICATED_TRUSTED_CLOCK_REQUIRED",
            "AUTHENTICATED_REPLAY_CLAIM_REQUIRED",
            "HARDENED_EXECUTOR_RUNTIME_NOT_PRESENT",
        ],
        "mechanicalPreflightPassed": True,
        "executionEligible": False,
        "executionEffect": "NONE",
        "actionAllowed": False,
    }
    return {**unsigned, "assessmentId": "e4hep_" + _hash(unsigned)}
