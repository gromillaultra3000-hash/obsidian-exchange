import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_key_boundary import build_key_boundary
from core.e5_recovery_attempt import (
    approve_recovery_attempt, evaluate_recovery_attempt, open_recovery_attempt,
)
from core.e5_recovery_completion import (
    build_completion_evidence, build_recovery_completion_proposal,
    validate_recovery_completion_proposal,
)
from core.e5_recovery_policy import build_recovery_policy

NOW = 1_800_000_000_000
DAY = 24 * 60 * 60 * 1000


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def context(eligible=True):
    boundary = build_key_boundary(design_id="native_wallet_foundation")
    policy = build_recovery_policy(
        boundary=boundary, policy_id="dual_path_recovery",
        guardian_trust_domains=["trusted_device", "family_guardian", "offline_guardian"])
    attempt = open_recovery_attempt(
        policy=policy, boundary=boundary, attempt_nonce_sha256=digest("attempt-1"),
        wallet_identity_sha256=digest("wallet-1"),
        active_device_identity_sha256=digest("active-device"),
        target_device_identity_sha256=digest("new-device"),
        target_device_attestation_sha256=digest("synthetic-attestation"),
        current_recovery_epoch=4, proposed_recovery_epoch=5,
        created_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 3 * DAY)
    if eligible:
        for guardian in ("trusted_device", "family_guardian"):
            attempt = approve_recovery_attempt(
                attempt, policy=policy, boundary=boundary,
                guardian_trust_domain=guardian,
                approval_evidence_sha256=digest(guardian),
                occurred_at_epoch_ms=NOW + 1_000)
        attempt = evaluate_recovery_attempt(
            attempt, policy=policy, boundary=boundary,
            observed_at_epoch_ms=NOW + DAY)
    return boundary, policy, attempt


def evidence(attempt, kind, verifier, when=NOW + DAY + 1_000):
    subject = (attempt["targetDeviceIdentitySha256"]
               if kind == "NEW_DEVICE_VERIFIED"
               else attempt["activeDeviceIdentitySha256"])
    return build_completion_evidence(
        evidence_kind=kind, attempt=attempt, subject_identity_sha256=subject,
        verifier_identity_sha256=digest(verifier), verified_at_epoch_ms=when)


def proposal():
    boundary, policy, attempt = context()
    value = build_recovery_completion_proposal(
        attempt=attempt, policy=policy, boundary=boundary,
        new_device_evidence=evidence(attempt, "NEW_DEVICE_VERIFIED", "verifier-a"),
        revocation_evidence=evidence(
            attempt, "PRIOR_DEVICE_REVOCATION_VERIFIED", "verifier-b"),
        observed_at_epoch_ms=NOW + DAY + 2_000)
    return boundary, policy, attempt, value


def test_eligible_attempt_and_independent_evidence_are_review_only():
    boundary, policy, attempt, value = proposal()
    assert value["status"] == "COMPLETION_REVIEW_READY_OFFLINE"
    assert value["recoveryExecuted"] is False
    assert value["newAuthorityInstalled"] is False
    assert value["priorDeviceRevoked"] is False
    assert value["signingAllowed"] is False
    assert value["productionRecoveryAllowed"] is False
    assert value["executionEffect"] == "NONE"
    assert value["actionAllowed"] is False
    assert validate_recovery_completion_proposal(
        value, attempt=attempt, policy=policy, boundary=boundary) == value


def test_pending_attempt_cannot_create_completion_proposal():
    boundary, policy, attempt = context(eligible=False)
    with pytest.raises(ValueError, match="not eligible"):
        build_recovery_completion_proposal(
            attempt=attempt, policy=policy, boundary=boundary,
            new_device_evidence=evidence(attempt, "NEW_DEVICE_VERIFIED", "verifier-a"),
            revocation_evidence=evidence(
                attempt, "PRIOR_DEVICE_REVOCATION_VERIFIED", "verifier-b"),
            observed_at_epoch_ms=NOW + DAY + 2_000)


def test_evidence_must_bind_exact_devices_attempt_epoch_and_hash():
    boundary, policy, attempt = context()
    device = evidence(attempt, "NEW_DEVICE_VERIFIED", "verifier-a")
    revocation = evidence(attempt, "PRIOR_DEVICE_REVOCATION_VERIFIED", "verifier-b")
    for field, replacement in (
        ("attemptId", "nwra_" + digest("other")),
        ("proposedRecoveryEpoch", 6),
        ("subjectIdentitySha256", digest("attacker")),
        ("evidenceSha256", digest("tamper")),
    ):
        changed = copy.deepcopy(device)
        changed[field] = replacement
        with pytest.raises(ValueError):
            build_recovery_completion_proposal(
                attempt=attempt, policy=policy, boundary=boundary,
                new_device_evidence=changed, revocation_evidence=revocation,
                observed_at_epoch_ms=NOW + DAY + 2_000)


def test_stale_future_or_same_verifier_evidence_fails_closed():
    boundary, policy, attempt = context()
    for when in (NOW + DAY - 10 * 60 * 1000, NOW + DAY + 4_000):
        with pytest.raises(ValueError, match="fresh"):
            build_recovery_completion_proposal(
                attempt=attempt, policy=policy, boundary=boundary,
                new_device_evidence=evidence(
                    attempt, "NEW_DEVICE_VERIFIED", "verifier-a", when),
                revocation_evidence=evidence(
                    attempt, "PRIOR_DEVICE_REVOCATION_VERIFIED", "verifier-b"),
                observed_at_epoch_ms=NOW + DAY + 2_000)
    with pytest.raises(ValueError, match="independent"):
        build_recovery_completion_proposal(
            attempt=attempt, policy=policy, boundary=boundary,
            new_device_evidence=evidence(attempt, "NEW_DEVICE_VERIFIED", "same"),
            revocation_evidence=evidence(
                attempt, "PRIOR_DEVICE_REVOCATION_VERIFIED", "same"),
            observed_at_epoch_ms=NOW + DAY + 2_000)


@pytest.mark.parametrize("field,replacement", [
    ("status", "RECOVERED"), ("recoveryExecuted", True),
    ("newAuthorityInstalled", True), ("priorDeviceRevoked", True),
    ("signingAllowed", True), ("productionRecoveryAllowed", True),
    ("executionEffect", "INSTALL_AUTHORITY"), ("actionAllowed", True),
])
def test_capability_tamper_fails(field, replacement):
    boundary, policy, attempt, value = proposal()
    value[field] = replacement
    with pytest.raises(ValueError):
        validate_recovery_completion_proposal(
            value, attempt=attempt, policy=policy, boundary=boundary)


def test_contract_has_no_secret_sdk_storage_network_or_execution_surface():
    source = (ROOT / "relay/core/e5_recovery_completion.py").read_text().lower()
    for forbidden in (
        "sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
        "os.environ", "subprocess", "mnemonic", "eth_account", "bitcoinlib",
        "sign_transaction", "private_key", "seed_phrase", "shamir",
        "keychain", "keystore", "android", "ios", "cloudkit",
    ):
        assert forbidden not in source
