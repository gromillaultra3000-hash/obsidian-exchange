import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_authenticator_evidence import (
    build_authenticator_evidence, validate_authenticator_evidence,
)
from core.e5_key_boundary import build_key_boundary
from core.e5_signing_consent import (
    build_signing_consent_receipt, build_signing_display_request,
)

NOW = 1_800_000_000_000
DESTINATION = "tst1acdefghjklmnpqrstuvwxyz23456789"


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def chain():
    boundary = build_key_boundary(design_id="native_wallet_foundation")
    request = build_signing_display_request(
        boundary=boundary, request_nonce="display_1",
        unsigned_payload_sha256=digest("synthetic unsigned tx"),
        destination=DESTINATION, amount="12.5", fee="0.01",
        created_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 60_000)
    consent = build_signing_consent_receipt(
        request=request, boundary=boundary, first_interaction_id="open_1",
        confirm_interaction_id="confirm_1", displayed_at_epoch_ms=NOW + 100,
        confirmed_at_epoch_ms=NOW + 850)
    return boundary, request, consent


def evidence(**changes):
    boundary, request, consent = chain()
    values = dict(
        request=request, consent=consent, boundary=boundary,
        first_interaction_id="open_1", confirm_interaction_id="confirm_1",
        device_key_identity_sha256=digest("hardware device public key"),
        challenge_sha256=digest("request-bound challenge"),
        assertion_sha256=digest("synthetic authenticator assertion"),
        assertion_counter=8, previous_assertion_counter=7,
        asserted_at_epoch_ms=NOW + 1_000, observed_at_epoch_ms=NOW + 1_010,
    )
    values.update(changes)
    return build_authenticator_evidence(**values)


def validation_context(**changes):
    boundary, request, consent = chain()
    values = dict(
        request=request, consent=consent, boundary=boundary,
        first_interaction_id="open_1", confirm_interaction_id="confirm_1",
        consumed_assertion_ids=())
    values.update(changes)
    return values


def test_evidence_binds_exact_consent_request_device_and_assertion():
    value = evidence()
    _, request, consent = chain()
    assert value["requestId"] == request["requestId"]
    assert value["consentReceiptId"] == consent["receiptId"]
    assert value["hardwareBackedClaim"] is True
    assert value["userVerificationClaim"] is True
    assert validate_authenticator_evidence(
        value, **validation_context()) == value


@pytest.mark.parametrize("changes", [
    {"assertion_counter": 7}, {"assertion_counter": 6},
    {"asserted_at_epoch_ms": NOW + 849},
    {"asserted_at_epoch_ms": NOW + 60_001},
    {"asserted_at_epoch_ms": NOW + 2_100, "observed_at_epoch_ms": NOW + 1_000},
    {"asserted_at_epoch_ms": NOW + 1_000, "observed_at_epoch_ms": NOW + 31_001},
])
def test_counter_window_and_freshness_fail_closed(changes):
    with pytest.raises(ValueError):
        evidence(**changes)


def test_exact_assertion_replay_is_rejected_by_consumed_evidence_id():
    value = evidence()
    with pytest.raises(ValueError, match="replay"):
        validate_authenticator_evidence(
            value, **validation_context(consumed_assertion_ids=[value["evidenceId"]]))


@pytest.mark.parametrize("field,replacement", [
    ("deviceKeyIdentitySha256", "0" * 64),
    ("challengeSha256", "1" * 64),
    ("assertionSha256", "2" * 64),
    ("hardwareBackedClaim", False),
    ("userVerificationClaim", False),
    ("platformAttestationVerified", True),
    ("localAuthenticatorVerified", True),
    ("signaturePresent", True),
    ("signingAllowed", True),
    ("actionAllowed", True),
])
def test_identity_assertion_or_capability_tamper_fails(field, replacement):
    changed = copy.deepcopy(evidence())
    changed[field] = replacement
    with pytest.raises(ValueError):
        validate_authenticator_evidence(changed, **validation_context())


def test_consent_or_device_binding_drift_fails():
    value = evidence()
    boundary, request, consent = chain()
    changed_request = build_signing_display_request(
        boundary=boundary, request_nonce="display_2",
        unsigned_payload_sha256=digest("synthetic unsigned tx"),
        destination=DESTINATION, amount="12.5", fee="0.01",
        created_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 60_000)
    with pytest.raises(ValueError):
        validate_authenticator_evidence(
            value, request=changed_request, consent=consent, boundary=boundary,
            first_interaction_id="open_1", confirm_interaction_id="confirm_1",
            consumed_assertion_ids=())


def test_contract_has_no_sdk_key_storage_network_or_signing_surface():
    source = (ROOT / "relay/core/e5_authenticator_evidence.py").read_text()
    for forbidden in (
        "sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
        "os.environ", "subprocess", "mnemonic", "eth_account", "bitcoinlib",
        "send_crypto", "sign_transaction", "private_key", "seed_phrase",
        "biometric_template", "android", "ios", "keychain", "keystore",
    ):
        assert forbidden not in source.lower()
