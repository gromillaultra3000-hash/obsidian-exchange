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
    validate_recovery_attempt, veto_recovery_attempt,
)
from core.e5_recovery_policy import build_recovery_policy

NOW = 1_800_000_000_000
DAY = 24 * 60 * 60 * 1000


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def context():
    boundary = build_key_boundary(design_id="native_wallet_foundation")
    policy = build_recovery_policy(
        boundary=boundary, policy_id="dual_path_recovery",
        guardian_trust_domains=["trusted_device", "family_guardian", "offline_guardian"])
    return boundary, policy


def attempt(**changes):
    boundary, policy = context()
    values = dict(
        policy=policy, boundary=boundary, attempt_nonce_sha256=digest("attempt-1"),
        wallet_identity_sha256=digest("wallet-1"),
        active_device_identity_sha256=digest("active-device"),
        target_device_identity_sha256=digest("new-device"),
        target_device_attestation_sha256=digest("synthetic-attestation"),
        current_recovery_epoch=4, proposed_recovery_epoch=5,
        created_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 3 * DAY)
    values.update(changes)
    return open_recovery_attempt(**values)


def approve(value, guardian, evidence=None, when=NOW + 1_000):
    boundary, policy = context()
    return approve_recovery_attempt(
        value, policy=policy, boundary=boundary, guardian_trust_domain=guardian,
        approval_evidence_sha256=evidence or digest(guardian),
        occurred_at_epoch_ms=when)


def test_two_distinct_approvals_and_delay_produce_offline_eligibility_only():
    boundary, policy = context()
    value = approve(attempt(), "trusted_device")
    value = approve(value, "family_guardian")
    assert evaluate_recovery_attempt(
        value, policy=policy, boundary=boundary,
        observed_at_epoch_ms=NOW + DAY - 1) == value
    value = evaluate_recovery_attempt(
        value, policy=policy, boundary=boundary,
        observed_at_epoch_ms=NOW + DAY)
    assert value["status"] == "ELIGIBLE_OFFLINE"
    assert value["recoveryEligibleOffline"] is True
    assert value["recoveryExecuted"] is False
    assert value["newAuthorityInstalled"] is False
    assert value["priorDeviceRevoked"] is False
    assert value["actionAllowed"] is False
    assert validate_recovery_attempt(value, policy=policy, boundary=boundary) == value


def test_exact_approval_retry_is_idempotent_but_evidence_drift_fails():
    value = approve(attempt(), "trusted_device")
    assert approve(value, "trusted_device") == value
    with pytest.raises(ValueError, match="drift"):
        approve(value, "trusted_device", evidence=digest("different"))


def test_unknown_or_duplicate_guardian_cannot_satisfy_threshold():
    with pytest.raises(ValueError):
        approve(attempt(), "server")
    value = approve(attempt(), "trusted_device")
    with pytest.raises(ValueError):
        approve_recovery_attempt(
            value, policy=context()[1], boundary=context()[0],
            guardian_trust_domain="trusted_device",
            approval_evidence_sha256=digest("different"),
            occurred_at_epoch_ms=NOW + 2_000)


def test_active_device_veto_is_terminal_and_blocks_later_approval():
    boundary, policy = context()
    value = veto_recovery_attempt(
        approve(attempt(), "trusted_device"), policy=policy, boundary=boundary,
        veto_evidence_sha256=digest("active-veto"),
        occurred_at_epoch_ms=NOW + 2_000)
    assert value["status"] == "VETOED"
    with pytest.raises(ValueError, match="terminal"):
        approve(value, "family_guardian")
    assert evaluate_recovery_attempt(
        value, policy=policy, boundary=boundary,
        observed_at_epoch_ms=NOW + DAY) == value


def test_expiry_is_terminal_and_never_becomes_eligible():
    boundary, policy = context()
    value = approve(approve(attempt(), "trusted_device"), "family_guardian")
    value = evaluate_recovery_attempt(
        value, policy=policy, boundary=boundary,
        observed_at_epoch_ms=NOW + 3 * DAY)
    assert value["status"] == "EXPIRED"
    assert value["recoveryEligibleOffline"] is False


@pytest.mark.parametrize("changes", [
    {"proposed_recovery_epoch": 4}, {"proposed_recovery_epoch": 6},
    {"target_device_identity_sha256": digest("active-device")},
    {"expires_at_epoch_ms": NOW + DAY},
    {"expires_at_epoch_ms": NOW + 8 * DAY},
])
def test_epoch_device_and_lifetime_invariants_fail_closed(changes):
    with pytest.raises(ValueError):
        attempt(**changes)


@pytest.mark.parametrize("field,replacement", [
    ("status", "RECOVERED"), ("recoveryExecuted", True),
    ("newAuthorityInstalled", True), ("priorDeviceRevoked", True),
    ("containsSeed", True), ("containsRecoveryShare", True),
    ("serverCanRecover", True), ("productionRecoveryAllowed", True),
    ("actionAllowed", True),
])
def test_state_or_capability_tamper_fails(field, replacement):
    changed = copy.deepcopy(attempt())
    changed[field] = replacement
    boundary, policy = context()
    with pytest.raises(ValueError):
        validate_recovery_attempt(changed, policy=policy, boundary=boundary)


def test_event_or_target_tamper_fails_replay_validation():
    value = approve(attempt(), "trusted_device")
    value["events"][0]["targetDeviceIdentitySha256"] = digest("attacker-device")
    boundary, policy = context()
    with pytest.raises(ValueError):
        validate_recovery_attempt(value, policy=policy, boundary=boundary)


def test_contract_has_no_secret_crypto_sdk_storage_network_or_execution_surface():
    source = (ROOT / "relay/core/e5_recovery_attempt.py").read_text().lower()
    for forbidden in (
        "sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
        "os.environ", "subprocess", "mnemonic", "eth_account", "bitcoinlib",
        "sign_transaction", "private_key", "seed_phrase", "shamir",
        "keychain", "keystore", "android", "ios", "cloudkit",
    ):
        assert forbidden not in source
