import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
DSSE_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-dsse-witness-statement-v1.schema.json"
WEBAUTHN_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-webauthn-preflight-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _strict_client_data(raw: bytes, expected_challenge: bytes, expected_origin: str) -> bool:
    try:
        pairs = json.loads(raw.decode("utf-8"), object_pairs_hook=lambda values: values)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(pairs, list) or any(not isinstance(item, tuple) or len(item) != 2 for item in pairs):
        return False
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)) or not set(keys) <= {"type", "challenge", "origin", "crossOrigin"}:
        return False
    data = dict(pairs)
    expected_text = base64.urlsafe_b64encode(expected_challenge).decode("ascii").rstrip("=")
    return (
        set(data) >= {"type", "challenge", "origin"}
        and data["type"] == "webauthn.get"
        and data["challenge"] == expected_text
        and data["origin"] == expected_origin
        and data.get("crossOrigin", False) is False
    )


def _authenticator_preflight(raw: bytes, expected_rp_id: str) -> bool:
    if len(raw) != 37:
        return False
    expected_hash = hashlib.sha256(expected_rp_id.encode("utf-8")).digest()
    return raw[:32] == expected_hash and raw[32] == 0x05


def test_dsse_statement_is_closed_bounded_and_symbolic():
    schema = _load(DSSE_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["maximum_decoded_bytes"] == 8192
    assert schema["maximum_json_depth"] == 4
    assert schema["duplicate_fields_rejected"] is True
    assert schema["semantics_evaluated_only_after_symbolic_signature_success"] is True
    assert schema["signature_outcome_symbolic"] is True


def test_client_data_requires_exact_challenge_origin_type_and_no_unknowns():
    challenge = bytes(range(32))
    encoded = base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
    exact = json.dumps({"type": "webauthn.get", "challenge": encoded, "origin": "https://review.invalid", "crossOrigin": False}, separators=(",", ":")).encode()
    assert _strict_client_data(exact, challenge, "https://review.invalid")
    for old, new in [
        (b"webauthn.get", b"webauthn.create"),
        (encoded.encode(), b"AAAA"),
        (b"https://review.invalid", b"https://evil.invalid"),
        (b'"crossOrigin":false', b'"crossOrigin":true'),
    ]:
        assert not _strict_client_data(exact.replace(old, new), challenge, "https://review.invalid")
    unknown = exact[:-1] + b',"topOrigin":"https://review.invalid"}'
    assert not _strict_client_data(unknown, challenge, "https://review.invalid")


def test_duplicate_client_data_fields_fail():
    challenge = bytes(32)
    encoded = base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
    duplicate = f'{{"type":"webauthn.get","type":"webauthn.get","challenge":"{encoded}","origin":"https://review.invalid"}}'.encode()
    assert not _strict_client_data(duplicate, challenge, "https://review.invalid")


def test_authenticator_data_requires_exact_rp_hash_length_and_flags():
    rp_id = "review.invalid"
    exact = hashlib.sha256(rp_id.encode()).digest() + bytes([0x05]) + (7).to_bytes(4, "big")
    assert _authenticator_preflight(exact, rp_id)
    assert not _authenticator_preflight(exact, "evil.invalid")
    assert not _authenticator_preflight(exact[:-1], rp_id)
    for flags in [0x01, 0x04, 0x0D, 0x15, 0x45, 0x85, 0x07, 0x25]:
        changed = bytearray(exact)
        changed[32] = flags
        assert not _authenticator_preflight(bytes(changed), rp_id)


def test_sign_count_is_advisory_and_does_not_change_preflight():
    rp_id = "review.invalid"
    prefix = hashlib.sha256(rp_id.encode()).digest() + bytes([0x05])
    for count in [0, 1, 2**32 - 1]:
        assert _authenticator_preflight(prefix + count.to_bytes(4, "big"), rp_id)
    contract = _load(WEBAUTHN_PATH)
    assert contract["authenticator_data_model"]["sign_count_authoritative"] is False


def test_order_keeps_lookup_and_symbolic_signature_after_preflight():
    contract = _load(WEBAUTHN_PATH)
    order = contract["ordered_preflight"]
    assert order.index("external credential allowlist and revocation lookup") > order.index("exact flags byte 0x05")
    assert order.index("symbolic ES256 signature outcome") > order.index("external credential allowlist and revocation lookup")
    assert contract["signature_outcome_symbolic"] is True


def test_no_lookup_signature_or_authentication_is_implemented():
    dsse = _load(DSSE_PATH)
    webauthn = _load(WEBAUTHN_PATH)
    assert dsse["root_lookup_implemented"] is False
    assert dsse["signature_verification_implemented"] is False
    assert dsse["checkpoint_authenticated"] is False
    for field in ["credential_lookup_implemented", "revocation_lookup_implemented", "es256_signature_verification_implemented", "checkpoint_authenticated", "gate_i09_pass", "runtime_integration_allowed"]:
        assert webauthn[field] is False
