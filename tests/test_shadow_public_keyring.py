import copy
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "lumi") not in sys.path:
    sys.path.insert(0, str(ROOT / "lumi"))

from lumi.app.integration.shadow_public_keyring import (
    initial_keyring, load_keyring, resolve_public_key, revoke_key,
    rotate_keyring, validate_keyring,
)
from lumi.app.integration.shadow_service_identity import build_envelope, verify_envelope

NOW = 1786424405
OLD_ID = "kairos-shadow-v1"
NEW_ID = "kairos-shadow-v2"
OLD_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
NEW_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
OLD_PUBLIC = OLD_PRIVATE.public_key().public_bytes_raw()
NEW_PUBLIC = NEW_PRIVATE.public_key().public_bytes_raw()


def initial():
    return initial_keyring(
        key_id=OLD_ID, public_key=OLD_PUBLIC, activated_at=NOW - 100,
        valid_until=NOW + 86400)


def rotated(overlap=60):
    return rotate_keyring(
        initial(), new_key_id=NEW_ID, new_public_key=NEW_PUBLIC,
        rotated_at=NOW, valid_until=NOW + 86400, overlap_seconds=overlap)


def test_frozen_rotation_is_exact_and_input_is_immutable():
    source = initial()
    before = copy.deepcopy(source)
    expected = json.loads(
        (ROOT / "contracts/e2-shadow/public-keyring-rotation.v1.json").read_text())
    assert rotated() == expected
    assert source == before


def test_overlap_accepts_old_and_new_then_old_expires():
    value = rotated()
    assert resolve_public_key(value, key_id=OLD_ID, at_epoch=NOW + 60) == OLD_PUBLIC
    assert resolve_public_key(value, key_id=NEW_ID, at_epoch=NOW + 60) == NEW_PUBLIC
    with pytest.raises(ValueError, match="not active"):
        resolve_public_key(value, key_id=OLD_ID, at_epoch=NOW + 61)
    assert resolve_public_key(value, key_id=NEW_ID, at_epoch=NOW + 61) == NEW_PUBLIC


def test_revocation_is_immediate_and_can_fail_closed_with_no_active_key():
    value = revoke_key(rotated(), key_id=OLD_ID, revoked_at=NOW + 10)
    with pytest.raises(ValueError, match="not active"):
        resolve_public_key(value, key_id=OLD_ID, at_epoch=NOW + 10)
    assert resolve_public_key(value, key_id=NEW_ID, at_epoch=NOW + 10) == NEW_PUBLIC
    stopped = revoke_key(value, key_id=NEW_ID, revoked_at=NOW + 11)
    with pytest.raises(ValueError, match="not active"):
        resolve_public_key(stopped, key_id=NEW_ID, at_epoch=NOW + 11)
    assert not [item for item in stopped["keys"] if item["status"] == "ACTIVE"]


def test_identity_signature_verifier_resolves_only_allowlisted_key():
    payload = b'{"schemaVersion":"shadow-advisory-request.v1"}'
    envelope = build_envelope(
        payload, key_id=NEW_ID, issued_at=NOW + 1,
        nonce="AQIDBAUGBwgJCgsMDQ4PEBES", signer=NEW_PRIVATE.sign)
    value = rotated()

    def verifier(key_id, signature, canonical):
        raw = resolve_public_key(value, key_id=key_id, at_epoch=NOW + 1)
        Ed25519PublicKey.from_public_bytes(raw).verify(signature, canonical)

    result = verify_envelope(
        envelope, payload, now_epoch=NOW + 1, verify_signature=verifier,
        consume_nonce=lambda key, nonce, expires: None)
    assert result["verified"] is True and result["keyId"] == NEW_ID


@pytest.mark.parametrize(("overlap", "rotated_at", "valid_until"), [
    (-1, NOW, NOW + 100), (301, NOW, NOW + 100),
    (60, NOW - 101, NOW + 100), (60, NOW, NOW),
    (True, NOW, NOW + 100),
])
def test_invalid_rotation_fails_closed(overlap, rotated_at, valid_until):
    with pytest.raises(ValueError, match="rotation"):
        rotate_keyring(
            initial(), new_key_id=NEW_ID, new_public_key=NEW_PUBLIC,
            rotated_at=rotated_at, valid_until=valid_until,
            overlap_seconds=overlap)


@pytest.mark.parametrize("mutation", [
    lambda value: value.update({"keyringId": "kr_" + "0" * 64}),
    lambda value: value.update({"algorithm": "RSA"}),
    lambda value: value.update({"audience": "kairos"}),
    lambda value: value.update({"extra": True}),
    lambda value: value["keys"][0].update({"publicKey": "A" * 42}),
    lambda value: value["keys"][0].update({"status": "UNKNOWN"}),
    lambda value: value["keys"][0].update({"notAfter": True}),
    lambda value: value["keys"][0].update({"extra": True}),
])
def test_keyring_tamper_fails_closed(mutation):
    value = rotated()
    mutation(value)
    with pytest.raises(ValueError):
        validate_keyring(value)


def test_loader_accepts_readonly_public_file_and_rejects_unsafe_files(tmp_path):
    safe = tmp_path / "keyring.json"
    safe.write_text(json.dumps(rotated(), sort_keys=True, separators=(",", ":")))
    safe.chmod(0o644)
    assert load_keyring(safe) == rotated()

    safe.chmod(0o664)
    with pytest.raises(ValueError, match="invalid"):
        load_keyring(safe)
    safe.chmod(0o644)
    link = tmp_path / "link.json"
    link.symlink_to(safe)
    with pytest.raises(ValueError, match="invalid"):
        load_keyring(link)

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{")
    corrupt.chmod(0o644)
    with pytest.raises(ValueError, match="content"):
        load_keyring(corrupt)
