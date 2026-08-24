import hashlib
import json
from pathlib import Path


ROOT = Path("/root")
DEFERRAL_PATH = ROOT / "docs/e5-issuer-selection-owner-reviewer-deferral.v1.json"


def _load() -> dict:
    return json.loads(DEFERRAL_PATH.read_text(encoding="utf-8"))


def test_e5_deferral_binds_exact_current_owner_reviewer_contracts():
    data = _load()
    for path_field, digest_field in [
        ("decisionResultEnvelopeSchemaPath", "decisionResultEnvelopeSchemaSha256"),
        ("ownerReviewerHandoffSchemaPath", "ownerReviewerHandoffSchemaSha256"),
        ("selectionScorecardPath", "selectionScorecardSha256"),
    ]:
        path = ROOT / data[path_field]
        assert data[digest_field] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert data["decisionEffect"] == "RESTRICTIVE_DEFERRAL_ONLY"
    assert data["status"] == "BLOCKED_OWNER"
    assert data["sourceAuthentication"] == "CONVERSATION_CONTEXT_NOT_AUTHENTICATED_SIGNATURE"


def test_e5_deferral_preserves_blocked_authority_and_safe_work_only():
    data = _load()
    assert data["ownerDecisionContextPresent"] is True
    assert data["authenticatedOwnerDecisionPresent"] is False
    assert data["authenticatedIndependentReviewerDecisionPresent"] is False
    assert set(data["allowedWork"]) == {
        "KEYLESS", "READ_ONLY", "NON_PRODUCTION", "DOCUMENTATION_AND_TESTS",
    }
    assert all(value is False for value in data["authority"].values())
    assert data["sourceFreshnessEffect"]["freshnessCanAuthorize"] is False
    assert data["sourceFreshnessEffect"]["candidateMayExpireWhileDeferred"] is True
    assert "E5_ISSUER_SELECTION_CONSUMPTION" in data["deferredItems"]
    assert "E5_NATIVE_PRODUCTION_SIGNING" in data["deferredItems"]


def test_e5_deferral_does_not_turn_conversation_context_into_acceptance():
    data = _load()
    interpretation = data["interpretation"]
    for marker in [
        "does not authenticate a signature",
        "does not",
        "remains BLOCKED_OWNER",
    ]:
        assert marker in interpretation
    assert "waiver" in interpretation
    assert "select an issuer" in interpretation
