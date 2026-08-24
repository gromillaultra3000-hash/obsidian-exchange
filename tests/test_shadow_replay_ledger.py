import copy
import inspect
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "lumi") not in sys.path:
    sys.path.insert(0, str(ROOT / "lumi"))

from lumi.app.integration.shadow_replay_ledger import (
    consume, empty_snapshot, replay_key, validate_snapshot,
)
from lumi.app.integration.shadow_service_identity import build_envelope, verify_envelope

NOW = 1786424405
KEY_ID = "kairos-shadow-test-v1"
NONCE_A = "AQIDBAUGBwgJCgsMDQ4PEBES"
NONCE_B = "AgMEBQYHCAkKCwwNDg8QERIT"
NONCE_C = "AwQFBgcICQoLDA0ODxAREhMU"


def transition(snapshot=None, nonce=NONCE_A, now=NOW, expires=NOW + 30):
    return consume(
        snapshot or empty_snapshot(capacity=2), key_id=KEY_ID, nonce=nonce,
        now_epoch=now, expires_at=expires)


def test_frozen_transition_is_exact_and_does_not_mutate_input():
    initial = empty_snapshot(capacity=2)
    before = copy.deepcopy(initial)
    expected = json.loads(
        (ROOT / "contracts/e2-shadow/replay-transition.v1.json").read_text())
    assert transition(initial) == expected
    assert initial == before


def test_json_snapshot_restart_preserves_replay_rejection():
    saved = json.loads(json.dumps(transition()["nextSnapshot"]))
    assert validate_snapshot(saved) == saved
    with pytest.raises(ValueError, match="replayed"):
        transition(saved)


def test_signed_envelope_uses_snapshot_transition_across_json_restart():
    payload = b'{"schemaVersion":"shadow-advisory-request.v1"}'
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public = private.public_key()
    envelope = build_envelope(
        payload, key_id=KEY_ID, issued_at=NOW, nonce=NONCE_A,
        signer=private.sign)
    holder = {"snapshot": empty_snapshot(capacity=2)}

    def ledger_consume(key_id, nonce, expires_at):
        result = consume(
            holder["snapshot"], key_id=key_id, nonce=nonce,
            now_epoch=NOW, expires_at=expires_at)
        holder["snapshot"] = result["nextSnapshot"]

    verify_envelope(
        envelope, payload, now_epoch=NOW,
        verify_signature=lambda key, signature, message: public.verify(signature, message),
        consume_nonce=ledger_consume)
    holder["snapshot"] = json.loads(json.dumps(holder["snapshot"]))
    with pytest.raises(ValueError, match="replayed"):
        verify_envelope(
            envelope, payload, now_epoch=NOW,
            verify_signature=lambda key, signature, message: public.verify(signature, message),
            consume_nonce=ledger_consume)


def test_expired_entries_are_pruned_and_nonce_can_be_reused_after_window():
    first = transition()["nextSnapshot"]
    result = transition(first, now=NOW + 31, expires=NOW + 61)
    assert result["prunedCount"] == 1
    assert result["previousCount"] == 1
    assert result["nextSnapshot"]["entryCount"] == 1


def test_capacity_is_fail_closed_until_an_entry_expires():
    first = transition()["nextSnapshot"]
    second = transition(first, nonce=NONCE_B)["nextSnapshot"]
    with pytest.raises(ValueError, match="capacity"):
        transition(second, nonce=NONCE_C)
    recovered = transition(
        second, nonce=NONCE_C, now=NOW + 31, expires=NOW + 61)
    assert recovered["prunedCount"] == 2
    assert recovered["nextSnapshot"]["entryCount"] == 1


def test_entry_order_is_deterministic_independent_of_consumption_order():
    left = transition(
        transition(nonce=NONCE_A)["nextSnapshot"], nonce=NONCE_B)["nextSnapshot"]
    right = transition(
        transition(nonce=NONCE_B)["nextSnapshot"], nonce=NONCE_A)["nextSnapshot"]
    assert left == right
    assert [entry["replayKey"] for entry in left["entries"]] == sorted(
        [replay_key(KEY_ID, NONCE_A), replay_key(KEY_ID, NONCE_B)])


@pytest.mark.parametrize("mutation", [
    lambda value: value.update({"schemaVersion": "shadow-replay-ledger.v2"}),
    lambda value: value.update({"capacity": 0}),
    lambda value: value.update({"entryCount": 2}),
    lambda value: value.update({"extra": True}),
    lambda value: value["entries"][0].update({"replayKey": "0" * 63}),
    lambda value: value["entries"][0].update({"expiresAt": True}),
    lambda value: value["entries"][0].update({"extra": True}),
])
def test_snapshot_tamper_fails_closed(mutation):
    value = transition()["nextSnapshot"]
    mutation(value)
    with pytest.raises(ValueError):
        validate_snapshot(value)


@pytest.mark.parametrize(("now", "expires"), [
    (True, NOW + 30), (NOW, True), (NOW, NOW - 1), (NOW, NOW + 61),
])
def test_invalid_expiry_fails_without_mutating_snapshot(now, expires):
    snapshot = empty_snapshot(capacity=2)
    before = copy.deepcopy(snapshot)
    with pytest.raises(ValueError, match="expiry"):
        transition(snapshot, now=now, expires=expires)
    assert snapshot == before


def test_snapshot_contains_hashes_not_key_ids_or_nonces():
    public = json.dumps(transition(), sort_keys=True)
    assert KEY_ID not in public and NONCE_A not in public


def test_replay_ledger_has_no_file_network_env_lock_or_runtime_surface():
    source = inspect.getsource(sys.modules[
        "lumi.app.integration.shadow_replay_ledger"]).lower()
    assert all(term not in source for term in (
        "open(", "pathlib", "os.", "environ", "requests", "urllib", "socket",
        "fcntl", "lock", "fastapi", "router", "http://", "https://"))
