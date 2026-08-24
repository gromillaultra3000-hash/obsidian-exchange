import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-3-bot-b5-3-064a-refresh-launch-preflight.v1.json"
LEDGER = ROOT / "docs/e0-gate-status.v1.json"
EXPECTED_BINDINGS = {
    "docs/e0-3-bot-b5-3-064a-current-authority-reconciliation.v1.json":
        "4060eac085698ee8b4dc3237381b2788e69611a50cdf9bf38cc0d82e9350440d",
    "docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json":
        "99531224f6eac8d13ce07b14fdf6408f333fca2a10426e7876613ce3da812a80",
    "docs/b64-064a-offline-signing-v4.md":
        "07670fb2368786c2d6b7b7b89649b032ea3d5fd6adb490bfcc562f82ec525854",
    "scripts/b64_064a_offline_signer.py":
        "fafe307ba81a1f08eb762ecbea26578728b5688fe552529a5b1a5b56fafca2f2",
    "relay/core/b64_064a_decision.py":
        "f0eac40ae2f8cf5f2e616bc6e1853621988eed9aebfd4e6658ab71c240b1c5fd",
    "docs/e0-3-bot-b5-3-064a-v4-synthetic-one-device-preflight.v1.json":
        "0e82f5854a5416f3eeedce967eb81cb4cce4a8a0b77c4d129aa325dc499b87f4",
    "deploy/postgres/check_b64_notification_migration.py":
        "9f7941d2945701b92918ef561b22663e2a307407c6194462f2e2dac83a05fc0f",
    "deploy/postgres/b64_snapshot_dump.py":
        "5fae39a32b195b4dd8eba3e9834fee1834f010538bc87a3bb04e623aa91921a2",
    "tests/test_e0_3_bot_b5_3_snapshot_dump.py":
        "5d59de5cd65b77c4acb6098991135f01e9d9f5af6041a26af67d2517e11e4cc9",
}
EXPECTED_PREDICATES = [
    {"id": "OWNER_CONVERSATION_AUTHORIZATION_FOR_ONE_READ_ONLY_REFRESH",
     "status": "PASS_CONDITIONAL"},
    {"id": "ACCOUNTABLE_OWNER_OFFLINE_SIGNING_PATH_READY", "status": "FAIL_NOT_PROVEN"},
    {"id": "GENUINELY_INDEPENDENT_REVIEWER_AND_SEPARATE_OFFLINE_DEVICE_READY",
     "status": "FAIL_NOT_PROVEN"},
    {"id": "PRODUCTION_AUTHENTICATED_KEY_REGISTRY_AND_ENROLLMENT_READY",
     "status": "FAIL_ABSENT"},
    {"id": "TRUSTED_TIME_ATTESTATION_READY", "status": "FAIL_ABSENT"},
    {"id": "REVOCATION_SOURCE_READY", "status": "FAIL_ABSENT"},
    {"id": "DURABLE_ATOMIC_REPLAY_LEDGER_AND_CONSUMER_READY", "status": "FAIL_ABSENT"},
    {"id": "EXACT_SECRET_SAFE_READ_ONLY_OPERATOR_COMMAND_AND_CREDENTIAL_MAPPING_REVIEWED",
     "status": "FAIL_ABSENT"},
    {"id": "PATCHED_DIGEST_PINNED_PG_DUMP_CLIENT_AT_LEAST_17_11",
     "status": "FAIL_CURRENT_EVIDENCE_17_10"},
    {"id": "DEDICATED_ATTESTED_LEAST_PRIVILEGE_DUMP_PRINCIPAL",
     "status": "FAIL_RUNNER_USES_POSTGRES"},
    {"id": "FAIL_SAFE_CLEANUP_AND_ABSENCE_VERIFICATION_FOR_ALL_TRANSIENTS",
     "status": "FAIL_INCOMPLETE"},
    {"id": "STATEMENT_EXPIRY_CANNOT_EXCEED_SOURCE_EVIDENCE_EXPIRY",
     "status": "FAIL_NOT_ENFORCED_AT_VERIFY"},
    {"id": "CURRENT_IMPLEMENTATION_AND_SOURCE_PACKAGE",
     "status": "FAIL_EXPIRED_AND_DRIFTED"},
]
EXPECTED_REMAINING_BLOCKERS = [
    "INDEPENDENT_REVIEWER_AND_SEPARATE_OFFLINE_DEVICE_NOT_PROVEN_READY",
    "PRODUCTION_REGISTRY_TRUSTED_TIME_REVOCATION_AND_DURABLE_REPLAY_ABSENT",
    "READ_ONLY_OPERATOR_COMMAND_AND_CREDENTIAL_MAPPING_NOT_REVIEWED",
    "PG_DUMP_17_10_EVIDENCE_IS_AFFECTED_BY_CVE_2026_19385",
    "PG_DUMP_RUNS_AS_POSTGRES_WITHOUT_LEAST_PRIVILEGE_ATTESTATION",
    "TRANSIENT_CLEANUP_IS_NOT_ONE_FAIL_SAFE_VERIFIED_ORCHESTRATION",
    "STATEMENT_EXPIRY_MAY_OUTLIVE_SOURCE_EVIDENCE_EXPIRY",
    "SOURCE_WINDOW_EXPIRED_AND_CURRENT_IMPLEMENTATION_BINDINGS_DRIFTED",
    "064B_REMAINS_UNAUTHORIZED",
    "064D_REMAINS_UNAUTHORIZED",
]
EXPECTED_NEXT = (
    "HARDEN_AND_INDEPENDENTLY_REVIEW_ONE_EXACT_064A_REFRESH_RUNBOOK_WITH_PATCHED_PINNED_"
    "PG_DUMP_LEAST_PRIVILEGE_COMPLETE_CLEANUP_SOURCE_WINDOW_BINDING_AND_CONCRETE_"
    "AUTHENTICATION_PATH_BEFORE_FRESH_OWNER_AUTHORIZATION"
)


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_launch_preflight_preserves_exact_historical_bindings_and_detects_current_drift():
    evidence = _load(EVIDENCE)
    assert evidence["schemaVersion"] == "e0-3-bot-b5-3-064a-refresh-launch-preflight.v1"
    assert evidence["route"] == "E0/E0.3/B5.3/064A_REFRESH_LAUNCH_PREFLIGHT"
    assert evidence["boundedSliceStatus"] == "BLOCKED_OWNER"
    assert evidence["result"] == "NO_GO_BEFORE_PRODUCTION_CONTACT"
    bindings = evidence["evidenceBindings"]
    assert len(bindings) == len(EXPECTED_BINDINGS)
    assert [item["path"] for item in bindings] == list(EXPECTED_BINDINGS)
    assert len({item["path"] for item in bindings}) == len(bindings)
    assert {item["path"]: item["sha256"] for item in bindings} == EXPECTED_BINDINGS
    drift = []
    for relative, digest in EXPECTED_BINDINGS.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            drift.append(relative)
    assert drift == [
        "docs/e0-3-bot-b5-3-064a-current-authority-reconciliation.v1.json",
        "scripts/b64_064a_offline_signer.py",
        "relay/core/b64_064a_decision.py",
    ]


