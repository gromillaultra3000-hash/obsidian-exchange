import hashlib
import json
from pathlib import Path


ROOT = Path("/root")
REFRESH = ROOT / "docs/e0-3-bot-b5-3-064a-production-source-refresh.v2.json"
CANDIDATE = ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v2.json"
PRIOR = ROOT / "docs/e0-3-bot-b5-3-064a-decision-input.v1.json"
DEFERRAL = ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_new_candidate_binds_exact_refresh_and_preserves_prior_deferral():
    refresh = json.loads(REFRESH.read_text())
    candidate = json.loads(CANDIDATE.read_text())
    deferral = json.loads(DEFERRAL.read_text())
    assert candidate["requestedDecision"] == "ACCEPT_BOUNDED_EVIDENCE_ONLY"
    assert candidate["effect"] == "EVIDENCE_ACCEPTANCE_ONLY"
    assert candidate["sourceObservation"]["sha256"] == sha(REFRESH)
    assert candidate["immutablePriorState"]["priorDecisionInputSha256"] == sha(PRIOR)
    assert candidate["immutablePriorState"]["activeDeferralSha256"] == sha(DEFERRAL)
    assert deferral["decisionInputSha256"] == sha(PRIOR)
    assert refresh["source"]["sourceClusterSha256"] == candidate["sourceBinding"]["sourceClusterSha256"]
    assert refresh["archive"]["sha256"] == candidate["sourceBinding"]["archiveSha256"]
    assert refresh["equality"]["tableSourceAndRestoreSha256"] == candidate["sourceBinding"]["tableFingerprintSha256"]
    assert refresh["equality"]["catalogSourceAggregateSha256"] == candidate["sourceBinding"]["catalogFingerprintSha256"]


def test_refresh_is_secret_free_bounded_and_cleanup_complete():
    refresh = json.loads(REFRESH.read_text())
    assert refresh["dirtyData"]["privacy"] == "NO_IDENTIFIERS_OR_PAYLOAD"
    assert refresh["dirtyData"]["criterionStatus"] == "BLOCKED"
    assert refresh["dirtyData"]["counts"]["sending"] == 13
    assert refresh["dirtyData"]["counts"]["staleSending"] == 11
    assert refresh["equality"]["differentTables"] == []
    assert refresh["equality"]["differentDatabaseLocalSections"] == []
    assert refresh["equality"]["differentClusterGlobalSections"] == []
    assert refresh["equality"]["sequenceRuntimeStateCompared"] is False
    assert set(refresh["cleanup"].values()) == {True}
    assert refresh["archive"]["retained"] is False


def test_candidate_cannot_authorize_any_effect():
    candidate = json.loads(CANDIDATE.read_text())
    authority = candidate["authority"]
    assert candidate["candidateStatus"] == "AWAITING_NEW_AUTHENTICATED_DECISION"
    assert authority["freshnessCanInvalidate"] is True
    for key, value in authority.items():
        if key != "freshnessCanInvalidate":
            assert value is False
    assert any("OWNER" in blocker for blocker in candidate["knownBlockers"])
    assert any("INDEPENDENT_REVIEWER" in blocker for blocker in candidate["knownBlockers"])
    assert any("13_LEGACY_SENDING" in blocker for blocker in candidate["knownBlockers"])


def test_prior_input_and_deferral_known_digests_are_unchanged():
    assert sha(PRIOR) == "f8abf0cb858232df2497221c44a319975403ccb7a8e2d2403bd57bda8c904bbb"
    assert sha(DEFERRAL) == "a701300a921f5345aaaab3772fc62ffae8be001d719671a1dd9b3478ecb60196"
