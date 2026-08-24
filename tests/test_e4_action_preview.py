import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_action_preview import build_action_preview, validate_action_preview

NOW = 1_800_000_000_000


def preview(lane="private_exchange", side="BUY_CRYPTO", **changes):
    values = dict(lane=lane, side=side, quote_id="quote_1",
                  quoted_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + 60_000,
                  spend_asset="RUB" if side == "BUY_CRYPTO" else "BTC",
                  spend_amount="10000" if side == "BUY_CRYPTO" else "0.001",
                  receive_asset="BTC" if side == "BUY_CRYPTO" else "RUB",
                  receive_amount="0.001" if side == "BUY_CRYPTO" else "10000",
                  fee_items=[{"type": "SERVICE", "amount": "100", "asset": "RUB"}],
                  fee_asset="RUB")
    values.update(changes)
    return build_action_preview(**values)


@pytest.mark.parametrize("lane,side", [
    ("private_exchange", "BUY_CRYPTO"), ("private_exchange", "SELL_CRYPTO"),
    ("verified_exchanges", "BUY_CRYPTO"), ("verified_exchanges", "SELL_CRYPTO"),
])
def test_preview_exposes_executor_custody_identity_fees_risks_and_irreversibility(lane, side):
    value = preview(lane, side)
    assert value["executor"]["id"] in {"OBSIDIAN_EXCHANGE", "EXTERNAL_CEX"}
    assert set(value["custody"]) == {"before", "during", "after"}
    assert set(value["identity"]) == {"kycRequired", "performedBy"}
    assert value["fees"]["totalAmount"] == "100"
    assert value["risks"]
    assert value["irreversibleAfterExecution"] is True
    assert value["confirmationAvailable"] is False
    assert value["actionAllowed"] is False
    assert validate_action_preview(json.loads(json.dumps(value))) == value


def test_private_and_verified_lanes_never_blur_kyc_custody_or_availability():
    private = preview("private_exchange")
    verified = preview("verified_exchanges")
    assert private["identity"] == {"kycRequired": False, "performedBy": "NONE"}
    assert private["availability"] == "AVAILABLE"
    assert private["custody"]["after"] == "USER_DESTINATION_WALLET"
    assert verified["identity"] == {"kycRequired": True, "performedBy": "EXTERNAL_CEX"}
    assert verified["availability"] == "PLANNED"
    assert set(verified["custody"].values()) == {"EXTERNAL_CEX_ACCOUNT"}


def test_fee_total_is_derived_and_tamper_fails_closed():
    value = preview(fee_items=[
        {"type": "SERVICE", "amount": "100", "asset": "RUB"},
        {"type": "PROVIDER", "amount": "25.5", "asset": "RUB"},
    ])
    assert value["fees"]["totalAmount"] == "125.5"
    changed = copy.deepcopy(value)
    changed["fees"]["totalAmount"] = "0"
    with pytest.raises(ValueError):
        validate_action_preview(changed)


@pytest.mark.parametrize("changes", [
    {"spend_amount": "01"}, {"receive_amount": "NaN"},
    {"expires_at_epoch_ms": NOW + 15 * 60 * 1000 + 1},
    {"spend_asset": "BTC", "receive_asset": "ETH"},
    {"fee_items": [{"type": "HIDDEN", "amount": "1", "asset": "RUB"}]},
])
def test_malformed_amount_expiry_direction_or_hidden_fee_fails_closed(changes):
    with pytest.raises(ValueError):
        preview(**changes)


@pytest.mark.parametrize("field", [
    "confirmationAvailable", "actionAllowed",
])
def test_preview_tamper_cannot_become_confirmation_or_execution(field):
    value = preview()
    value[field] = True
    with pytest.raises(ValueError):
        validate_action_preview(value)


def test_preview_contract_has_no_database_network_secret_or_execution_surface():
    source = (ROOT / "relay/core/e4_action_preview.py").read_text()
    for forbidden in ("sqlite", "psycopg", "requests", "httpx", "aiohttp", "socket",
                      "os.environ", "apiKey", "apiSecret", "privateKey", "send_crypto",
                      "subprocess", "time.time"):
        assert forbidden not in source
