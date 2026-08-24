import copy
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/support"
sys.path.insert(0, str(SUPPORT))

from e5_android_webauthn_preauth import (  # noqa: E402
    MAX_LIFETIME_MS,
    PreAuthSessionError,
    consume_for_test_only,
    create_preauth_session,
    create_role_links,
    validate_preauth_session,
    validate_role_pair,
)


NOW = 1_800_000_000_000
CONTEXT = {
    "decision_result_sha256": "a" * 64,
    "handoff_sha256": "b" * 64,
    "scorecard_sha256": "c" * 64,
}


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _session(role: str, identity: str, trust_domain: str, nonce_label: str):
    return create_preauth_session(
        role=role,
        human_identity_id=identity,
        trust_domain_id=trust_domain,
        context=CONTEXT,
        rp_id="review.invalid",
        origin="https://review.invalid",
        issued_at_epoch_ms=NOW,
        expires_at_epoch_ms=NOW + 60_000,
        caller_nonce_sha256=_nonce(nonce_label),
    )


def test_two_role_links_are_distinct_and_bound_to_the_same_context():
    reviewer = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    owner = _session("owner", "human-owner-b", "domain-owner-b", "owner")

    assert reviewer["link"] != owner["link"]
    assert "/reviewer/" in reviewer["link"]
    assert "/owner/" in owner["link"]
    assert reviewer["context"] == owner["context"] == CONTEXT
    result = validate_role_pair(reviewer, owner, expected_context=CONTEXT, now_epoch_ms=NOW + 1)
    assert result["preAuthPairStructurallyValid"] is True
    assert result["authenticated"] is False
    assert result["selectionAllowed"] is False


def test_single_helper_issues_both_inert_role_links():
    links = create_role_links(
        context=CONTEXT,
        rp_id="review.invalid",
        origin="https://review.invalid",
        issued_at_epoch_ms=NOW,
        expires_at_epoch_ms=NOW + 60_000,
        reviewer_identity_id="human-reviewer-a",
        reviewer_trust_domain_id="domain-review-a",
        reviewer_caller_nonce_sha256=_nonce("reviewer"),
        owner_identity_id="human-owner-b",
        owner_trust_domain_id="domain-owner-b",
        owner_caller_nonce_sha256=_nonce("owner"),
    )
    assert links["schema"] == "native-wallet-e5-android-webauthn-role-links.v1"
    assert links["reviewer"]["role"] == "reviewer"
    assert links["owner"]["role"] == "owner"
    assert links["pairValidation"]["authenticated"] is False


def test_session_has_exact_challenge_and_android_policy_shape():
    value = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    assert len(value["challengeB64Url"]) == 43
    assert value["webauthn"] == {
        "profile": "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV",
        "clientDataType": "webauthn.get",
        "backupEligible": False,
        "backupState": False,
        "userPresentRequired": True,
        "userVerifiedRequired": True,
        "requiredAuthenticatorFlagsByte": 0x05,
        "exactRpIdRequired": True,
        "exactOriginRequired": True,
    }
    assert value["preAuth"]["cryptographicVerificationImplemented"] is False
    assert value["preAuth"]["runtimeIntegrationAllowed"] is False


def test_validator_rejects_context_role_and_link_tampering():
    value = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    for changes, expected_role, context in [
        ({"role": "owner"}, None, CONTEXT),
        ({"link": "https://review.invalid/e5/webauthn/reviewer/tampered"}, None, CONTEXT),
        ({}, "owner", CONTEXT),
        ({}, None, {**CONTEXT, "scorecard_sha256": "d" * 64}),
    ]:
        changed = copy.deepcopy(value)
        changed.update(changes)
        try:
            validate_preauth_session(
                changed, expected_context=context, expected_role=expected_role,
                now_epoch_ms=NOW + 1,
            )
        except PreAuthSessionError:
            pass
        else:
            raise AssertionError("tampered pre-auth session was accepted")


def test_validator_rejects_expired_future_and_overlong_sessions():
    value = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    for now in [NOW + 60_000, NOW - 1_001]:
        try:
            validate_preauth_session(value, expected_context=CONTEXT, now_epoch_ms=now)
        except PreAuthSessionError:
            pass
        else:
            raise AssertionError("invalid time window was accepted")
    try:
        _ = create_preauth_session(
            role="reviewer", human_identity_id="human-reviewer-a",
            trust_domain_id="domain-review-a", context=CONTEXT,
            rp_id="review.invalid", origin="https://review.invalid",
            issued_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + MAX_LIFETIME_MS + 1,
            caller_nonce_sha256=_nonce("long"),
        )
    except PreAuthSessionError:
        pass
    else:
        raise AssertionError("overlong session was accepted")


def test_replay_guard_is_single_use_for_session_and_nonce():
    value = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    consumed_sessions = set()
    consumed_nonces = set()
    consume_for_test_only(
        value, expected_context=CONTEXT, now_epoch_ms=NOW + 1,
        consumed_session_ids=consumed_sessions, consumed_nonces=consumed_nonces,
    )
    try:
        consume_for_test_only(
            value, expected_context=CONTEXT, now_epoch_ms=NOW + 2,
            consumed_session_ids=consumed_sessions, consumed_nonces=consumed_nonces,
        )
    except PreAuthSessionError:
        pass
    else:
        raise AssertionError("replayed pre-auth session was accepted")


def test_pair_rejects_shared_human_or_trust_domain():
    reviewer = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    for owner in [
        _session("owner", "human-reviewer-a", "domain-owner-b", "owner-1"),
        _session("owner", "human-owner-b", "domain-review-a", "owner-2"),
    ]:
        try:
            validate_role_pair(reviewer, owner, expected_context=CONTEXT, now_epoch_ms=NOW + 1)
        except PreAuthSessionError:
            pass
        else:
            raise AssertionError("non-independent role pair was accepted")


def test_pair_rejects_shared_nonce_or_rp_origin():
    reviewer = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    shared_nonce_owner = _session("owner", "human-owner-b", "domain-owner-b", "reviewer")
    try:
        validate_role_pair(reviewer, shared_nonce_owner, expected_context=CONTEXT, now_epoch_ms=NOW + 1)
    except PreAuthSessionError:
        pass
    else:
        raise AssertionError("shared role nonce was accepted")

    owner_other_rp = create_preauth_session(
        role="owner", human_identity_id="human-owner-b", trust_domain_id="domain-owner-b",
        context=CONTEXT, rp_id="other.invalid", origin="https://other.invalid",
        issued_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 60_000,
        caller_nonce_sha256=_nonce("owner-other-rp"),
    )
    try:
        validate_role_pair(reviewer, owner_other_rp, expected_context=CONTEXT, now_epoch_ms=NOW + 1)
    except PreAuthSessionError:
        pass
    else:
        raise AssertionError("different RP/origin pair was accepted")


def test_no_pre_auth_result_can_grant_selection_or_crypto_authority():
    reviewer = _session("reviewer", "human-reviewer-a", "domain-review-a", "reviewer")
    result = validate_preauth_session(reviewer, expected_context=CONTEXT, now_epoch_ms=NOW + 1)
    assert result == {
        "schema": "native-wallet-e5-android-webauthn-preauth-validation.v1",
        "sessionId": reviewer["sessionId"],
        "role": "reviewer",
        "preAuthStructurallyValid": True,
        "cryptographicVerificationImplemented": False,
        "authenticated": False,
        "selectionAllowed": False,
        "cryptoCallAllowed": False,
        "runtimeIntegrationAllowed": False,
    }
