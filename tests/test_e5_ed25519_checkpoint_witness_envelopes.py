import base64
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
DSSE_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-dsse-witness-evidence-v1.schema.json"
WEBAUTHN_PATH = FIXTURES / "ed25519-corpus-review-checkpoint-webauthn-witness-evidence-v1.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_standard(value: str, limit: int) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("invalid standard Base64") from exc
    if len(decoded) > limit or base64.b64encode(decoded).decode("ascii") != value:
        raise ValueError("non-canonical or oversized standard Base64")
    return decoded


def _canonical_url(value: str, limit: int) -> bytes:
    if not value or "=" in value or any(char.isspace() for char in value):
        raise ValueError("canonical unpadded Base64URL required")
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("invalid Base64URL") from exc
    if len(decoded) > limit or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise ValueError("non-canonical or oversized Base64URL")
    return decoded


def test_dsse_envelope_is_closed_single_signature_and_bounded():
    schema = _load(DSSE_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["signature_count"] == 1
    assert schema["decoded_limits_bytes"] == {"payload": 8192, "signature": 1024, "complete_serialized_evidence": 16384}
    assert schema["keyid_selects_root"] is False


def test_standard_base64_requires_padding_canonicality_and_limits():
    exact = base64.b64encode(b"checkpoint statement").decode("ascii")
    assert _canonical_standard(exact, 64) == b"checkpoint statement"
    for invalid in [exact.rstrip("="), exact + " ", "Zh=="]:
        try:
            _canonical_standard(invalid, 64)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid Base64: {invalid!r}")
    oversized = base64.b64encode(b"x" * 65).decode("ascii")
    try:
        _canonical_standard(oversized, 64)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted oversized standard Base64")


def test_webauthn_envelope_is_closed_nullable_only_for_user_handle_and_bounded():
    schema = _load(WEBAUTHN_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    nullable = {name for name, rule in schema["properties"].items() if isinstance(rule.get("type"), list) and "null" in rule["type"]}
    assert nullable == {"user_handle_base64url"}
    assert schema["decoded_limits_bytes"]["client_data_json"] == 8192
    assert schema["decoded_limits_bytes"]["complete_serialized_evidence"] == 16384


def test_base64url_requires_no_padding_canonicality_and_limits():
    exact = base64.urlsafe_b64encode(b"assertion bytes").decode("ascii").rstrip("=")
    assert _canonical_url(exact, 64) == b"assertion bytes"
    for invalid in [exact + "=", exact + " ", "Zh"]:
        try:
            _canonical_url(invalid, 64)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid Base64URL: {invalid!r}")
    oversized = base64.urlsafe_b64encode(b"x" * 65).decode("ascii").rstrip("=")
    try:
        _canonical_url(oversized, 64)
    except ValueError:
        pass
    else:
        raise AssertionError("accepted oversized Base64URL")


def test_declared_digests_are_explicitly_untrusted_before_verification():
    dsse = _load(DSSE_PATH)
    webauthn = _load(WEBAUTHN_PATH)
    assert dsse["declared_digests_trusted_before_verified_payload_parse"] is False
    assert webauthn["declared_digests_trusted_before_assertion_verification"] is False


def test_envelopes_decode_or_authenticate_nothing():
    dsse = _load(DSSE_PATH)
    webauthn = _load(WEBAUTHN_PATH)
    for field in ["payload_decoding_implemented", "signature_decoding_implemented", "signature_verification_implemented", "real_evidence_present", "checkpoint_authenticated"]:
        assert dsse[field] is False
    for field in ["assertion_decoding_implemented", "credential_lookup_implemented", "signature_verification_implemented", "real_evidence_present", "checkpoint_authenticated"]:
        assert webauthn[field] is False
