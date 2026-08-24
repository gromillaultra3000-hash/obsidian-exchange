import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


ROOT = Path("/root")
REFRESH = ROOT / "docs/e0-3-bot-b5-3-064a-production-source-refresh.v3.json"
CANDIDATE = ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json"
PRIOR = ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v2.json"
DEFERRAL = ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v2.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v3_candidate_binds_exact_fresh_source_and_active_deferral():
    refresh = json.loads(REFRESH.read_text())
    candidate = json.loads(CANDIDATE.read_text())
    assert candidate["requestedDecision"] == "ACCEPT_BOUNDED_EVIDENCE_ONLY"
    assert candidate["effect"] == "EVIDENCE_ACCEPTANCE_ONLY"
    assert candidate["sourceObservation"]["sha256"] == sha(REFRESH)
    assert candidate["immutablePriorState"]["priorCandidateSha256"] == sha(PRIOR)
    assert candidate["immutablePriorState"]["activeDeferralSha256"] == sha(DEFERRAL)
    assert candidate["immutablePriorState"]["activeDeferralRemainsRestrictive"] is True
    assert refresh["source"]["sourceClusterSha256"] == candidate["sourceBinding"]["sourceClusterSha256"]
    assert refresh["archive"]["sha256"] == candidate["sourceBinding"]["archiveSha256"]
    assert refresh["equality"]["tableSourceAndRestoreSha256"] == candidate["sourceBinding"]["tableFingerprintSha256"]
    assert refresh["equality"]["catalogSourceAggregateSha256"] == candidate["sourceBinding"]["catalogFingerprintSha256"]


def test_refresh_records_stricter_dirty_state_and_exact_restore_cleanup():
    refresh = json.loads(REFRESH.read_text())
    counts = refresh["dirtyData"]["counts"]
    assert counts == {
        "total": 95, "sent": 81, "pending": 1, "sending": 13,
        "staleSending": 11, "monteraAdmin": 1, "activeMonteraAdmin": 0,
        "invalidState": 0, "invalidKind": 0, "invalidLifecycle": 0,
        "invalidActiveRecipientShape": 0,
    }
    assert refresh["dirtyData"]["criterionStatus"] == "BLOCKED"
    assert refresh["equality"]["differentTables"] == []
    assert refresh["equality"]["differentDatabaseLocalSections"] == []
    assert refresh["equality"]["differentClusterGlobalSections"] == []
    assert refresh["equality"]["sequenceRuntimeStateCompared"] is False
    assert set(refresh["cleanup"].values()) == {True}
    assert refresh["archive"]["retained"] is False


def test_candidate_is_signer_compatible_but_cannot_authorize_effects():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "offline_signer", ROOT / "scripts/b64_064a_offline_signer.py")
    signer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signer)
    candidate = json.loads(CANDIDATE.read_text())
    signer._validate_v2_candidate(candidate, issued_at=1787108400)
    assert candidate["candidateStatus"] == "AWAITING_NEW_AUTHENTICATED_DECISION"
    assert candidate["authority"]["freshnessCanInvalidate"] is True
    for key, value in candidate["authority"].items():
        if key != "freshnessCanInvalidate":
            assert value is False
    assert any("1_PENDING" in blocker for blocker in candidate["knownBlockers"])
    assert any("13_LEGACY_SENDING" in blocker for blocker in candidate["knownBlockers"])


def test_observed_time_is_conservative_and_window_is_bounded():
    refresh = json.loads(REFRESH.read_text())
    candidate = json.loads(CANDIDATE.read_text())
    assert refresh["observedAt"] == candidate["sourceObservation"]["observedAt"]
    assert refresh["observedAt"] < refresh["recordedAt"]
    assert candidate["sourceObservation"]["maximumAgeSecondsAtDecision"] == 86400


def test_signer_rejects_tampered_binding_and_freshness_boundaries():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "offline_signer_v3", ROOT / "scripts/b64_064a_offline_signer.py")
    signer = importlib.util.module_from_spec(spec); spec.loader.exec_module(signer)
    candidate = json.loads(CANDIDATE.read_text())
    observed = 1787106894
    signer._validate_v2_candidate(candidate, issued_at=observed)
    for invalid in (observed - 1, observed + 86400, observed + 86401):
        try:
            signer._validate_v2_candidate(candidate, issued_at=invalid)
        except signer.SafeError as exc:
            assert str(exc) == "SOURCE_OBSERVATION_NOT_CURRENT"
        else:
            raise AssertionError("out-of-window signing time accepted")
    with tempfile.TemporaryDirectory(prefix="b64-v3-test-") as raw:
        root = Path(raw); os.chmod(root, 0o700)
        copies = {}
        for name, original in (("source", REFRESH), ("prior", PRIOR), ("deferral", DEFERRAL)):
            copies[name] = root / original.name
            shutil.copyfile(original, copies[name]); os.chmod(copies[name], 0o600)
        signer._validate_candidate_evidence(
            candidate, source_path=str(copies["source"]),
            prior_state_path=str(copies["prior"]),
            active_deferral_path=str(copies["deferral"]))
        changed = json.loads(json.dumps(candidate))
        changed["sourceObservation"]["sha256"] = "0" * 64
        try:
            signer._validate_candidate_evidence(
                changed, source_path=str(copies["source"]),
                prior_state_path=str(copies["prior"]),
                active_deferral_path=str(copies["deferral"]))
        except signer.SafeError as exc:
            assert str(exc) == "EVIDENCE_BINDING_INVALID"
        else:
            raise AssertionError("tampered evidence binding accepted")
        changed_source = json.loads(copies["source"].read_text())
        changed_source["equality"]["databaseLocalStatus"] = "MISMATCH"
        changed_source["equality"]["differentDatabaseLocalSections"] = ["column_acl"]
        copies["source"].write_text(json.dumps(changed_source)); os.chmod(copies["source"], 0o600)
        changed = json.loads(json.dumps(candidate))
        changed["sourceObservation"]["sha256"] = hashlib.sha256(copies["source"].read_bytes()).hexdigest()
        try:
            signer._validate_candidate_evidence(
                changed, source_path=str(copies["source"]),
                prior_state_path=str(copies["prior"]),
                active_deferral_path=str(copies["deferral"]))
        except signer.SafeError as exc:
            assert str(exc) == "EVIDENCE_BINDING_INVALID"
        else:
            raise AssertionError("mismatched restore evidence accepted")
        shutil.copyfile(REFRESH, copies["source"]); os.chmod(copies["source"], 0o600)
        changed = json.loads(json.dumps(candidate))
        changed["knownBlockers"] = [
            "1_PENDING_MUST_DRAIN_OR_BE_RECONCILED_BEFORE_ANY_MIGRATION",
            "13_LEGACY_SENDING_REQUIRE_SEPARATE_064D_IMMUTABLE_OPERATOR_DISPOSITION",
        ]
        try:
            signer._validate_candidate_evidence(
                changed, source_path=str(copies["source"]),
                prior_state_path=str(copies["prior"]),
                active_deferral_path=str(copies["deferral"]))
        except signer.SafeError as exc:
            assert str(exc) == "BOUNDED_BLOCKERS_INVALID"
        else:
            raise AssertionError("governance blocker removal accepted")
