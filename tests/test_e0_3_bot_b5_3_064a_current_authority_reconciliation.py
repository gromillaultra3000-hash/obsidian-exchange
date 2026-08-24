import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-3-bot-b5-3-064a-current-authority-reconciliation.v1.json"
LEDGER = ROOT / "docs/e0-gate-status.v1.json"
EXPECTED_BINDINGS = {
    "docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json":
        "99531224f6eac8d13ce07b14fdf6408f333fca2a10426e7876613ce3da812a80",
    "docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json":
        "32d54d2bfaf555c7d795cc70b8b92561d7a6d9a19262eb1089eb3611aafd2316",
    "docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json":
        "771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf",
    "docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json":
        "c1cf8375efe84ce4a77302263f3450d661f732ee88dd30164dc711bc94a2f7e3",
    "docs/e0-3-bot-b5-3-064a-v4-handoff.v1.json":
        "621a1c8ce2c932d2e5bc0d91edced5fa9542a144de9d552300e9d64c42169dfa",
}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _time(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_current_authority_reconciliation_binds_exact_public_evidence():
    evidence = _load(EVIDENCE)
    assert evidence["schemaVersion"] == "e0-3-bot-b5-3-064a-current-authority-reconciliation.v1"
    assert evidence["route"] == "E0/E0.3/B5.3/064A_CURRENT_AUTHORITY_RECONCILIATION"
    assert evidence["boundedSliceStatus"] == "BLOCKED_OWNER"
    assert evidence["result"] == "RECONCILED_NO_AUTHORITY"

    bindings = evidence["evidenceBindings"]
    assert len(bindings) == len(EXPECTED_BINDINGS)
    assert [item["path"] for item in bindings] == list(EXPECTED_BINDINGS)
    assert len({item["path"] for item in bindings}) == len(bindings)
    actual_bindings = {item["path"]: item["sha256"] for item in bindings}
    assert actual_bindings == EXPECTED_BINDINGS
    for relative, digest in EXPECTED_BINDINGS.items():
        path = ROOT / relative
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest

    source = _load(ROOT / "docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json")
    candidate = _load(ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json")
    prior = _load(ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json")
    deferral = _load(ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json")
    handoff = _load(ROOT / "docs/e0-3-bot-b5-3-064a-v4-handoff.v1.json")

    assert candidate["sourceObservation"] == {
        "path": "docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json",
        "sha256": EXPECTED_BINDINGS["docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json"],
        "observedAt": source["observedAt"],
        "maximumAgeSecondsAtDecision": 86400,
    }
    assert candidate["sourceBinding"] == {
        "database": source["source"]["database"],
        "postgresVersionNum": source["source"]["postgresVersionNum"],
        "sourceClusterSha256": source["source"]["sourceClusterSha256"],
        "archiveSha256": source["archive"]["sha256"],
        "tableFingerprintSha256": source["equality"]["tableSourceAndRestoreSha256"],
        "catalogFingerprintSha256": source["equality"]["catalogSourceAggregateSha256"],
        "catalogCoverageVersion": source["equality"]["catalogCoverageVersion"],
    }
    prior_state = candidate["immutablePriorState"]
    assert prior_state["priorCandidatePath"] == "docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json"
    assert prior_state["priorCandidateSha256"] == EXPECTED_BINDINGS[prior_state["priorCandidatePath"]]
    assert prior_state["activeDeferralPath"] == "docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json"
    assert prior_state["activeDeferralSha256"] == EXPECTED_BINDINGS[prior_state["activeDeferralPath"]]
    assert prior_state["activeDeferralBindsPriorCandidateOnly"] is True
    assert deferral["candidatePath"] == prior_state["priorCandidatePath"]
    assert deferral["candidateSha256"] == prior_state["priorCandidateSha256"]
    assert prior["route"] == candidate["route"] == deferral["route"] == "E0/E0.3/B5.3/064A"
    assert handoff["candidatePath"] == "docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json"
    assert handoff["candidateSha256"] == EXPECTED_BINDINGS[handoff["candidatePath"]]
    assert handoff["sourcePath"] == candidate["sourceObservation"]["path"]
    assert handoff["sourceSha256"] == candidate["sourceObservation"]["sha256"]
    assert handoff["priorCandidatePath"] == prior_state["priorCandidatePath"]
    assert handoff["priorCandidateSha256"] == prior_state["priorCandidateSha256"]
    assert handoff["activeDeferralPath"] == prior_state["activeDeferralPath"]
    assert handoff["activeDeferralSha256"] == prior_state["activeDeferralSha256"]


def test_v4_source_is_expired_and_freshness_never_authorizes():
    evidence = _load(EVIDENCE)
    window = evidence["sourceWindow"]
    observed = _time(window["sourceObservedAt"])
    expired = _time(window["expiredAt"])
    evaluated = _time(window["evaluatedAt"])
    assert expired == observed + timedelta(seconds=window["maximumAgeSeconds"])
    assert evaluated > expired
    assert window["status"] == "EXPIRED_SOURCE"
    assert window["freshnessCanInvalidate"] is True
    assert window["freshnessCanAuthorize"] is False
    assert window["currentProductionTruth"] is False

    candidate = _load(ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json")
    source = _load(ROOT / candidate["sourceObservation"]["path"])
    assert window["sourceObservedAt"] == candidate["sourceObservation"]["observedAt"] == source["observedAt"]
    assert window["maximumAgeSeconds"] == candidate["sourceObservation"]["maximumAgeSecondsAtDecision"]
    assert candidate["candidateStatus"] == "AWAITING_NEW_AUTHENTICATED_DECISION"
    assert candidate["authority"]["ownerApprovalPresent"] is False
    assert candidate["authority"]["independentReviewerApprovalPresent"] is False
    assert candidate["authority"]["actionAllowed"] is False


def test_public_v4_binding_does_not_overclaim_current_implementation_binding():
    evidence = _load(EVIDENCE)
    binding = evidence["implementationBinding"]
    decision_input = ROOT / binding["historicalDecisionInputPath"]
    assert hashlib.sha256(decision_input.read_bytes()).hexdigest() == binding["historicalDecisionInputSha256"]
    assert binding["publicV4CrossBindingsMatch"] is True
    assert binding["currentImplementationBytesRevalidated"] is False
    assert binding["status"] == "STALE_SUPPORTING_IMPLEMENTATION_DIGESTS"

    historical = _load(decision_input)
    bound = {item["artifactId"]: item["sha256"] for item in historical["artifactDigests"]}
    assert [item["artifactId"] for item in binding["drift"]] == [
        "bootstrap_roles",
        "prepare_database",
        "runtime_privileges",
    ]
    for item in binding["drift"]:
        current = hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
        assert item["boundSha256"] == bound[item["artifactId"]]
        assert item["currentSha256"] == current
        assert item["boundSha256"] != item["currentSha256"]


def test_legacy_v1_freshness_package_stays_fail_closed_on_drift():
    evidence = _load(EVIDENCE)
    expected = evidence["legacyV1FreshnessVerifier"]
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/b64_064a_decision_freshness.py"),
            "--root",
            str(ROOT),
            "--now",
            str(expected["evaluatedAtEpoch"]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 2
    result = json.loads(process.stdout)
    assert result["evaluatedTimeSource"] == expected["evaluatedTimeSource"]
    for field in (
        "status",
        "gateStatus",
        "packageIntegrity",
        "technicalEvidenceCurrent",
        "signingPreparationEligible",
    ):
        assert result[field] == expected[field]
    assert set(expected["reasonCodesRequired"]).issubset(result["reasonCodes"])
    assert result["productionExpandAuthorized"] is False
    assert result["productionMutationAuthorized"] is False
    assert result["actionAllowed"] is False


def test_reconciliation_preserves_every_authority_boundary():
    evidence = _load(EVIDENCE)
    assert evidence["scopeDecision"] == {
        "source": "CURRENT_OWNER_CONVERSATION_CONTEXT_ONLY",
        "reason": "OWNER_REQUESTED_CONTINUATION_OUTSIDE_E4_AFTER_E4_FATIGUE",
        "returnsToFirstUnmetCanonicalGate": True,
        "e4ExcludedFromCurrentTask": True,
        "e4StatusPreserved": "IN_PROGRESS",
        "e4GateDecisionPreserved": "NO_GO",
        "changesE4Authority": False,
        "authenticated064aDecision": False,
        "waiverGranted": False,
    }
    assert evidence["decisionState"]["refreshAuthorized"] is False
    assert evidence["decisionState"]["refreshDeferredUntilReviewerReady"] is True
    assert evidence["authority"] and all(value is False for value in evidence["authority"].values())
    assert evidence["workPerformed"]["localPublicArtifactReadOnly"] is True
    assert evidence["workPerformed"]["documentationAndTestsUpdated"] is True
    assert all(
        value is False
        for key, value in evidence["workPerformed"].items()
        if key not in {"localPublicArtifactReadOnly", "documentationAndTestsUpdated"}
    )
    scope = evidence["worktreeScope"]
    assert scope["repositoryFilesTouchedByThisSlice"] == [
        "docs/e0-3-bot-b5-3-064a-current-authority-reconciliation.v1.json",
        "docs/e0-gate-status.v1.json",
        "docs/ecosystem-master-roadmap.md",
        "tests/test_e0_3_bot_b5_3_064a_current_authority_reconciliation.py",
        "tests/test_e0_3_bot_b5_3_064a_decision.py",
        "tests/test_e0_3_bot_b5_3_064a_freshness.py",
        "PROJECT_MEMORY.md",
    ]
    assert scope["unrelatedPreExistingWorktreeChangesPresent"] is True
    assert scope["unrelatedPreExistingWorktreeChangesPreserved"] is True
    assert scope["claimsWholeWorktreeCleanOrReviewed"] is False


def test_machine_gate_ledger_matches_reconciled_first_unmet_status():
    evidence = _load(EVIDENCE)
    ledger = _load(LEDGER)
    stage = ledger["stage"]
    assert ledger["observedAt"] == "2026-08-18T18:57:23Z"
    reconciliation = ledger["statusReconciliation"]
    assert _time(reconciliation["reconciledAt"]) >= _time(evidence["observedAt"])
    assert any(item.startswith("E0.3") for item in reconciliation["scope"])
    assert reconciliation["productionReobserved"] is False
    assert reconciliation["runtimeReobserved"] is False
    assert reconciliation["preservesOriginalStageObservationProvenance"] is True
    criterion = next(item for item in stage["criteria"] if item["id"] == "E0.3")
    assert stage["id"] == "E0"
    assert stage["status"] == evidence["canonicalGateStatus"]["stageStatus"]
    assert stage["firstUnmetCriterion"] == evidence["canonicalGateStatus"]["firstUnmetCriterion"]
    assert criterion["status"] == evidence["canonicalGateStatus"]["firstUnmetStatus"]
    assert str(EVIDENCE.relative_to(ROOT)) in criterion["latestEvidence"]
    assert "operational refresh remains NO_GO" in criterion["blocker"]


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            globals()[name]()
    print("064A_CURRENT_AUTHORITY_RECONCILIATION_PASS")