def test_conversation_authorization_is_conditional_unconsumed_and_non_accepting():
    authorization = _load(EVIDENCE)["conversationAuthorization"]
    assert authorization == {
        "present": True,
        "source": "CURRENT_OWNER_CONVERSATION_CONTEXT_ONLY",
        "scope": "ONE_BOUNDED_READ_ONLY_064A_PRODUCTION_REFRESH_AFTER_ALL_HARD_PREREQUISITES_PASS",
        "singleUse": True,
        "consumed": False,
        "authenticatedCryptographicDecision": False,
        "evidenceAcceptance": False,
        "activationAllowed": False,
        "materiallyRevisedCommandRequiresFreshOwnerReview": True,
    }


def test_every_conjunctive_production_readiness_predicate_after_chat_authorization_fails():
    evidence = _load(EVIDENCE)
    predicates = evidence["hardReadinessPredicates"]
    assert predicates == EXPECTED_PREDICATES
    synthetic = _load(ROOT / "docs/e0-3-bot-b5-3-064a-v4-synthetic-one-device-preflight.v1.json")
    assert synthetic["oneDeviceBoundary"]["humanIndependenceProven"] is False
    assert synthetic["oneDeviceBoundary"]["separateOfflineDeviceRequirementSatisfied"] is False
    assert synthetic["result"]["replayProtectionVerified"] is False
    assert synthetic["result"]["productionAuthority"] is False


