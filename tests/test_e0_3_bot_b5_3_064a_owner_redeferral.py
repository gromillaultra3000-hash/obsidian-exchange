import hashlib
import json
from pathlib import Path


ROOT = Path("/root")
REDEFERRAL = ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v2.json"
CANDIDATE = ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v2.json"
PRIOR_DEFERRAL = ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json"
PRIOR_INPUT = ROOT / "docs/e0-3-bot-b5-3-064a-decision-input.v1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_redeferral_binds_exact_candidate_and_preserves_prior_history():
    value = load(REDEFERRAL)
    assert value["candidateSha256"] == sha(CANDIDATE)
    assert value["immutablePriorState"]["priorDeferralSha256"] == sha(PRIOR_DEFERRAL)
    assert value["immutablePriorState"]["priorDecisionInputSha256"] == sha(PRIOR_INPUT)
    assert value["candidateRequestedDecision"] == "ACCEPT_BOUNDED_EVIDENCE_ONLY"
    assert value["candidateEffect"] == "EVIDENCE_ACCEPTANCE_ONLY"
    assert value["decisionEffect"] == "RESTRICTIVE_RE_DEFERRAL_ONLY"
    assert value["ownerReDeferralDecisionPresent"] is True
    assert value["status"] == "BLOCKED_OWNER"


def test_redeferral_cannot_authorize_acceptance_or_any_effect():
    value = load(REDEFERRAL)
    assert value["authenticatedEvidenceAcceptancePresent"] is False
    assert value["independentReviewerAcceptancePresent"] is False
    assert set(value["authority"].values()) == {False}
    assert value["sourceFreshnessEffect"] == {
        "freshnessCanInvalidate": True,
        "freshnessCanAuthorize": False,
        "candidateMayExpireWhileDeferred": True,
        "expiredCandidateRequiresNewReadOnlyObservationAndNewDigest": True,
    }


def test_ambiguous_rows_and_next_safe_route_remain_bounded():
    value = load(REDEFERRAL)
    observed = value["observedProductionBlockers"]
    assert observed == {
        "sendingRows": 13,
        "staleSendingRows": 11,
        "rowsMutatedByDecision": 0,
        "separate064DDispositionRequired": True,
    }
    assert "064D_AMBIGUOUS_SENDING_DISPOSITION" in value["deferredItems"]
    assert value["nextSafeRoute"] == "E0/E0.4/POST_25_CLOSURE_RECONCILIATION"
    assert value["allowedWork"] == [
        "KEYLESS", "READ_ONLY", "NON_PRODUCTION", "DOCUMENTATION_AND_TESTS"
    ]
