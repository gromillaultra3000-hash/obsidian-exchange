import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_action_acknowledgement import (
    ACKNOWLEDGEMENTS, MIN_DELIBERATION_MS, acknowledge_action_preview,
    build_acknowledgement_challenge, validate_acknowledgement_challenge,
    validate_acknowledgement_receipt,
)
from test_e4_action_preview import NOW, preview


def challenge(action):
    return build_acknowledgement_challenge(
        preview=action, presentation_id="presentation_1", issued_at_epoch_ms=NOW + 1)


def acknowledge(action, gate, **changes):
    values = dict(preview=action, challenge=gate, interaction_id="interaction_2",
                  acknowledged=list(ACKNOWLEDGEMENTS),
                  acknowledged_at_epoch_ms=NOW + 1 + MIN_DELIBERATION_MS)
    values.update(changes)
    return acknowledge_action_preview(**values)


def test_private_preview_requires_all_five_acknowledgements_and_second_interaction():
    action = preview()
    gate = challenge(action)
    receipt = acknowledge(action, gate)
    assert gate["requiredAcknowledgements"] == list(ACKNOWLEDGEMENTS)
    assert gate["secondInteractionRequired"] is True
    assert receipt["status"] == "ACKNOWLEDGED"
    assert receipt["confirmationEligible"] is True
    assert receipt["moneyIntentAllowed"] is False
    assert receipt["actionAllowed"] is False
    assert validate_acknowledgement_challenge(
        json.loads(json.dumps(gate)), preview=action) == gate
    assert validate_acknowledgement_receipt(
        json.loads(json.dumps(receipt)), preview=action, challenge=gate) == receipt


def test_same_interaction_or_partial_reordered_acknowledgements_fail_closed():
    action, gate = preview(), None
    gate = challenge(action)
    with pytest.raises(ValueError):
        acknowledge(action, gate, interaction_id=gate["presentationId"])
    for acknowledgements in (list(ACKNOWLEDGEMENTS[:-1]), list(reversed(ACKNOWLEDGEMENTS))):
        with pytest.raises(ValueError):
            acknowledge(action, gate, acknowledged=acknowledgements)


def test_deliberation_and_expiry_are_explicit_no_go():
    action, gate = preview(), None
    gate = challenge(action)
    early = acknowledge(action, gate, acknowledged_at_epoch_ms=gate["issuedAtEpochMs"])
    late = acknowledge(action, gate,
                       acknowledged_at_epoch_ms=gate["expiresAtEpochMs"] + 1)
    assert early["blockers"] == ["DELIBERATION_TOO_SHORT"]
    assert late["blockers"] == ["CHALLENGE_OR_QUOTE_EXPIRED"]
    assert early["confirmationEligible"] is late["confirmationEligible"] is False


def test_planned_verified_exchange_lane_cannot_be_acknowledged_into_availability():
    action = preview("verified_exchanges")
    gate = challenge(action)
    receipt = acknowledge(action, gate)
    assert receipt["status"] == "NO_GO"
    assert receipt["blockers"] == ["LANE_NOT_AVAILABLE"]
    assert receipt["confirmationEligible"] is False


@pytest.mark.parametrize("field", ["confirmationEligible", "moneyIntentAllowed", "actionAllowed"])
def test_receipt_tamper_cannot_create_confirmation_intent_or_execution(field):
    action = preview()
    gate = challenge(action)
    receipt = acknowledge(action, gate)
    changed = copy.deepcopy(receipt)
    changed[field] = not changed[field]
    with pytest.raises(ValueError):
        validate_acknowledgement_receipt(changed, preview=action, challenge=gate)


def test_contract_has_no_database_network_secret_or_execution_surface():
    source = (ROOT / "relay/core/e4_action_acknowledgement.py").read_text()
    for forbidden in ("sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
                      "os.environ", "apiKey", "apiSecret", "privateKey", "send_crypto",
                      "subprocess", "time.time"):
        assert forbidden not in source
