import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/b64_064a_offline_signer.py"
NOW = 1_787_083_200
PASSWORD = b"synthetic-test-passphrase-only\n"


def run(args, passphrase=False):
    read_fd = write_fd = None
    kwargs = {}
    if passphrase:
        read_fd, write_fd = os.pipe()
        os.write(write_fd, PASSWORD); os.close(write_fd)
        args += ["--passphrase-fd", str(read_fd)]
        kwargs["pass_fds"] = (read_fd,)
    try:
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                                text=True, capture_output=True, check=False, **kwargs)
    finally:
        if read_fd is not None: os.close(read_fd)
    return result, json.loads(result.stdout)


def secure(tmp_path):
    os.chmod(tmp_path, 0o700)
    decision = tmp_path / "decision.json"
    shutil.copyfile(ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v2.json", decision)
    os.chmod(decision, 0o600)
    source = tmp_path / "e0-3-bot-b5-3-064a-production-source-refresh.v2.json"
    prior = tmp_path / "e0-3-bot-b5-3-064a-decision-input.v1.json"
    deferral = tmp_path / "e0-3-bot-b5-3-064a-owner-deferral.v1.json"
    for original, copied in (
        (ROOT / "docs/e0-3-bot-b5-3-064a-production-source-refresh.v2.json", source),
        (ROOT / "docs/e0-3-bot-b5-3-064a-decision-input.v1.json", prior),
        (ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json", deferral),
    ):
        shutil.copyfile(original, copied); os.chmod(copied, 0o600)
    return decision, source, prior, deferral


def workflow(tmp_path):
    decision, source, prior, deferral = secure(tmp_path)
    review_key, review_pub = tmp_path / "review.key", tmp_path / "review.json"
    owner_key, owner_pub = tmp_path / "owner.key", tmp_path / "owner.json"
    for role, identity, domain, key, public in (
        ("INDEPENDENT_REVIEWER", "reviewer_1", "review_org", review_key, review_pub),
        ("ACCOUNTABLE_OWNER", "owner_1", "owner_org", owner_key, owner_pub),
    ):
        result, receipt = run(["generate-key", "--role", role, "--identity-id", identity,
            "--trust-domain", domain, "--private-out", key, "--public-out", public], True)
        assert result.returncode == 0 and receipt["productionAuthority"] is False
    keyring = tmp_path / "keyring.json"
    assert run(["build-keyring", "--reviewer-public", review_pub, "--owner-public", owner_pub,
                "--out", keyring])[0].returncode == 0
    statement = tmp_path / "statement.json"
    assert run(["create-statement", "--decision-input", decision, "--keyring", keyring,
        "--source-observation", source, "--prior-state", prior,
        "--active-deferral", deferral,
        "--issued-at", NOW, "--expires-at", NOW + 3600,
        "--nonce", "AQEBAQEBAQEBAQEBAQEBAQ", "--out", statement])[0].returncode == 0
    review = tmp_path / "review-envelope.json"
    assert run(["sign-reviewer", "--statement", statement, "--keyring", keyring,
        "--private-key", review_key, "--nonce", "AgICAgICAgICAgICAgICAg", "--out", review], True)[0].returncode == 0
    owner = tmp_path / "owner-envelope.json"
    assert run(["sign-owner", "--statement", statement, "--keyring", keyring,
        "--private-key", owner_key, "--reviewer", review,
        "--nonce", "AwMDAwMDAwMDAwMDAwMDAw", "--out", owner], True)[0].returncode == 0
    return decision, keyring, statement, review, owner, review_key, owner_key, source, prior, deferral


def test_full_offline_candidate_flow_is_valid_but_never_authoritative(tmp_path):
    decision, keyring, statement, review, owner, review_key, owner_key, source, prior, deferral = workflow(tmp_path)
    frozen = json.loads(statement.read_text())
    assert frozen["schemaVersion"] == "b64-064a-decision-statement.v2"
    assert frozen["sourceObservedAtEpoch"] == 1787082017
    assert frozen["sourceExpiresAtEpoch"] == 1787168417
    result, receipt = run(["verify", "--decision-input", decision, "--statement", statement,
        "--source-observation", source, "--prior-state", prior,
        "--active-deferral", deferral,
        "--reviewer", review, "--owner", owner, "--keyring", keyring, "--now", NOW + 1])
    assert result.returncode == 0
    assert receipt["status"] == "SYNTHETIC_VALID"
    assert receipt["syntheticProtocolValid"] is True
    assert receipt["replayProtectionVerified"] is False
    for field in ("authenticatedOwnerReviewerGo", "boundedEvidenceAccepted",
                  "productionExpandAuthorized", "cutoverAuthorized", "actionAllowed",
                  "productionAuthority"):
        assert receipt[field] is False
    assert oct(review_key.stat().st_mode & 0o777) == "0o600"
    assert oct(owner_key.stat().st_mode & 0o777) == "0o600"
    assert PASSWORD.strip().decode() not in result.stdout + result.stderr


def test_tamper_existing_output_wrong_permissions_and_symlink_fail_closed(tmp_path):
    decision, keyring, statement, review, owner, review_key, owner_key, source, prior, deferral = workflow(tmp_path)
    value = json.loads(statement.read_text()); value["cutoverAuthorized"] = True
    statement.write_text(json.dumps(value)); os.chmod(statement, 0o600)
    result, receipt = run(["verify", "--decision-input", decision, "--statement", statement,
        "--source-observation", source, "--prior-state", prior,
        "--active-deferral", deferral,
        "--reviewer", review, "--owner", owner, "--keyring", keyring, "--now", NOW + 1])
    assert result.returncode == 0 and receipt["status"] == "INVALID"
    existing = tmp_path / "existing.json"; existing.write_text("keep"); os.chmod(existing, 0o600)
    assert run(["build-keyring", "--reviewer-public", review, "--owner-public", owner,
                "--out", existing])[0].returncode != 0
    os.chmod(review_key, 0o644)
    failed, output = run(["sign-reviewer", "--statement", statement, "--keyring", keyring,
        "--private-key", review_key, "--nonce", "BAQEBAQEBAQEBAQEBAQEBA", "--out", tmp_path / "x"], True)
    assert failed.returncode != 0 and output["actionAllowed"] is False
    link = tmp_path / "link.key"; link.symlink_to(owner_key)
    failed, _ = run(["sign-owner", "--statement", statement, "--keyring", keyring,
        "--private-key", link, "--reviewer", review,
        "--nonce", "BQUFBQUFBQUFBQUFBQUFBQ", "--out", tmp_path / "y"], True)
    assert failed.returncode != 0


def test_v2_candidate_scope_authority_and_source_window_fail_closed(tmp_path):
    for name, mutate, error in (
        ("scope", lambda value: value.update(requestedDecision="APPROVE_064B_EXPAND_ONLY"),
         "INVALID_DECISION_INPUT"),
        ("authority", lambda value: value["authority"].update(actionAllowed=True),
         "INVALID_DECISION_INPUT"),
        ("stale", lambda value: value["sourceObservation"].update(observedAt="2026-08-16T19:40:17Z"),
         "SOURCE_OBSERVATION_NOT_CURRENT"),
        ("exact-expiry", lambda value: value["sourceObservation"].update(observedAt="2026-08-17T20:00:00Z"),
         "SOURCE_OBSERVATION_NOT_CURRENT"),
        ("source-window-tamper", lambda value: value["sourceObservation"].update(observedAt="2026-08-18T19:40:16Z"),
         "EVIDENCE_BINDING_INVALID"),
    ):
        root = tmp_path / name
        root.mkdir(); os.chmod(root, 0o700)
        decision, keyring, *_ = workflow(root)
        value = json.loads(decision.read_text()); mutate(value)
        decision.write_text(json.dumps(value)); os.chmod(decision, 0o600)
        result, receipt = run(["create-statement", "--decision-input", decision,
            "--source-observation", root / "e0-3-bot-b5-3-064a-production-source-refresh.v2.json",
            "--prior-state", root / "e0-3-bot-b5-3-064a-decision-input.v1.json",
            "--active-deferral", root / "e0-3-bot-b5-3-064a-owner-deferral.v1.json",
            "--keyring", keyring, "--issued-at", NOW, "--expires-at", NOW + 3600,
            "--out", root / "rejected-statement.json"])
        assert result.returncode != 0 and receipt["errorCode"] == error
        assert receipt["actionAllowed"] is False


def test_statement_expiry_cannot_outlive_source_and_cleanup_keys_are_exact(tmp_path):
    decision, keyring, *_ = workflow(tmp_path)
    common = ["create-statement", "--decision-input", decision,
        "--source-observation", tmp_path / "e0-3-bot-b5-3-064a-production-source-refresh.v2.json",
        "--prior-state", tmp_path / "e0-3-bot-b5-3-064a-decision-input.v1.json",
        "--active-deferral", tmp_path / "e0-3-bot-b5-3-064a-owner-deferral.v1.json",
        "--keyring", keyring, "--issued-at", NOW]
    result, receipt = run([*common, "--expires-at", 1787168418,
                           "--out", tmp_path / "outlives-source.json"])
    assert result.returncode != 0
    assert receipt["errorCode"] == "INVALID_STATEMENT_WINDOW"
    assert receipt["actionAllowed"] is False

    source = tmp_path / "e0-3-bot-b5-3-064a-production-source-refresh.v2.json"
    value = json.loads(source.read_text())
    value["cleanup"] = {"archiveAbsent": True}
    source.write_text(json.dumps(value)); os.chmod(source, 0o600)
    candidate = json.loads(decision.read_text())
    candidate["sourceObservation"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    decision.write_text(json.dumps(candidate)); os.chmod(decision, 0o600)
    result, receipt = run([*common, "--expires-at", NOW + 3600,
                           "--out", tmp_path / "weak-cleanup.json"])
    assert result.returncode != 0
    assert receipt["errorCode"] == "EVIDENCE_BINDING_INVALID"
    assert receipt["actionAllowed"] is False


def test_v4_candidate_binds_v3_restrictive_deferral(tmp_path):
    _, keyring, _, _, _, review_key, owner_key, *_ = workflow(tmp_path)
    decision = tmp_path / "e0-3-bot-b5-3-064a-decision-candidate.v4.json"
    source = tmp_path / "e0-3-bot-b5-3-064a-production-source-refresh.v4.json"
    prior = tmp_path / "e0-3-bot-b5-3-064a-decision-candidate.v3.json"
    deferral = tmp_path / "e0-3-bot-b5-3-064a-owner-deferral.v3.json"
    for original, copied in (
        (ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json", decision),
        (ROOT / "docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json", source),
        (ROOT / "docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json", prior),
        (ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json", deferral),
    ):
        shutil.copyfile(original, copied); os.chmod(copied, 0o600)
    statement = tmp_path / "v4-statement.json"
    result, receipt = run(["create-statement", "--decision-input", decision,
        "--source-observation", source, "--prior-state", prior,
        "--active-deferral", deferral, "--keyring", keyring,
        "--issued-at", 1787369400, "--expires-at", 1787373000,
        "--nonce", "AQEBAQEBAQEBAQEBAQEBAQ", "--out", statement])
    assert result.returncode == 0
    assert receipt["productionAuthority"] is False
    frozen = json.loads(statement.read_text())
    assert frozen["schemaVersion"] == "b64-064a-decision-statement.v2"
    assert frozen["sourceObservedAtEpoch"] == 1787369106
    assert frozen["sourceExpiresAtEpoch"] == 1787455506
    review = tmp_path / "v4-review-envelope.json"
    result, receipt = run(["sign-reviewer", "--statement", statement,
        "--keyring", keyring, "--private-key", review_key,
        "--nonce", "AgICAgICAgICAgICAgICAg", "--out", review], True)
    assert result.returncode == 0 and receipt["productionAuthority"] is False
    owner = tmp_path / "v4-owner-envelope.json"
    result, receipt = run(["sign-owner", "--statement", statement,
        "--keyring", keyring, "--private-key", owner_key,
        "--reviewer", review, "--nonce", "AwMDAwMDAwMDAwMDAwMDAw",
        "--out", owner], True)
    assert result.returncode == 0 and receipt["productionAuthority"] is False
    result, receipt = run(["verify", "--decision-input", decision,
        "--source-observation", source, "--prior-state", prior,
        "--active-deferral", deferral, "--statement", statement,
        "--reviewer", review, "--owner", owner, "--keyring", keyring,
        "--now", 1787369401])
    assert result.returncode == 0
    assert receipt["status"] == "SYNTHETIC_VALID"
    assert receipt["syntheticProtocolValid"] is True
    assert receipt["replayProtectionVerified"] is False
    for field in ("authenticatedOwnerReviewerGo", "boundedEvidenceAccepted",
                  "productionExpandAuthorized", "cutoverAuthorized",
                  "actionAllowed", "productionAuthority"):
        assert receipt[field] is False


def test_no_network_or_secret_ingress_surface():
    source = CLI.read_text()
    for forbidden in ("socket", "requests", "httpx", "subprocess", "os.environ", "private-seed"):
        assert forbidden not in source
    assert 'add_argument("--passphrase")' not in source
    assert "traceback" not in source
