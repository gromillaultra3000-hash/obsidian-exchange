import hashlib
from pathlib import Path


ROOT = Path("/root")
RUNBOOK = ROOT / "docs/b64-064a-offline-signing-v3.md"
CANDIDATE = ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json"
SOURCE = ROOT / "docs/e0-3-bot-b5-3-064a-production-source-refresh.v3.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v3_handoff_pins_exact_current_decision_and_source():
    text = RUNBOOK.read_text()
    assert sha(CANDIDATE) == "771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf"
    assert sha(SOURCE) == "280e0b0de3c76992ef1674ef76495a0136138c9ee6ab114ff794f8377437d104"
    assert sha(CANDIDATE) in text and sha(SOURCE) in text
    assert "--decision-input /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v3.json" in text
    assert "The v2 candidate is prior-state evidence only" in text


def test_statement_creation_requires_all_cross_bound_inputs():
    runbook = RUNBOOK.read_text()
    signer = (ROOT / "scripts/b64_064a_offline_signer.py").read_text()
    for flag in ("--source-observation", "--prior-state", "--active-deferral"):
        assert runbook.count(flag) >= 2 and signer.count(f'add_argument("{flag}",required=True)') == 2
    assert "_validate_candidate_evidence" in signer
    assert "EVIDENCE_BINDING_INVALID" in signer
    assert "PRIOR_STATE_BINDING_INVALID" in signer
    assert "EVIDENCE_BUNDLE_DIGEST_MISMATCH" in signer


def test_handoff_never_claims_operational_acceptance():
    text = RUNBOOK.read_text()
    for claim in (
        "replayProtectionVerified:false", "boundedEvidenceAccepted:false",
        "productionExpandAuthorized:false", "cutoverAuthorized:false",
        "actionAllowed:false",
    ):
        assert claim in text
    assert "cannot clear `BLOCKED_OWNER`" in text
