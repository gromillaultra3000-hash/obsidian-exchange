#!/usr/bin/env python3
"""Fail-closed, secret-free freshness check for the 064A signing package."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ARTIFACTS = {
    "migration_plan": "docs/e0-3-bot-b5-3-production-migration-plan.v1.json",
    "dirty_data_scan": "docs/e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1.json",
    "catalog_drift_rehearsal": "docs/e0-3-bot-b5-3-catalog-security-drift-rehearsal.v1.json",
    "catalog_source_restore_rehearsal": "docs/e0-3-bot-b5-3-catalog-source-restore-rehearsal.v1.json",
    "bootstrap_roles": "deploy/postgres/bootstrap_roles.sql",
    "prepare_database": "deploy/postgres/prepare_database.sql",
    "runtime_privileges": "deploy/postgres/runtime_privileges.sql",
}
SOURCE_OBSERVATIONS = (
    "docs/e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1.json",
    "docs/e0-3-bot-b5-3-catalog-source-restore-rehearsal.v1.json",
)
POLICY = "docs/e0-3-bot-b5-3-064a-freshness-policy.v1.json"
SUPPORTING_ARTIFACTS = (
    "docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json",
    "docs/e0-3-bot-b5-3-064a-authenticated-decision-rehearsal.v1.json",
    "docs/e0-3-bot-b5-3-064a-offline-signing-rehearsal.v1.json",
    "docs/b64-064a-offline-signing.md", "relay/core/b64_064a_decision.py",
    "scripts/b64_064a_offline_signer.py", "tests/test_e0_3_bot_b5_3_064a_decision.py",
    "tests/test_e0_3_bot_b5_3_064a_offline_signer.py",
)
POLICY_KEYS = {"schemaVersion","policyId","policyVersion","route",
               "maximumSourceObservationAgeSeconds","maximumFutureSkewSeconds",
               "evaluatedTimeSource","outcomes","supportingArtifacts","authority"}
POLICY_AUTHORITY = {"freshnessCanInvalidate":True,"freshnessCanAuthorize":False,
                    "deferralCannotExpireIntoAllowance":True,
                    "authenticatedAcceptanceRequiredSeparately":True,"actionAllowed":False}
SOURCE_SCHEMAS = {
    SOURCE_OBSERVATIONS[0]: "e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1",
    SOURCE_OBSERVATIONS[1]: "e0-3-bot-b5-3-catalog-source-restore-rehearsal.v1",
}


def safe_path(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("unsafe_artifact_path")
    base = root.resolve(strict=True)
    candidate = base.joinpath(rel)
    current = base
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("unsafe_artifact_path")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("unsafe_artifact_path") from exc
    if not resolved.is_file() or resolved.stat().st_size > 10_000_000:
        raise ValueError("unsafe_artifact_path")
    return resolved


def sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError("unsafe_artifact_path")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError("unsafe_json_path")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("not_json_object")
    return value


def epoch(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("invalid_utc_timestamp")
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    result = int(parsed.timestamp())
    if result <= 0:
        raise ValueError("invalid_utc_timestamp")
    return result


def evaluate(root: Path, now: int, max_age: int) -> dict:
    reasons: list[str] = []
    decision_path = safe_path(root, "docs/e0-3-bot-b5-3-064a-decision-input.v1.json")
    deferral_path = safe_path(root, SUPPORTING_ARTIFACTS[0])
    rehearsal_path = safe_path(root, SUPPORTING_ARTIFACTS[1])
    decision, deferral, rehearsal = load(decision_path), load(deferral_path), load(rehearsal_path)
    policy_path = safe_path(root, POLICY)
    policy = load(policy_path)
    policy_ok = (set(policy) == POLICY_KEYS
                 and policy.get("schemaVersion") == "e0-3-bot-b5-3-064a-freshness-policy.v1"
                 and policy.get("policyId") == "B64_064A_DECISION_SOURCE_FRESHNESS"
                 and policy.get("policyVersion") == 1 and policy.get("route") == "E0/E0.3/B5.3/064A"
                 and policy.get("maximumSourceObservationAgeSeconds") == max_age
                 and policy.get("maximumFutureSkewSeconds") == 60
                 and policy.get("evaluatedTimeSource") == "CALLER_INJECTED_HOST_UTC_UNTRUSTED"
                 and policy.get("outcomes") == ["REFRESH_REQUIRED","CURRENT_BUT_BLOCKED_OWNER"]
                 and policy.get("authority") == POLICY_AUTHORITY)
    if not policy_ok:
        reasons.append("FRESHNESS_POLICY_INVALID")
    supporting_results = []
    declared_support = policy.get("supportingArtifacts", []) if policy_ok else []
    supporting_set_ok = (isinstance(declared_support, list)
                         and [x.get("path") for x in declared_support] == list(SUPPORTING_ARTIFACTS))
    if not supporting_set_ok:
        reasons.append("SUPPORTING_ARTIFACT_SET_MISMATCH")
        declared_support = []
    seen_paths = set()
    for item in declared_support:
        relative, expected = item.get("path"), item.get("sha256")
        if relative in seen_paths or not isinstance(relative, str):
            reasons.append("SUPPORTING_ARTIFACT_DUPLICATE")
            continue
        seen_paths.add(relative)
        actual = sha(safe_path(root, relative))
        matches = actual == expected
        supporting_results.append({"path":relative,"expectedSha256":expected,"actualSha256":actual,"matches":matches})
        if not matches:
            reasons.append(f"SUPPORTING_ARTIFACT_DIGEST_DRIFT:{relative}")
    decision_sha = sha(decision_path)

    declared = decision.get("artifactDigests")
    expected_ids = list(ARTIFACTS)
    artifact_results = []
    artifact_set_ok = (isinstance(declared, list)
                       and [x.get("artifactId") for x in declared] == expected_ids)
    if not artifact_set_ok:
        reasons.append("ARTIFACT_SET_MISMATCH")
        declared = []
    declared_by_id = {x.get("artifactId"): x.get("sha256") for x in declared}
    for artifact_id, relative in ARTIFACTS.items():
        actual = sha(safe_path(root, relative))
        expected = declared_by_id.get(artifact_id)
        matches = actual == expected
        artifact_results.append({"artifactId": artifact_id, "path": relative,
                                 "expectedSha256": expected, "actualSha256": actual,
                                 "matches": matches})
        if not matches:
            reasons.append(f"ARTIFACT_DIGEST_DRIFT:{artifact_id}")

    binding_results = {
        "ownerDeferral": deferral.get("decisionInputSha256") == decision_sha,
        "authenticatedRehearsal": rehearsal.get("decisionInputSha256") == decision_sha,
    }
    for name, matches in binding_results.items():
        if not matches:
            reasons.append(f"DECISION_INPUT_BINDING_DRIFT:{name}")

    safe_flags = (
        decision.get("effect") == "EVIDENCE_ACCEPTANCE_ONLY"
        and decision.get("productionMutation") is False
        and decision.get("cutoverAuthorized") is False
        and decision.get("telegramDeliveryAuthorized") is False
        and decision.get("actionAllowed") is False
    )
    if not safe_flags:
        reasons.append("DECISION_SAFETY_FLAGS_INVALID")
    # The current label says APPROVE_064B_EXPAND_ONLY while the signed protocol
    # accepts bounded evidence only. Treat that human-facing ambiguity as a block.
    scope_unambiguous = decision.get("requestedDecision") == "ACCEPT_BOUNDED_EVIDENCE_ONLY"
    if not scope_unambiguous:
        reasons.append("DECISION_SCOPE_LABEL_AMBIGUOUS")

    source_results = []
    for relative in SOURCE_OBSERVATIONS:
        value = load(safe_path(root, relative))
        if value.get("schemaVersion") != SOURCE_SCHEMAS[relative] or value.get("route") != "E0/E0.3/B5.3/064A":
            reasons.append(f"SOURCE_OBSERVATION_SCHEMA_INVALID:{Path(relative).name}")
        observed = epoch(value.get("observedAt", ""))
        age = now - observed
        fresh = -60 <= age <= max_age
        source_results.append({"path": relative, "observedAt": value.get("observedAt"),
                               "ageSeconds": age, "maxAgeSeconds": max_age, "fresh": fresh})
        if age < -60:
            reasons.append(f"SOURCE_OBSERVATION_FROM_FUTURE:{Path(relative).name}")
        elif age > max_age:
            reasons.append(f"SOURCE_OBSERVATION_STALE:{Path(relative).name}")

    deferral_active = (
        deferral.get("status") == "BLOCKED_OWNER"
        and deferral.get("decisionEffect") == "RESTRICTIVE_DEFERRAL_ONLY"
        and deferral.get("ownerDeferralDecisionPresent") is True
        and deferral.get("authenticated064AAcceptancePresent") is False
        and deferral.get("actionAllowed") is False
    )
    if not deferral_active:
        reasons.append("OWNER_DEFERRAL_STATE_UNEXPECTED")
    else:
        reasons.append("ACTIVE_RESTRICTIVE_OWNER_DEFERRAL")

    technical_reasons = [x for x in reasons if x != "ACTIVE_RESTRICTIVE_OWNER_DEFERRAL"]
    integrity = (artifact_set_ok and supporting_set_ok
                 and len(supporting_results) == len(SUPPORTING_ARTIFACTS)
                 and all(x["matches"] for x in artifact_results)
                 and all(x["matches"] for x in supporting_results)
                 and all(binding_results.values()) and policy_ok)
    freshness = all(x["fresh"] for x in source_results)
    technical_current = integrity and freshness and safe_flags and scope_unambiguous and not technical_reasons
    status = "CURRENT_BUT_BLOCKED_OWNER" if technical_current and deferral_active else "REFRESH_REQUIRED"
    return {
        "schemaVersion": "b64-064a-decision-freshness.v1",
        "route": "E0/E0.3/B5.3/064A",
        "gateStatus": "BLOCKED_OWNER",
        "evaluatedAtEpoch": now,
        "evaluatedTimeSource": "CALLER_INJECTED_HOST_UTC_UNTRUSTED",
        "policyId": policy.get("policyId"), "policyVersion": policy.get("policyVersion"),
        "freshnessPolicySha256": sha(policy_path),
        "decisionInputSha256": decision_sha,
        "packageIntegrity": integrity,
        "sourceObservationFresh": freshness,
        "decisionScopeUnambiguous": scope_unambiguous,
        "ownerDeferralActive": deferral_active,
        "artifactResults": artifact_results,
        "supportingArtifactResults": supporting_results,
        "bindingResults": binding_results,
        "sourceObservationResults": source_results,
        "status": status,
        "reasonCodes": sorted(set(reasons)),
        "technicalEvidenceCurrent": technical_current,
        "signingPreparationEligible": False,
        "authenticatedAcceptancePresent": False,
        "productionMutationAuthorized": False,
        "productionExpandAuthorized": False,
        "cutoverAuthorized": False,
        "actionAllowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--now", type=int, required=True)
    parser.add_argument("--max-source-age-seconds", type=int, default=86400)
    args = parser.parse_args()
    if args.now <= 0 or args.max_source_age_seconds <= 0:
        parser.error("positive time values required")
    try:
        result = evaluate(args.root.resolve(), args.now, args.max_source_age_seconds)
    except Exception:
        result = {"schemaVersion":"b64-064a-decision-freshness.v1",
                  "route":"E0/E0.3/B5.3/064A", "gateStatus":"BLOCKED_OWNER",
                  "status":"REFRESH_REQUIRED",
                  "reasonCodes":["PREFLIGHT_INPUT_INVALID"], "packageIntegrity":False,
                  "sourceObservationFresh":False, "technicalEvidenceCurrent":False,
                  "signingPreparationEligible":False,
                  "authenticatedAcceptancePresent":False, "productionMutationAuthorized":False,
                  "productionExpandAuthorized":False, "cutoverAuthorized":False,
                  "actionAllowed":False}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 3 if result.get("status") == "CURRENT_BUT_BLOCKED_OWNER" else 2


if __name__ == "__main__":
    raise SystemExit(main())
