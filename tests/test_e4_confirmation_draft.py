import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_confirmation_draft import (
    build_confirmation_draft, validate_confirmation_draft,
)
from test_e4_action_acknowledgement import acknowledge, challenge
from test_e4_action_preview import NOW, preview


def flow(side="BUY_CRYPTO"):
    action = preview(side=side)
    gate = challenge(action)
    receipt = acknowledge(action, gate)
    destination = {
        "kind": "WALLET_ADDRESS" if side == "BUY_CRYPTO" else "BANK_ACCOUNT",
        "network": "bitcoin" if side == "BUY_CRYPTO" else None,
        "destinationFingerprintSha256": hashlib.sha256(b"destination").hexdigest(),
    }
    values = dict(preview=action, challenge=gate, acknowledgement_receipt=receipt,
                  idempotency_key="confirm_1", destination_summary=destination,
                  created_at_epoch_ms=receipt["acknowledgedAtEpochMs"] + 1)
    return values, build_confirmation_draft(**values)


@pytest.mark.parametrize("side", ["BUY_CRYPTO", "SELL_CRYPTO"])
def test_acknowledged_private_action_yields_only_unpersisted_nonexecuting_draft(side):
    values, draft = flow(side)
    assert draft["status"] == "DRAFT_ONLY"
    assert draft["persisted"] is False
    assert draft["serverAuthenticationSatisfied"] is False
    assert draft["serverStateChecksSatisfied"] is False
    assert draft["moneyIntentAllowed"] is False
    assert draft["actionAllowed"] is False
    assert "confirm_1" not in json.dumps(draft)
    assert validate_confirmation_draft(
        json.loads(json.dumps(draft)), idempotency_key="confirm_1",
        preview=values["preview"], challenge=values["challenge"],
        acknowledgement_receipt=values["acknowledgement_receipt"]) == draft


def test_exact_retry_is_stable_and_key_or_destination_drift_changes_identity():
    values, draft = flow()
    assert build_confirmation_draft(**values) == draft
    assert build_confirmation_draft(**{**values, "idempotency_key": "confirm_2"}) != draft
    changed_destination = {**values["destination_summary"],
                           "destinationFingerprintSha256": hashlib.sha256(b"other").hexdigest()}
    assert build_confirmation_draft(
        **{**values, "destination_summary": changed_destination}) != draft


def test_planned_lane_or_no_go_acknowledgement_cannot_create_draft():
    action = preview("verified_exchanges")
    gate = challenge(action)
    receipt = acknowledge(action, gate)
    with pytest.raises(ValueError):
        build_confirmation_draft(
            preview=action, challenge=gate, acknowledgement_receipt=receipt,
            idempotency_key="confirm_1",
            destination_summary={"kind": "WALLET_ADDRESS", "network": "bitcoin",
                                 "destinationFingerprintSha256": "0" * 64},
            created_at_epoch_ms=NOW + 1000)


def test_raw_destination_or_wrong_kind_network_and_expiry_fail_closed():
    values, _ = flow()
    for destination in (
        {**values["destination_summary"], "address": "raw"},
        {**values["destination_summary"], "kind": "BANK_ACCOUNT"},
        {**values["destination_summary"], "network": None},
    ):
        with pytest.raises(ValueError):
            build_confirmation_draft(**{**values, "destination_summary": destination})
    with pytest.raises(ValueError):
        build_confirmation_draft(**{
            **values, "created_at_epoch_ms": values["preview"]["quote"]["expiresAtEpochMs"] + 1})


@pytest.mark.parametrize("field", [
    "persisted", "serverAuthenticationSatisfied", "serverStateChecksSatisfied",
    "moneyIntentAllowed", "actionAllowed",
])
def test_draft_tamper_cannot_claim_server_state_or_money_action(field):
    values, draft = flow()
    changed = copy.deepcopy(draft)
    changed[field] = True
    with pytest.raises(ValueError):
        validate_confirmation_draft(
            changed, preview=values["preview"], challenge=values["challenge"],
            acknowledgement_receipt=values["acknowledgement_receipt"],
            idempotency_key=values["idempotency_key"])


def test_draft_contract_has_no_database_network_secret_or_execution_surface():
    source = (ROOT / "relay/core/e4_confirmation_draft.py").read_text()
    for forbidden in ("sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
                      "os.environ", "apiKey", "apiSecret", "privateKey", "send_crypto",
                      "subprocess", "time.time"):
        assert forbidden not in source
