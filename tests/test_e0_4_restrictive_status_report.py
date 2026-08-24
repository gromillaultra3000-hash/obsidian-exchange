import hashlib
import json
from pathlib import Path


ROOT = Path("/root")
DOC = ROOT / "docs/e0-4-restrictive-status-report.v1.json"
AUTHORITY_KEYS = {
    "productionAuthorization",
    "productionMutationAuthorized",
    "productionExpandAuthorized",
    "deploymentAuthorized",
    "telegramDeliveryAuthorized",
    "paymentMutationAuthorized",
    "adminMutationAuthorized",
    "actionAllowed",
}


def load_report():
    return json.loads(DOC.read_text())


def test_report_separates_artifact_closure_from_gate_acceptance():
    data = load_report()
    assert data["route"] == "E0/E0.4/RESTRICTIVE_STATUS_REPORT"
    assert data["boundedSliceStatus"] == "BLOCKED_OWNER"
    assert data["decisionEffect"] == "CLOSED_RESTRICTIVE_REPORT_NO_AUTHORITY"
    assert data["canonicalGateStatus"] == {
        "firstUnmetGate": "E0.3",
        "firstUnmetStatus": "BLOCKED_OWNER",
        "E0.4": "IN_PROGRESS",
        "E0": "IN_PROGRESS",
    }
    assert data["reportClosure"]["reportComplete"] is True
    for field, value in data["reportClosure"].items():
        if field != "reportComplete":
            assert value is False, field


def test_authority_is_closed_non_vacuous_and_all_false():
    authority = load_report()["authority"]
    assert set(authority) == AUTHORITY_KEYS
    assert all(value is False for value in authority.values())


def test_every_evidence_binding_matches_current_raw_bytes():
    bindings = load_report()["evidenceBindings"]
    assert len(bindings) == 5
    assert len({item["path"] for item in bindings}) == len(bindings)
    for item in bindings:
        raw = (ROOT / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]


def test_historical_pass_and_route_do_not_create_authority():
    data = load_report()
    assert data["source"] == {
        "kind": "CURRENT_OWNER_CONVERSATION_CONTEXT_ONLY",
        "authenticated": False,
        "trustedTime": False,
        "currentProductionTruth": False,
    }
    assert data["historicalEvidencePolicy"] == {
        "asOfOnly": True,
        "freshnessProven": False,
        "expiryCreatesAuthority": False,
        "syntheticRehearsalPassIsAcceptance": False,
    }
    assert "E0.3/064B" in data["prohibitions"]
    assert "E0.3/064D" in data["prohibitions"]
    assert data["conclusion"] == "NO_OWNER_DECISION_CAN_BE_INFERRED_NO_REMEDIATION_OR_ACCEPTANCE"
    assert data["nextCanonicalItem"] == "E0/E0.3/B5.3/064A_ACCOUNTABLE_OWNER_AND_INDEPENDENT_REVIEWER_DECISION"
    assert "grants no authority" in data["nextItemConstraint"]


def test_gap_list_is_explicitly_a_lower_bound():
    data = load_report()
    assert len(data["confirmedGapLowerBound"]) == 8
    assert data["reportClosure"]["inventoryComplete"] is False
    assert data["reportClosure"]["noCriticalHighGaps"] is False
