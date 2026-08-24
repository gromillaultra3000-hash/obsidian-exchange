import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_key_boundary import build_key_boundary
from core.e5_recovery_attempt import approve_recovery_attempt, evaluate_recovery_attempt, open_recovery_attempt
from core.e5_recovery_completion import build_completion_evidence, build_recovery_completion_proposal
from core.e5_recovery_policy import build_recovery_policy
from core.e5_recovery_review import (
    MAX_AUTHORIZATION_MS, REQUIRED_CHECKS, build_completion_review,
    build_rehearsal_authorization, validate_completion_review,
    validate_rehearsal_authorization,
)

NOW = 1_800_000_000_000
DAY = 86_400_000


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def context():
    boundary = build_key_boundary(design_id="native_wallet_foundation")
    policy = build_recovery_policy(
        boundary=boundary, policy_id="dual_path_recovery",
        guardian_trust_domains=["trusted_device", "family_guardian", "offline_guardian"])
    attempt = open_recovery_attempt(
        policy=policy, boundary=boundary, attempt_nonce_sha256=digest("attempt"),
        wallet_identity_sha256=digest("wallet"),
        active_device_identity_sha256=digest("active-device"),
        target_device_identity_sha256=digest("target-device"),
        target_device_attestation_sha256=digest("attestation"),
        current_recovery_epoch=8, proposed_recovery_epoch=9,
        created_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 3 * DAY)
    for guardian in ("trusted_device", "family_guardian"):
        attempt = approve_recovery_attempt(
            attempt, policy=policy, boundary=boundary,
            guardian_trust_domain=guardian,
            approval_evidence_sha256=digest(guardian), occurred_at_epoch_ms=NOW + 1_000)
    attempt = evaluate_recovery_attempt(
        attempt, policy=policy, boundary=boundary, observed_at_epoch_ms=NOW + DAY)
    def evidence(kind, subject, verifier):
        return build_completion_evidence(
            evidence_kind=kind, attempt=attempt, subject_identity_sha256=subject,
            verifier_identity_sha256=digest(verifier),
            verified_at_epoch_ms=NOW + DAY + 1_000)
    proposal = build_recovery_completion_proposal(
        attempt=attempt, policy=policy, boundary=boundary,
        new_device_evidence=evidence(
            "NEW_DEVICE_VERIFIED", attempt["targetDeviceIdentitySha256"], "verifier-a"),
        revocation_evidence=evidence(
            "PRIOR_DEVICE_REVOCATION_VERIFIED", attempt["activeDeviceIdentitySha256"], "verifier-b"),
        observed_at_epoch_ms=NOW + DAY + 2_000)
    return boundary, policy, attempt, proposal


def review(**outcomes):
    boundary, policy, attempt, proposal = context()
    checks = {check: outcomes.get(check, "PASS") for check in REQUIRED_CHECKS}
    value = build_completion_review(
        proposal=proposal, attempt=attempt, policy=policy, boundary=boundary,
        reviewer_identity_sha256=digest("reviewer"),
        reviewed_at_epoch_ms=NOW + DAY + 3_000, check_outcomes=checks)
    return boundary, policy, attempt, proposal, value


def authorization(review_value=None, **changes):
    boundary, policy, attempt, proposal, default_review = review()
    args = dict(
        review=review_value or default_review, proposal=proposal, attempt=attempt,
        policy=policy, boundary=boundary, rehearsal_nonce_sha256=digest("nonce"),
        isolated_target_identity_sha256=digest("disposable-target"),
        mobile_build_sha256=digest("reproducible-build"),
        authorized_at_epoch_ms=NOW + DAY + 4_000,
        expires_at_epoch_ms=NOW + DAY + 4_000 + MAX_AUTHORIZATION_MS)
    args.update(changes)
    return (boundary, policy, attempt, proposal, args["review"],
            build_rehearsal_authorization(**args))


def test_all_checks_produce_review_ready_without_execution_permission():
    boundary, policy, attempt, proposal, value = review()
    assert value["status"] == "REHEARSAL_REVIEW_READY"
    assert value["isolatedRehearsalReviewReady"] is True
    assert value["blockers"] == []
    assert value["newAuthorityInstalled"] is False
    assert value["actionAllowed"] is False
    assert validate_completion_review(
        value, proposal=proposal, attempt=attempt, policy=policy,
        boundary=boundary) == value


