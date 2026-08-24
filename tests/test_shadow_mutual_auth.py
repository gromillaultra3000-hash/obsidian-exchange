import copy
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

from app.shadow_mutual_auth import run_round_trip, validate_transcript
from lumi.app.integration.shadow_advisory import evaluate
from lumi.app.integration.shadow_service_identity import build_envelope, verify_envelope

REQUEST_ISSUED = 1786424405
RESPONSE_ISSUED = 1786424406
REQUEST_NONCE = "AQIDBAUGBwgJCgsMDQ4PEBES"
RESPONSE_NONCE = "AgMEBQYHCAkKCwwNDg8QERIT"
REQUEST_KEY = "kairos-shadow-test-v1"
RESPONSE_KEY = "lumi-shadow-test-v1"
REQUEST_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
RESPONSE_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(65, 97)))


def wire(name):
    value = json.loads((ROOT / f"contracts/e2-shadow/{name}").read_text())
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


class Guard:
    def __init__(self):
        self.seen = set()

    def consume(self, key_id, nonce, expires_at):
        identity = (key_id, nonce)
        if identity in self.seen:
            raise ValueError("replayed")
        self.seen.add(identity)


def setup_round_trip():
    body = wire("advisory-request.v1.json")
    envelope = build_envelope(
        body, key_id=REQUEST_KEY, issued_at=REQUEST_ISSUED,
        nonce=REQUEST_NONCE, signer=REQUEST_PRIVATE.sign)
    request_guard = Guard()
    response_guard = Guard()
    evaluations = []

    def verify_request(value, payload, now):
        return verify_envelope(
            value, payload, now_epoch=now,
            verify_signature=lambda key, signature, canonical:
                REQUEST_PRIVATE.public_key().verify(signature, canonical),
            consume_nonce=request_guard.consume)

    def evaluate_request(value):
        evaluations.append(value["requestId"])
        return evaluate(
            value, evaluated_at=datetime(2026, 8, 11, 4, 0, 2,
                                         tzinfo=timezone.utc))

    def run(**changes):
        arguments = {
            "request_now_epoch": REQUEST_ISSUED,
            "verify_request": verify_request,
            "evaluate_request": evaluate_request,
            "response_key_id": RESPONSE_KEY,
            "response_issued_at": RESPONSE_ISSUED,
            "response_nonce": RESPONSE_NONCE,
            "response_signer": RESPONSE_PRIVATE.sign,
            "response_verify_signature": lambda key, signature, canonical:
                RESPONSE_PRIVATE.public_key().verify(signature, canonical),
            "consume_response_nonce": response_guard.consume,
            "decided_at": datetime(2026, 8, 11, 4, 0, 3, tzinfo=timezone.utc),
        }
        arguments.update(changes)
        return run_round_trip(body, envelope, **arguments)

    return run, request_guard, response_guard, evaluations


def test_frozen_mutual_auth_transcript_is_exact_and_non_executing():
    run, request_guard, response_guard, evaluations = setup_round_trip()
    expected = json.loads((
        ROOT / "contracts/e2-shadow/mutual-auth-transcript.v1.json").read_text())
    result = run()
    assert result == expected
    assert validate_transcript(result) == result
    assert len(request_guard.seen) == len(response_guard.seen) == 1
    assert evaluations == [result["requestId"]]
    assert result["dispatch"]["combinedVerdict"] == "HOLD"
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False


def test_request_replay_stops_before_lumi_evaluation_and_response_signature():
    run, request_guard, response_guard, evaluations = setup_round_trip()
    run()
    with pytest.raises(ValueError, match="replayed"):
        run()
    assert len(request_guard.seen) == len(response_guard.seen) == 1
    assert len(evaluations) == 1


def test_response_replay_stops_before_dispatch():
    run, request_guard, response_guard, evaluations = setup_round_trip()
    run()
    request_guard.seen.clear()
    with pytest.raises(ValueError, match="replayed"):
        run()
    assert len(evaluations) == 2 and len(response_guard.seen) == 1


@pytest.mark.parametrize(("path", "value"), [
    (("requestHash",), "0" * 64),
    (("responseHash",), "0" * 64),
    (("requestId",), "ar_" + "0" * 64),
    (("requestVerification", "actionAllowed"), True),
    (("responseReceipt", "executionEffect"), "WRITE"),
    (("responseVerification", "requestHash"), "0" * 64),
    (("dispatch", "status"), "MALFORMED"),
    (("dispatch", "actionAllowed"), True),
    (("actionAllowed",), True),
    (("transcriptId",), "rt_" + "0" * 64),
])
def test_transcript_tamper_fails_closed(path, value):
    run, *_ = setup_round_trip()
    transcript = copy.deepcopy(run())
    target = transcript
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_transcript(transcript)


def test_request_signature_failure_stops_before_nonce_and_evaluation():
    run, request_guard, response_guard, evaluations = setup_round_trip()

    def reject(value, payload, now):
        raise ValueError("signature rejected")

    with pytest.raises(ValueError, match="signature rejected"):
        run(verify_request=reject)
    assert not request_guard.seen and not response_guard.seen and not evaluations


def test_response_signature_failure_does_not_consume_response_nonce():
    run, request_guard, response_guard, evaluations = setup_round_trip()

    def reject(key, signature, canonical):
        raise ValueError("signature rejected")

    with pytest.raises(ValueError, match="verification failed"):
        run(response_verify_signature=reject)
    assert len(request_guard.seen) == 1 and len(evaluations) == 1
    assert not response_guard.seen


def test_module_has_no_network_env_file_route_state_or_crypto_surface():
    source = inspect.getsource(sys.modules["app.shadow_mutual_auth"]).lower()
    assert all(term not in source for term in (
        "requests", "urllib", "http://", "https://", "socket", "os.getenv",
        "environ", "open(", "pathlib", "fastapi", "router", "cryptography",
        "write", "append("))
