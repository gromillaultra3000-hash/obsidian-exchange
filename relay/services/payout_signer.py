"""Narrow secure-wallet adapter for the dedicated payout worker.

This module intentionally has no legacy bitcoinlib fallback.  A missing vault,
password, feature gate or TXID is an error requiring review, never permission to
try a weaker signing path.
"""
from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any

from core import address as address_rules
from wallet import payout_routing


def inspect_attempt(intent: dict[str, Any]) -> dict[str, Any]:
    """Read the signer idempotency ledger without unlocking a wallet.

    `absent` is the only result that proves this signer never reached its
    durable pre-broadcast claim. Malformed/unreadable files are ambiguous.
    """
    currency = str(intent.get("currency") or "").upper()
    idem = str(intent.get("idempotency_key") or "")
    if not idem:
        return {"verdict": "unknown", "reason": "idempotency_key_missing"}
    data_dir = Path(os.getenv("WALLET_DATA_DIR", "/root/wallet_data")) / "secure"
    if currency in ("BTC", "LTC"):
        path = data_dir / f"{currency.lower()}-sends.json"
    elif payout_routing.evm_payout_asset(currency, intent.get("network")):
        path = data_dir / "evm-sends.json"
    else:
        return {"verdict": "unknown", "reason": "signer_route_unsupported"}
    if not path.exists():
        return {"verdict": "absent", "reason": "signer_ledger_file_absent"}
    try:
        ledger = json.loads(path.read_text("utf-8"))
        if not isinstance(ledger, dict):
            raise ValueError("ledger_not_object")
    except Exception as exc:
        return {"verdict": "unknown", "reason": f"ledger_unreadable:{type(exc).__name__}"}
    row = ledger.get(idem)
    if row is None:
        return {"verdict": "absent", "reason": "idempotency_key_absent"}
    if not isinstance(row, dict):
        return {"verdict": "unknown", "reason": "ledger_entry_invalid"}
    txid = str(row.get("txHash") or "").strip()
    if txid:
        return {"verdict": "txid", "txid": txid,
                "reason": str(row.get("status") or "txid_recorded")[:80]}
    return {"verdict": "ambiguous", "reason": str(row.get("status") or "claimed")[:80]}


def _password() -> str:
    value = os.getenv("WALLET_PAYOUT_PASSWORD", "").strip()
    if not value:
        raise RuntimeError("wallet_password_missing")
    return value


def _valid_destination(currency: str, network: str | None, destination: str) -> bool:
    coin = currency.upper()
    if coin == "BTC":
        return address_rules.is_valid_btc(destination)
    if coin == "LTC":
        return address_rules.is_valid_ltc(destination)
    if payout_routing.evm_payout_asset(coin, network):
        return address_rules.is_valid_evm_address(destination)
    return False


def sign(intent: dict[str, Any]) -> str:
    """Sign and broadcast one already-claimed immutable payout intent."""
    if intent.get("state") != "processing":
        raise RuntimeError("payout_intent_not_claimed")
    currency = str(intent.get("currency") or "").upper()
    network = intent.get("network")
    destination = str(intent.get("destination") or "")
    amount = float(intent.get("crypto_amount") or 0)
    idem = str(intent.get("idempotency_key") or "")
    if amount <= 0:
        raise RuntimeError("payout_amount_invalid")
    if not idem:
        raise RuntimeError("payout_idempotency_key_missing")
    if not _valid_destination(currency, network, destination):
        raise RuntimeError("payout_destination_invalid")

    password = _password()
    if currency in ("BTC", "LTC"):
        from wallet import btc_wallet
        status = btc_wallet.status(currency)
        if not status.get("configured"):
            raise RuntimeError("secure_wallet_not_configured")
        if not status.get("unlocked"):
            btc_wallet.unlock(currency, password)
        preview = btc_wallet.preview_send(currency, destination, amount)
        result = btc_wallet.send(
            currency, destination, amount, preview["previewId"],
            idempotency_key=idem,
        )
    else:
        asset = payout_routing.evm_payout_asset(currency, network)
        if not asset or not payout_routing.evm_payouts_enabled():
            raise RuntimeError("payout_asset_not_enabled")
        from wallet import evm_wallet
        status = evm_wallet.status()
        if not status.get("configured"):
            raise RuntimeError("secure_wallet_not_configured")
        if not status.get("unlocked"):
            evm_wallet.unlock(password)
        preview = evm_wallet.preview_send(asset, destination, amount)
        result = evm_wallet.send(
            asset, destination, amount, preview["previewId"],
            idempotency_key=idem,
        )
    txid = str((result or {}).get("txHash") or "").strip()
    if not txid:
        raise RuntimeError("signer_returned_no_txid")
    return txid
