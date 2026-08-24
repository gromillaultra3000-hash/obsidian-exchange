import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-3-bot-b5-3-064a-source-window-v2-closure.v1.json"


def load():
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_closure_binds_current_implementation_and_tests():
    evidence = load()
    assert evidence["schemaVersion"] == "e0-3-bot-b5-3-064a-source-window-v2-closure.v1"
    assert evidence["route"] == "E0/E0.3/B5.3/064A_SOURCE_WINDOW_V2_CLOSURE"
    assert evidence["boundedSliceStatus"] == "VERIFIED_LOCAL"
    assert evidence["operationalRefreshStatus"] == "NO_GO"
    for binding in evidence["implementationBindings"]:
        assert hashlib.sha256((ROOT / binding["path"]).read_bytes()).hexdigest() == binding["sha256"]


def test_contract_is_source_bound_without_authority_expansion():
    evidence = load()
    contract = evidence["closedContract"]
    assert contract["productionRequiresStatementSchema"] == "b64-064a-decision-statement.v2"
    assert contract["legacyV1Scope"] == "SYNTHETIC_ONLY"
    assert contract["freeCallerSourceWindowInput"] is False
    assert contract["productionAuthorityCreated"] is False
    assert evidence["cleanupEvidenceValidation"]["validatesHistoricalEvidenceShapeOnly"] is True
    assert evidence["cleanupEvidenceValidation"]["claimsEndToEndRunnerCleanup"] is False
    assert all(value is False for key, value in evidence["authority"].items()
               if key not in {"priorConversationAuthorizationConsumed",
                              "freshOwnerAuthorizationRequiredForMateriallyRevisedCommand"})
    assert evidence["authority"]["priorConversationAuthorizationConsumed"] is False
    assert evidence["authority"]["freshOwnerAuthorizationRequiredForMateriallyRevisedCommand"] is True
    assert [item["localSliceResult"] for item in evidence["independentReviews"]] == [
        "PASS", "PASS", "PASS"]
    assert {item["operationalRefreshResult"] for item in evidence["independentReviews"]} == {
        "NO_GO"}


def test_gate_stays_blocked_and_has_one_concrete_next_item():
    evidence = load()
    ledger = json.loads((ROOT / "docs/e0-gate-status.v1.json").read_text(encoding="utf-8"))
    assert evidence["canonicalGateStatus"] == {
        "stage": "E0",
        "stageStatus": "IN_PROGRESS",
        "firstUnmetCriterion": "E0.3",
        "firstUnmetStatus": "BLOCKED_OWNER",
        "e4ExcludedFromCurrentTask": True,
        "e4StatusPreserved": "IN_PROGRESS",
        "e4GateDecisionPreserved": "NO_GO",
    }
    assert evidence["remainingHardBlockers"]
    criterion = next(item for item in ledger["stage"]["criteria"] if item["id"] == "E0.3")
    assert str(EVIDENCE.relative_to(ROOT)) in criterion["latestEvidence"]
    assert "operational refresh remains NO_GO" in criterion["blocker"]
    assert evidence["nextCanonicalItem"] == (
        "HARDEN_ONE_EXACT_064A_REFRESH_RUNBOOK_WITH_PATCHED_DIGEST_PINNED_PG_DUMP_"
        "LEAST_PRIVILEGE_COMPLETE_CLEANUP_AND_CONCRETE_PRODUCTION_AUTHENTICATION_ADAPTER_"
        "THEN_INDEPENDENTLY_REVIEW_BEFORE_FRESH_OWNER_AUTHORIZATION")