def test_current_source_is_expired_affected_17_10_and_not_signable():
    evidence = _load(EVIDENCE)
    finding = evidence["currentPackageFindings"]
    source = _load(ROOT / "docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json")
    observed = _time(finding["sourceObservedAt"])
    assert _time(finding["sourceExpiredAt"]) == observed + timedelta(seconds=86400)
    assert source["observedAt"] == finding["sourceObservedAt"]
    assert source["source"]["postgresVersionNum"] == finding["sourcePostgresVersionNum"] == 170010
    assert finding["sourceCurrent"] is False
    assert finding["packageIntegrity"] is False
    assert finding["technicalEvidenceCurrent"] is False
    assert finding["implementationDriftPresent"] is True
    assert finding["candidateCanBeSignedNow"] is False
    cve = evidence["securityResearch"][0]
    assert cve["source"] == "https://www.postgresql.org/support/security/CVE-2026-19385/"
    assert cve["finding"] == "PG_DUMP_BEFORE_17_11_AFFECTED_BY_CVE_2026_19385_CVSS_8_8"


def test_runtime_paths_remain_synthetic_while_source_window_is_now_verify_bound():
    signer = (ROOT / "scripts/b64_064a_offline_signer.py").read_text(encoding="utf-8")
    protocol = (ROOT / "relay/core/b64_064a_decision.py").read_text(encoding="utf-8")
    assert 'value["trustEnvironment"] != "CANDIDATE_OFFLINE"' in signer
    assert 'consume_pair=lambda *_:True,trust_environment="CANDIDATE_OFFLINE"' in signer
    assert '"replayProtectionVerified":False,"productionAuthority":False' in signer
    assert 'production = trust_environment == "PRODUCTION_AUTHENTICATED"' in protocol
    assert "expires_at_epoch <= issued_at_epoch + MAX_LIFETIME_SECONDS" in protocol
    assert 'unsigned["sourceObservedAtEpoch"]' in protocol
    assert 'unsigned["sourceExpiresAtEpoch"]' in protocol
    assert "legacy_statement_not_production_eligible" in protocol
    assert "expected_source_observed_at_epoch=source_observed" in signer
    assert "expected_source_expires_at_epoch=source_expires" in signer


def test_dirty_scan_fail_open_was_narrowly_hardened_without_overclaim():
    evidence = _load(EVIDENCE)
    guard = evidence["localGuardHardening"]
    assert guard["status"] == "HARDENED_LOCAL"
    assert guard["focusedTests"] == {"result": "PASS", "count": 14}
    assert guard["doesNotClaimWholeRefreshRunnerSafe"] is True
    snapshot = (ROOT / "deploy/postgres/b64_snapshot_dump.py").read_text(encoding="utf-8")
    checker = (ROOT / "deploy/postgres/check_b64_notification_migration.py").read_text(encoding="utf-8")
    assert 'dirty_data.get("status") != "IN_PROGRESS"' not in snapshot
    assert "if not valid_snapshot_scan(dirty_data):" in snapshot
    assert '"TARGET_PG17_READONLY_AND_LEGACY_SHAPE_EXACT"' in checker
    assert "def valid_snapshot_scan(value: object) -> bool:" in checker


