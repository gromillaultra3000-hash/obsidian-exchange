import copy
import inspect
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "kairos", ROOT / "lumi", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.shadow_advisory_wire import AdvisoryRequest
from lumi.app.integration.shadow_advisory import evaluate
from lumi.app.integration.shadow_service_identity import (
    build_envelope, canonical_envelope, verify_envelope,
)

ISSUED = 1786424405
NONCE = "AQIDBAUGBwgJCgsMDQ4PEBES"
KEY_ID = "kairos-shadow-test-v1"
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC = PRIVATE.public_key()


def body():
    value = json.loads(
        (ROOT / "contracts/e2-shadow/advisory-request.v1.json").read_text())
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


class Guard:
    def __init__(self):
        self.seen = set()

    def consume(self, key_id, nonce, expires_at):
        key = (key_id, nonce)
        if key in self.seen:
            raise ValueError("replayed")
        assert expires_at == ISSUED + 30
        self.seen.add(key)


def verifier(key_id, signature, canonical):
    assert key_id == KEY_ID
    PUBLIC.verify(signature, canonical)


def make_envelope():
    return build_envelope(
        body(), key_id=KEY_ID, issued_at=ISSUED, nonce=NONCE,
        signer=PRIVATE.sign)


def test_frozen_envelope_and_verification_are_exact():
    envelope = json.loads(
        (ROOT / "contracts/e2-shadow/service-envelope.v1.json").read_text())
    expected = json.loads(
        (ROOT / "contracts/e2-shadow/service-verification.v1.json").read_text())
    assert make_envelope() == envelope
    assert verify_envelope(
        envelope, body(), now_epoch=ISSUED, verify_signature=verifier,
        consume_nonce=Guard().consume) == expected


def test_verified_body_is_still_independently_validated_by_lumi_adapter():
    guard = Guard()
    envelope = make_envelope()
    verification = verify_envelope(
        envelope, body(), now_epoch=ISSUED, verify_signature=verifier,
        consume_nonce=guard.consume)
    request = AdvisoryRequest.model_validate_json(body())
    response = evaluate(request.model_dump(mode="json"), evaluated_at=request.requestedAt)
    assert verification["requestHash"] == envelope["bodySha256"]
    assert response["requestId"] == request.requestId


def test_exact_replay_is_rejected_after_first_verified_consumption():
    guard = Guard()
    envelope = make_envelope()
    verify_envelope(
        envelope, body(), now_epoch=ISSUED, verify_signature=verifier,
        consume_nonce=guard.consume)
    with pytest.raises(ValueError, match="replayed"):
        verify_envelope(
            envelope, body(), now_epoch=ISSUED, verify_signature=verifier,
            consume_nonce=guard.consume)


@pytest.mark.parametrize(("field", "value"), [
    ("schemaVersion", "shadow-service-envelope.v2"), ("algorithm", "HMAC"),
    ("keyId", "bad key"), ("issuedAt", True), ("nonce", "short"),
    ("issuer", "relay"), ("audience", "kairos"), ("scope", "shadow:write"),
    ("method", "GET"), ("path", "/conflict/resolve"),
    ("contentType", "text/plain"), ("bodySha256", "0" * 64),
    ("signature", "A" * 85),
])
def test_envelope_field_tamper_fails_closed(field, value):
    envelope = make_envelope()
    envelope[field] = value
    guard = Guard()
    with pytest.raises(ValueError):
        verify_envelope(
            envelope, body(), now_epoch=ISSUED, verify_signature=verifier,
            consume_nonce=guard.consume)
    assert not guard.seen


def test_body_signature_clock_and_extra_field_tamper_do_not_consume_nonce():
    cases = []
    changed_signature = make_envelope()
    changed_signature["signature"] = "A" * 86
    cases.append((changed_signature, body(), ISSUED))
    cases.append((make_envelope(), body() + b" ", ISSUED))
    cases.append((make_envelope(), body(), ISSUED + 31))
    extra = make_envelope()
    extra["extra"] = True
    cases.append((extra, body(), ISSUED))
    for envelope, payload, now in cases:
        guard = Guard()
        with pytest.raises(ValueError):
            verify_envelope(
                envelope, payload, now_epoch=now, verify_signature=verifier,
                consume_nonce=guard.consume)
        assert not guard.seen


def test_canonical_fields_reject_newline_injection():
    envelope = make_envelope()
    envelope["keyId"] = "abc\nshadow"
    with pytest.raises(ValueError):
        canonical_envelope(envelope)


def test_identity_module_has_no_network_env_key_token_route_or_storage_surface():
    source = inspect.getsource(sys.modules[
        "lumi.app.integration.shadow_service_identity"]).lower()
    assert all(term not in source for term in (
        "requests", "urllib", "http://", "https://", "socket", "os.getenv",
        "environ", "open(", "pathlib", "token", "fastapi", "router", "model.invoke"))
