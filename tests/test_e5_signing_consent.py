import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_key_boundary import build_key_boundary
from core.e5_signing_consent import (
    build_signing_consent_receipt, build_signing_display_request,
    validate_signing_consent_receipt, validate_signing_display_request,
)

NOW = 1_800_000_000_000
DESTINATION = "tst1acdefghjklmnpqrstuvwxyz23456789"


def boundary():
    return build_key_boundary(design_id="native_wallet_foundation")


def request(**changes):
    values = dict(
        boundary=boundary(), request_nonce="display_1",
        unsigned_payload_sha256=hashlib.sha256(b"synthetic unsigned tx").hexdigest(),
        destination=DESTINATION, amount="12.5", fee="0.01",
        created_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 60_000,
    )
    values.update(changes)
    return build_signing_display_request(**values)


def receipt(value=None, **changes):
    values = dict(
        request=value or request(), boundary=boundary(),
        first_interaction_id="open_1", confirm_interaction_id="confirm_1",
        displayed_at_epoch_ms=NOW + 100,
        confirmed_at_epoch_ms=NOW + 850,
    )
    values.update(changes)
    return build_signing_consent_receipt(**values)


def test_display_binds_payload_to_exact_human_visible_transaction_fields():
    value = request()
    assert value["display"] == {
        "network": "SYNTHETIC_TESTNET_V1", "asset": "TST",
        "destination": DESTINATION, "amount": "12.5", "fee": "0.01",
    }
    expected = hashlib.sha256(json.dumps({
        "unsignedPayloadSha256": value["unsignedPayloadSha256"],
        "display": value["display"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert value["displayBindingSha256"] == expected
    assert validate_signing_display_request(value, boundary=boundary()) == value


def test_consent_requires_distinct_deliberate_interaction_and_binds_request():
    signing_request = request()
    value = receipt(signing_request)
    assert value["requestId"] == signing_request["requestId"]
    assert value["displayBindingSha256"] == signing_request["displayBindingSha256"]
    assert value["status"] == "LOCAL_CONSENT_RECORDED_OFFLINE"
    assert validate_signing_consent_receipt(
        value, request=signing_request, boundary=boundary(),
        first_interaction_id="open_1", confirm_interaction_id="confirm_1") == value


@pytest.mark.parametrize("changes", [
    {"confirm_interaction_id": "open_1"},
    {"confirmed_at_epoch_ms": NOW + 849},
    {"confirmed_at_epoch_ms": NOW + 60_001},
    {"displayed_at_epoch_ms": NOW - 1},
])
def test_reused_fast_expired_or_precreated_confirmation_fails(changes):
    with pytest.raises(ValueError):
        receipt(**changes)


@pytest.mark.parametrize("changes", [
    {"amount": "01"}, {"fee": "NaN"}, {"destination": "real1address"},
    {"unsigned_payload_sha256": "A" * 64},
    {"expires_at_epoch_ms": NOW + 120_001},
])
def test_noncanonical_or_non_synthetic_request_fails(changes):
    with pytest.raises(ValueError):
        request(**changes)


@pytest.mark.parametrize("field,replacement", [
    ("signaturePresent", True), ("signingAllowed", True),
    ("productionNetworkAllowed", True), ("actionAllowed", True),
])
def test_tamper_cannot_turn_display_or_consent_into_signature_permission(field, replacement):
    for value, validator in (
        (request(), lambda item: validate_signing_display_request(item, boundary=boundary())),
        (receipt(), lambda item: validate_signing_consent_receipt(
            item, request=request(), boundary=boundary(),
            first_interaction_id="open_1", confirm_interaction_id="confirm_1")),
    ):
        changed = copy.deepcopy(value)
        changed[field] = replacement
        with pytest.raises(ValueError):
            validator(changed)


def test_payload_or_visible_field_drift_invalidates_consent_chain():
    original = request()
    value = receipt(original)
    changed = request(amount="12.6")
    with pytest.raises(ValueError):
        validate_signing_consent_receipt(
            value, request=changed, boundary=boundary(),
            first_interaction_id="open_1", confirm_interaction_id="confirm_1")


def test_contract_has_no_key_network_storage_or_signing_surface():
    source = (ROOT / "relay/core/e5_signing_consent.py").read_text()
    for forbidden in (
        "sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
        "os.environ", "subprocess", "mnemonic", "eth_account", "bitcoinlib",
        "send_crypto", "sign_transaction", "private_key", "seed_phrase",
    ):
        assert forbidden not in source.lower()
