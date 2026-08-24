"""Pure E4 money-action preview; never confirms or executes an action."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

SCHEMA = "wallet-action-preview.v1"
LANES = {"private_exchange", "verified_exchanges"}
SIDES = {"BUY_CRYPTO", "SELL_CRYPTO"}
ASSETS = {"RUB", "BTC", "ETH", "LTC", "TRX", "USDT"}
_LANE_CONTRACTS = {
    "private_exchange": {
        "executor": {"id": "OBSIDIAN_EXCHANGE", "label": "ObsidianExchange"},
        "identity": {"kycRequired": False, "performedBy": "NONE"},
        "availability": "AVAILABLE",
    },
    "verified_exchanges": {
        "executor": {"id": "EXTERNAL_CEX", "label": "Выбранная внешняя биржа"},
        "identity": {"kycRequired": True, "performedBy": "EXTERNAL_CEX"},
        "availability": "PLANNED",
    },
}
_RISKS = {
    "private_exchange": [
        "QUOTE_CAN_EXPIRE", "PAYMENT_REVIEW_CAN_DELAY_COMPLETION",
        "ONCHAIN_TRANSFER_IS_IRREVERSIBLE",
    ],
    "verified_exchanges": [
        "EXTERNAL_CEX_CUSTODY", "EXTERNAL_CEX_KYC_APPLIES",
        "QUOTE_CAN_EXPIRE", "TRADING_ACTION_IS_IRREVERSIBLE_AFTER_EXECUTION",
    ],
}


def _hash(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 \
            or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ValueError(f"{field} is invalid")
    return value


def _time(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _amount(value: Any, field: str, *, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError(f"{field} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not number.is_finite() or number < 0 or (not allow_zero and number == 0):
        raise ValueError(f"{field} is outside bounds")
    canonical = format(number, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical != value:
        raise ValueError(f"{field} must be canonical")
    return canonical


def _asset(value: Any, field: str) -> str:
    if value not in ASSETS:
        raise ValueError(f"{field} is unsupported")
    return value


def _custody(lane: str, side: str) -> dict[str, str]:
    if lane == "verified_exchanges":
        return {"before": "EXTERNAL_CEX_ACCOUNT", "during": "EXTERNAL_CEX_ACCOUNT",
                "after": "EXTERNAL_CEX_ACCOUNT"}
    if side == "BUY_CRYPTO":
        return {"before": "USER_PAYMENT_ACCOUNT",
                "during": "OBSIDIAN_EXCHANGE_ORDER_FLOW",
                "after": "USER_DESTINATION_WALLET"}
    return {"before": "USER_SOURCE_WALLET",
            "during": "OBSIDIAN_EXCHANGE_ORDER_FLOW",
            "after": "USER_BANK_ACCOUNT"}


def build_action_preview(*, lane: str, side: str, quote_id: str,
                         quoted_at_epoch_ms: int, expires_at_epoch_ms: int,
                         spend_asset: str, spend_amount: str,
                         receive_asset: str, receive_amount: str,
                         fee_items: Sequence[Mapping[str, Any]],
                         fee_asset: str) -> dict[str, Any]:
    if lane not in LANES or side not in SIDES:
        raise ValueError("lane or side is invalid")
    spend = _asset(spend_asset, "spendAsset")
    receive = _asset(receive_asset, "receiveAsset")
    if spend == receive or (side == "BUY_CRYPTO" and spend != "RUB") \
            or (side == "SELL_CRYPTO" and receive != "RUB"):
        raise ValueError("asset direction does not match side")
    quoted = _time(quoted_at_epoch_ms, "quotedAtEpochMs")
    expires = _time(expires_at_epoch_ms, "expiresAtEpochMs")
    if not quoted < expires <= quoted + 15 * 60 * 1000:
        raise ValueError("quote lifetime is invalid")
    if not isinstance(fee_items, Sequence) or isinstance(fee_items, (str, bytes)) \
            or not 1 <= len(fee_items) <= 8:
        raise ValueError("feeItems are invalid")
    normalized_fees = []
    total = Decimal("0")
    fee_asset_value = _asset(fee_asset, "feeAsset")
    for item in fee_items:
        if not isinstance(item, Mapping) or set(item) != {"type", "amount", "asset"} \
                or item["type"] not in {"SERVICE", "NETWORK", "PROVIDER"} \
                or item["asset"] != fee_asset_value:
            raise ValueError("fee item is invalid")
        amount = _amount(item["amount"], "feeAmount", allow_zero=True)
        total += Decimal(amount)
        normalized_fees.append({"type": item["type"], "amount": amount,
                                "asset": fee_asset_value})
    contract = _LANE_CONTRACTS[lane]
    unsigned = {
        "schemaVersion": SCHEMA, "lane": lane, "side": side,
        "executor": contract["executor"], "custody": _custody(lane, side),
        "identity": contract["identity"],
        "amounts": {"spendAsset": spend, "spendAmount": _amount(spend_amount, "spendAmount"),
                    "receiveAsset": receive,
                    "receiveAmount": _amount(receive_amount, "receiveAmount")},
        "fees": {"items": normalized_fees, "totalAsset": fee_asset_value,
                 "totalAmount": _amount(format(total, "f"), "feeTotal", allow_zero=True)},
        "quote": {"quoteId": _token(quote_id, "quoteId"),
                  "quotedAtEpochMs": quoted, "expiresAtEpochMs": expires},
        "risks": _RISKS[lane], "irreversibleAfterExecution": True,
        "availability": contract["availability"],
        "confirmationAvailable": False, "containsSecrets": False,
        "executionEffect": "NONE", "actionAllowed": False,
    }
    return {**unsigned, "previewId": "wap_" + _hash(unsigned)}


def validate_action_preview(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schemaVersion", "previewId", "lane", "side", "executor", "custody",
                "identity", "amounts", "fees", "quote", "risks",
                "irreversibleAfterExecution", "availability",
                "confirmationAvailable", "containsSecrets", "executionEffect",
                "actionAllowed"}
    if not isinstance(value, Mapping) or set(value) != required \
            or value.get("schemaVersion") != SCHEMA \
            or value.get("irreversibleAfterExecution") is not True \
            or value.get("confirmationAvailable") is not False \
            or value.get("containsSecrets") is not False \
            or value.get("executionEffect") != "NONE" \
            or value.get("actionAllowed") is not False:
        raise ValueError("action preview schema is invalid")
    amounts, fees, quote = value.get("amounts"), value.get("fees"), value.get("quote")
    if not all(isinstance(item, Mapping) for item in (amounts, fees, quote)) \
            or set(amounts) != {"spendAsset", "spendAmount", "receiveAsset", "receiveAmount"} \
            or set(fees) != {"items", "totalAsset", "totalAmount"} \
            or set(quote) != {"quoteId", "quotedAtEpochMs", "expiresAtEpochMs"}:
        raise ValueError("action preview nested schema is invalid")
    rebuilt = build_action_preview(
        lane=value["lane"], side=value["side"], quote_id=quote["quoteId"],
        quoted_at_epoch_ms=quote["quotedAtEpochMs"],
        expires_at_epoch_ms=quote["expiresAtEpochMs"],
        spend_asset=amounts["spendAsset"], spend_amount=amounts["spendAmount"],
        receive_asset=amounts["receiveAsset"], receive_amount=amounts["receiveAmount"],
        fee_items=fees["items"], fee_asset=fees["totalAsset"])
    if rebuilt != dict(value) or fees["totalAmount"] != rebuilt["fees"]["totalAmount"]:
        raise ValueError("action preview does not match canonical content")
    return rebuilt