def test_preflight_did_not_cross_any_runtime_or_authority_boundary():
    evidence = _load(EVIDENCE)
    assert evidence["canonicalGateStatus"] == {
        "stage": "E0",
        "stageStatus": "IN_PROGRESS",
        "firstUnmetCriterion": "E0.3",
        "firstUnmetStatus": "BLOCKED_OWNER",
        "e4ExcludedFromCurrentTask": True,
        "e4StatusPreserved": "IN_PROGRESS",
        "e4GateDecisionPreserved": "NO_GO",
    }
    assert evidence["independentReviews"] == [
        {"review": "ROUTE_AND_AUTHORITY", "result": "NO_GO"},
        {"review": "LOCAL_STATE_AND_PREREQUISITES", "result": "NO_GO"},
        {"review": "SECURITY_AND_DEVOPS_REPEATABILITY", "result": "NO_GO"},
    ]
    assert evidence["postChangeReviews"] == [
        {"review": "ROUTE_AND_AUTHORITY_EXACTNESS", "localSliceResult": "PASS",
         "operationalRefreshResult": "NO_GO"},
        {"review": "ADVERSARIAL_COUNTER_AND_EVIDENCE_MUTATIONS", "localSliceResult": "PASS",
         "operationalRefreshResult": "NO_GO"},
        {"review": "SECURITY_AND_DEVOPS_SQL_SEMANTICS", "localSliceResult": "PASS",
         "operationalRefreshResult": "NO_GO"},
    ]
    assert evidence["verification"] == {
        "dirtyScanGuardTests": 14,
        "rootFocused064aAndSnapshotTests": 68,
        "independentExtendedSelectedTests": 71,
        "jsonValidation": "PASS",
        "pythonCompilation": "PASS",
        "gitDiffCheck": "PASS",
        "gitCachedDiffCheck": "PASS",
        "gitleaksVersion": "8.30.0",
        "gitleaksScopedResult": "PASS",
    }
    execution = evidence["refreshExecution"]
    assert execution == {
        "preflightCompleted": True,
        "productionContact": False,
        "productionDatabaseConnection": False,
        "dockerOrPostgresInvoked": False,
        "secretOrPrivateKeyRead": False,
        "customerDataRead": False,
        "signatureCreated": False,
        "refreshAttempted": False,
        "new24HourWindowCreated": False,
        "authorizationConsumed": False,
        "automaticRetry": False,
    }
    assert evidence["authority"] == {
        "evidenceAccepted": False,
        "productionContactActivated": False,
        "productionMutationAuthorized": False,
        "productionExpandAuthorized": False,
        "deploymentAuthorized": False,
        "restartAuthorized": False,
        "cutoverAuthorized": False,
        "telegramDeliveryAuthorized": False,
        "ambiguousSendingDispositionAuthorized": False,
        "automaticRetryAuthorized": False,
        "e4ExecutionAuthorized": False,
        "actionAllowed": False,
    }
    assert evidence["remainingBlockers"] == EXPECTED_REMAINING_BLOCKERS
    assert evidence["nextCanonicalItem"] == EXPECTED_NEXT
    assert evidence["canonicalGateStatus"]["e4ExcludedFromCurrentTask"] is True
    assert evidence["canonicalGateStatus"]["e4StatusPreserved"] == "IN_PROGRESS"
    assert evidence["canonicalGateStatus"]["e4GateDecisionPreserved"] == "NO_GO"


def test_machine_gate_ledger_points_to_launch_preflight_no_go():
    evidence = _load(EVIDENCE)
    ledger = _load(LEDGER)
    assert _time(ledger["statusReconciliation"]["reconciledAt"]) >= _time(evidence["observedAt"])
    assert ledger["statusReconciliation"]["productionReobserved"] is False
    criterion = next(item for item in ledger["stage"]["criteria"] if item["id"] == "E0.3")
    assert criterion["status"] == "BLOCKED_OWNER"
    assert str(EVIDENCE.relative_to(ROOT)) in criterion["latestEvidence"]
    assert "operational refresh remains NO_GO" in criterion["blocker"]
    assert (
        "DESIGN_AND_REHEARSE_EXACT_OBSIDIAN_B64_SNAPSHOT_READER_ROLE_PROVISIONING_"
        "AGAINST_THE_FROZEN_001_023_PROFILE"
    ) in criterion["blocker"]


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            globals()[name]()
    print("064A_REFRESH_LAUNCH_PREFLIGHT_PASS")
