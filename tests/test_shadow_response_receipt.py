import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "kairos", ROOT / "lumi", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.shadow_response_receipt import build_receipt, canonical_receipt, verify_receipt
from app.shadow_advisory_wire import AdvisoryRequest, dispatch

ISSUED = 1786424406
NONCE = "AgMEBQYHCAkKCwwNDg8QERIT"
KEY_ID = "lumi-shadow-test-v1"
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(65, 97)))
PUBLIC = PRIVATE.public_key()


def wire(name):
    value = json.loads((ROOT / f"contracts/e2-shadow/{name}").read_text())
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def request_body():
    return wire("advisory-request.v1.json")


def response_body():
    return wire("advisory-response.v1.json")


class Guard:
    def __init__(self):
        self.seen = set()

    def consume(self, key_id, nonce, expires_at):
        identity = (key_id, nonce)
        if identity in self.seen:
            raise ValueError("response replayed")
        assert expires_at == ISSUED + 30
        self.seen.add(identity)


def verifier(key_id, signature, canonical):
    assert key_id == KEY_ID
    PUBLIC.verify(signature, canonical)


def make_receipt():
    return build_receipt(
        request_body(), response_body(), key_id=KEY_ID, issued_at=ISSUED,
        nonce=NONCE, signer=PRIVATE.sign)


def test_frozen_receipt_and_verification_are_exact():
    receipt = json.loads(
        (ROOT / "contracts/e2-shadow/response-receipt.v1.json").read_text())
    expected = json.loads((
        ROOT / "contracts/e2-shadow/response-receipt-verification.v1.json").read_text())
    assert make_receipt() == receipt
    assert verify_receipt(
        receipt, request_body(), response_body(), now_epoch=ISSUED,
        verify_signature=verifier, consume_nonce=Guard().consume) == expected


def test_exact_response_receipt_replay_is_rejected():
    guard = Guard()
    receipt = make_receipt()
    verify_receipt(
        receipt, request_body(), response_body(), now_epoch=ISSUED,
        verify_signature=verifier, consume_nonce=guard.consume)
    with pytest.raises(ValueError, match="replayed"):
        verify_receipt(
            receipt, request_body(), response_body(), now_epoch=ISSUED,
            verify_signature=verifier, consume_nonce=guard.consume)


def test_verified_receipt_response_dispatch_remains_non_executing():
    receipt = make_receipt()
    verification = verify_receipt(
        receipt, request_body(), response_body(), now_epoch=ISSUED,
        verify_signature=verifier, consume_nonce=Guard().consume)
    request = AdvisoryRequest.model_validate_json(request_body())
    response = json.loads(response_body())
    result = dispatch(
        request, transport=lambda payload, timeout: response,
        decided_at=datetime(2026, 8, 11, 4, 0, 3, tzinfo=timezone.utc))
    assert verification["requestId"] == result["requestId"]
    assert result["status"] == "OK" and result["combinedVerdict"] == "HOLD"
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False


@pytest.mark.parametrize(("field", "value"), [
    ("schemaVersion", "shadow-response-receipt.v2"), ("receiptId", "rr_" + "0" * 64),
    ("algorithm", "HMAC"), ("keyId", "bad key"), ("issuedAt", True),
    ("nonce", "short"), ("issuer", "kairos-shadow"), ("audience", "lumi-shadow"),
    ("scope", "shadow:advisory"), ("contentType", "text/plain"),
    ("requestId", "ar_" + "0" * 64), ("requestBodySha256", "0" * 64),
    ("responseBodySha256", "0" * 64), ("executionEffect", "WRITE"),
    ("actionAllowed", True), ("signature", "A" * 85),
])
def test_receipt_field_tamper_fails_without_nonce_consumption(field, value):
    receipt = make_receipt()
    receipt[field] = value
    guard = Guard()
    with pytest.raises(ValueError):
        verify_receipt(
            receipt, request_body(), response_body(), now_epoch=ISSUED,
            verify_signature=verifier, consume_nonce=guard.consume)
    assert not guard.seen


def test_request_response_signature_clock_and_extra_tamper_fail_before_consume():
    changed_signature = make_receipt()
    changed_signature["signature"] = "A" * 86
    extra = make_receipt()
    extra["extra"] = True
    cases = [
        (make_receipt(), request_body() + b" ", response_body(), ISSUED),
        (make_receipt(), request_body(), response_body() + b" ", ISSUED),
        (changed_signature, request_body(), response_body(), ISSUED),
        (make_receipt(), request_body(), response_body(), ISSUED + 31),
        (extra, request_body(), response_body(), ISSUED),
    ]
    for receipt, request, response, now in cases:
        guard = Guard()
        with pytest.raises(ValueError):
            verify_receipt(
                receipt, request, response, now_epoch=now,
                verify_signature=verifier, consume_nonce=guard.consume)
        assert not guard.seen


def test_receipt_canonicalization_rejects_newline_injection():
    receipt = make_receipt()
    receipt["keyId"] = "abc\nlumi"
    with pytest.raises(ValueError):
        canonical_receipt(receipt)


def test_receipt_module_has_no_network_env_key_file_route_or_state_surface():
    source = inspect.getsource(sys.modules["app.shadow_response_receipt"]).lower()
    assert all(term not in source for term in (
        "requests", "urllib", "http://", "https://", "socket", "os.getenv",
        "environ", "open(", "pathlib", "fastapi", "router", "write", "append("))