@pytest.mark.parametrize("failed", REQUIRED_CHECKS)
def test_each_review_failure_is_explicit_no_go(failed):
    *_, value = review(**{failed: "FAIL"})
    assert value["status"] == "NO_GO"
    assert value["blockers"] == [failed]
    assert value["isolatedRehearsalReviewReady"] is False


def test_authorization_is_exact_short_lived_and_rehearsal_only():
    boundary, policy, attempt, proposal, review_value, value = authorization()
    assert value["scope"] == "ONE_ISOLATED_NON_PRODUCTION_MOBILE_RECOVERY_REHEARSAL"
    assert value["invocationLimit"] == 1
    assert value["isolatedRehearsalEligible"] is True
    for field in (
        "productionNetworkAllowed", "productionCredentialsAllowed",
        "productionWalletAllowed", "realKeyMaterialAllowed",
        "authorityInstallationAllowed", "priorDeviceRevocationAllowed",
        "broadcastAllowed", "automaticRetryAllowed", "recoveryExecuted",
        "signingAllowed", "actionAllowed",
    ):
        assert value[field] is False
    assert validate_rehearsal_authorization(
        value, review=review_value, proposal=proposal, attempt=attempt,
        policy=policy, boundary=boundary) == value


def test_no_go_stale_or_long_authorization_fails_closed():
    *_, no_go = review(NO_PRODUCTION_ROUTE="FAIL")
    with pytest.raises(ValueError, match="not ready"):
        authorization(review_value=no_go)
    with pytest.raises(ValueError, match="not current"):
        authorization(authorized_at_epoch_ms=NOW + DAY + 3_000 + 10 * 60 * 1000 + 1)
    with pytest.raises(ValueError, match="lifetime"):
        authorization(expires_at_epoch_ms=NOW + DAY + 4_000 + MAX_AUTHORIZATION_MS + 1)


def test_reviewer_must_be_independent_and_review_inside_attempt_lifetime():
    boundary, policy, attempt, proposal = context()
    checks = {check: "PASS" for check in REQUIRED_CHECKS}
    for reviewer in (
        attempt["activeDeviceIdentitySha256"],
        attempt["targetDeviceIdentitySha256"],
        proposal["newDeviceEvidence"]["verifierIdentitySha256"],
        proposal["revocationEvidence"]["verifierIdentitySha256"],
    ):
        with pytest.raises(ValueError, match="not independent"):
            build_completion_review(
                proposal=proposal, attempt=attempt, policy=policy, boundary=boundary,
                reviewer_identity_sha256=reviewer,
                reviewed_at_epoch_ms=NOW + DAY + 3_000, check_outcomes=checks)
    with pytest.raises(ValueError, match="lifetime"):
        build_completion_review(
            proposal=proposal, attempt=attempt, policy=policy, boundary=boundary,
            reviewer_identity_sha256=digest("reviewer"),
            reviewed_at_epoch_ms=NOW + 3 * DAY + 1, check_outcomes=checks)


def test_authorization_id_is_single_use_against_consumed_ledger_snapshot():
    boundary, policy, attempt, proposal, review_value, value = authorization()
    with pytest.raises(ValueError, match="already consumed"):
        validate_rehearsal_authorization(
            value, review=review_value, proposal=proposal, attempt=attempt,
            policy=policy, boundary=boundary,
            consumed_authorization_ids=[value["authorizationId"]])


def test_review_and_authorization_capability_tamper_fails():
    boundary, policy, attempt, proposal, review_value, value = authorization()
    for field, replacement in (
        ("invocationLimit", 2), ("productionNetworkAllowed", True),
        ("realKeyMaterialAllowed", True), ("authorityInstallationAllowed", True),
        ("priorDeviceRevocationAllowed", True), ("broadcastAllowed", True),
        ("executionEffect", "INSTALL_AUTHORITY"), ("actionAllowed", True),
    ):
        changed = copy.deepcopy(value); changed[field] = replacement
        with pytest.raises(ValueError):
            validate_rehearsal_authorization(
                changed, review=review_value, proposal=proposal, attempt=attempt,
                policy=policy, boundary=boundary)


def test_contract_has_no_runtime_storage_network_sdk_or_secret_surface():
    source = (ROOT / "relay/core/e5_recovery_review.py").read_text().lower()
    for forbidden in (
        "open(", "read_text", "read_bytes", "sqlite", "psycopg", "requests",
        "httpx", "aiohttp", "socket", "os.environ", "subprocess", "docker",
        "systemctl", "mnemonic", "private_key", "seed_phrase", "keychain",
        "keystore", "android", "ios", "sign_transaction",
    ):
        assert forbidden not in source
