"""Fail-closed command boundary for one isolated E4 rehearsal invocation.

This module builds a secret-free, non-executing invocation plan. A separate
executor may consume the plan only after validating the exact receipt. It does
not read files, secrets, environment variables, databases or Docker state.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from core.e4_rehearsal_runner_authorization import validate_authorization_receipt
from core.e4_rehearsal_runner_plan import validate_rehearsal_runner_plan

SCHEMA = "e4-rehearsal-runner-boundary.v1"
TARGET_CLASS = "ISOLATED_DISPOSABLE_POSTGRESQL"
POSTGRES_IMAGE = (
    "postgres@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)
TARGET_NAME = re.compile(r"^e4(?:-|_)[a-z0-9][a-z0-9_-]{0,79}$")
OPAQUE_REF = re.compile(r"^[a-z0-9][a-z0-9_-]{0,95}$")
SHA256_REF = re.compile(r"^sha256_(?P<digest>[0-9a-f]{64})$")


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _target_ref(value: Any) -> str:
    if not isinstance(value, str) or not TARGET_NAME.fullmatch(value):
        raise ValueError("targetRef is invalid")
    return value


def _opaque_ref(value: Any, field: str) -> str:
    if not isinstance(value, str) or not OPAQUE_REF.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    lowered = value.lower()
    if any(marker in lowered for marker in (
            "postgres", "database_url", "dsn", "password", "secret", "prod",
            "live", "obsidian", "exchange", "root")):
        raise ValueError(f"{field} contains a forbidden production/secret marker")
    return value


def _bound_ref(value: Any, field: str) -> tuple[str, str]:
    """Return an opaque public reference and its owner-bound digest.

    Historical staging references contain deployment names, and the key digest
    is bound directly to the normalized public SSH recipient line.  Neither
    value belongs in runtime input, so ``sha256_<digest>`` is the canonical
    digest-only reference.  Legacy safe opaque references remain valid.
    """
    ref = _opaque_ref(value, field)
    match = SHA256_REF.fullmatch(ref)
    if match is not None:
        return ref, _digest(match.group("digest"), f"{field}Sha256")
    return ref, hashlib.sha256(ref.encode()).hexdigest()


def target_spec(*, target_ref: str) -> dict[str, Any]:
    """Return the only target shape this boundary can describe."""
    ref = _target_ref(target_ref)
    return {
        "targetRef": ref,
        "targetClass": TARGET_CLASS,
        "image": POSTGRES_IMAGE,
        "network": "none",
        "readOnlyRoot": True,
        "persistentVolume": False,
        "publishedPorts": False,
        "tmpfsOnly": True,
        "automaticRetryAllowed": False,
    }


def target_spec_fingerprint(*, target_ref: str) -> str:
    """Fingerprint the deterministic fixture specification, not a live ID."""
    return _hash(target_spec(target_ref=target_ref))


def build_runner_boundary(*, plan: Mapping[str, Any], receipt: Mapping[str, Any],
                          snapshot_ref: str, key_ref: str) -> dict[str, Any]:
    """Build a non-executing, receipt-bound isolated runner invocation plan."""
    frozen_plan = validate_rehearsal_runner_plan(plan)
    frozen_receipt = validate_authorization_receipt(receipt)
    if frozen_receipt["status"] != "ELIGIBLE" \
            or frozen_receipt["rehearsalExecutionEligible"] is not True:
        raise ValueError("runner boundary requires an eligible authorization receipt")
    target = _target_ref(frozen_receipt["targetRef"])
    if frozen_receipt["planId"] != frozen_plan["planId"]:
        raise ValueError("receipt plan binding is invalid")
    expected_fingerprint = target_spec_fingerprint(target_ref=target)
    if frozen_receipt["targetFingerprintSha256"] != expected_fingerprint:
        raise ValueError("receipt target fingerprint differs from frozen target spec")
    snapshot = _digest(frozen_receipt["snapshotSha256"], "snapshotSha256")
    snapshot_ref_value, snapshot_ref_digest = _bound_ref(snapshot_ref, "snapshotRef")
    key_ref_value, key_ref_digest = _bound_ref(key_ref, "keyRef")
    if snapshot_ref_digest != frozen_receipt["snapshotRefSha256"] \
            or key_ref_digest != frozen_receipt["keyRefSha256"]:
        raise ValueError("runner references differ from owner-approved receipt")
    spec = target_spec(target_ref=target)
    phases = [
        {
            "sequence": 1,
            "operation": "VERIFY_TARGET_ABSENT",
            "effect": "READ_ONLY",
            "argv": ["docker", "ps", "-aq", "--filter", f"name=^{target}$"],
        },
        {
            "sequence": 2,
            "operation": "CREATE_DISPOSABLE_POSTGRESQL_TARGET",
            "effect": "REVERSIBLE_FIXTURE_MUTATION",
            "argv": [
                "docker", "run", "--detach", "--name", target,
                "--network", "none", "--read-only",
                "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=256m",
                "--tmpfs", "/run/postgresql:rw,noexec,nosuid,nodev,size=16m",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
                "--shm-size", "64m", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                POSTGRES_IMAGE,
            ],
        },
        {
            "sequence": 3,
            "operation": "LOAD_ENCRYPTED_SNAPSHOT",
            "effect": "BOUNDED_FIXTURE_MUTATION",
            "snapshotRef": snapshot_ref_value,
            "snapshotSha256": snapshot,
            "keyRef": key_ref_value,
            "plaintextPersistence": "NONE",
            "targetRef": target,
        },
        {
            "sequence": 4,
            "operation": "REVOKE_POST_LOAD_WRITE_CAPABILITY",
            "effect": "REVERSIBLE_FIXTURE_MUTATION",
            "targetRef": target,
        },
        {
            "sequence": 5,
            "operation": "COLLECT_SECRET_FREE_READ_ONLY_EVIDENCE",
            "effect": "READ_ONLY",
            "targetRef": target,
            "productionContacted": False,
            "connectionMaterialPresent": False,
            "proposalApplicationAllowed": False,
        },
        {
            "sequence": 6,
            "operation": "DESTROY_DISPOSABLE_TARGET_AND_STAGED_SNAPSHOT",
            "effect": "ROLLBACK_MUTATION",
            "argv": ["docker", "rm", "-f", target],
        },
        {
            "sequence": 7,
            "operation": "VERIFY_TARGET_AND_SNAPSHOT_ABSENT",
            "effect": "READ_ONLY",
            "targetRef": target,
            "snapshotRef": snapshot_ref_value,
        },
    ]
    unsigned = {
        "schemaVersion": SCHEMA,
        "planId": frozen_plan["planId"],
        "receiptId": frozen_receipt["receiptId"],
        "target": spec,
        "snapshotSha256": snapshot,
        "phases": phases,
        "productionDatabaseContactAllowed": False,
        "productionNetworkAllowed": False,
        "productionCredentialsAllowed": False,
        "proposalApplicationAllowed": False,
        "persistentTargetAllowed": False,
        "automaticRetryAllowed": False,
        "rehearsalInvocationAllowed": True,
        "moneyActionAllowed": False,
        "executionEffect": "NONE",
        "promotionAllowed": False,
        "actionAllowed": False,
        "containsConnectionMaterial": False,
        "containsSecretValue": False,
    }
    return {**unsigned, "boundaryId": "e4rrb_" + _hash(unsigned)}


def validate_runner_boundary(value: Mapping[str, Any], *, plan: Mapping[str, Any],
                             receipt: Mapping[str, Any], snapshot_ref: str,
                             key_ref: str) -> dict[str, Any]:
    """Validate the exact builder output and reject scope expansion."""
    if not isinstance(value, Mapping) or value.get("schemaVersion") != SCHEMA:
        raise ValueError("runner boundary schema is invalid")
    required_false = (
        "productionDatabaseContactAllowed", "productionNetworkAllowed",
        "productionCredentialsAllowed", "proposalApplicationAllowed",
        "persistentTargetAllowed", "automaticRetryAllowed", "promotionAllowed",
        "actionAllowed", "moneyActionAllowed", "containsConnectionMaterial",
        "containsSecretValue",
    )
    if any(value.get(field) is not False for field in required_false) \
            or value.get("rehearsalInvocationAllowed") is not True \
            or value.get("executionEffect") != "NONE":
        raise ValueError("runner boundary scope is invalid")
    target = value.get("target")
    if not isinstance(target, Mapping) or target.get("targetClass") != TARGET_CLASS:
        raise ValueError("runner target spec is invalid")
    rebuilt = build_runner_boundary(plan=plan, receipt=receipt,
                                    snapshot_ref=snapshot_ref, key_ref=key_ref)
    if rebuilt != dict(value):
        raise ValueError("runner boundary hash differs")
    return dict(value)
