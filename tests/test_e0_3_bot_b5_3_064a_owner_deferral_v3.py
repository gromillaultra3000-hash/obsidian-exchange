import hashlib
import json
from pathlib import Path

ROOT = Path("/root")
DOC = ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json"

def test_v3_redeferral_binds_exact_candidate_and_source():
    data = json.loads(DOC.read_text())
    assert data["candidateSha256"] == hashlib.sha256((ROOT / data["candidatePath"]).read_bytes()).hexdigest()
    assert data["sourceObservationSha256"] == hashlib.sha256((ROOT / data["sourceObservationPath"]).read_bytes()).hexdigest()
    assert data["decisionEffect"] == "RESTRICTIVE_RE_DEFERRAL_ONLY"
    assert data["status"] == "BLOCKED_OWNER"
    assert data["authenticatedOwnerDecisionPresent"] is False
    assert set(data["allowedWork"]) == {"KEYLESS", "READ_ONLY", "NON_PRODUCTION", "DOCUMENTATION_AND_TESTS"}
    superseded = ROOT / data["supersedesDeferralPath"]
    assert data["supersedesDeferralSha256"] == hashlib.sha256(superseded.read_bytes()).hexdigest()
    assert data["supersedesDeferralSha256"] != data["candidateSha256"]

def test_v3_redeferral_preserves_false_authority_and_064b_064d_blocks():
    data = json.loads(DOC.read_text())
    assert all(value is False for value in data["authority"].values())
    assert "064B_PRODUCTION_EXPAND" in data["deferredItems"]
    assert "064D_AMBIGUOUS_SENDING_DISPOSITION" in data["deferredItems"]
    assert data["sourceFreshnessEffect"]["freshnessCanAuthorize"] is False
