"""Pure normalization for the three read-only portfolio custody domains."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


SCHEMA_VERSION = "unified-portfolio.v1"
_BAD_STATES = {"STALE", "UNKNOWN", "ERROR"}


def _now(value: datetime | None = None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return result.astimezone(timezone.utc)


def _decimal(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return format(parsed, "f")


def _wallet_sources(wallets: list, observed: datetime) -> list:
    sources = []
    for wallet in wallets or []:
        chain = str(wallet.get("chain") or "").upper()
        address = str(wallet.get("address") or "")
        source_id = "wallet_" + hashlib.sha256(
            f"{chain}\0{address}".encode()).hexdigest()[:32]
        raw_assets = wallet.get("assets")
        if not isinstance(raw_assets, list) or not raw_assets:
            raw_assets = [{
                "asset": wallet.get("asset") or chain,
                "balance": wallet.get("balance"),
                "status": wallet.get("status"),
                "reason": wallet.get("reason"),
            }]
        balances = []
        for item in raw_assets:
            asset = str(item.get("asset") or chain).upper()
            amount = _decimal(item.get("balance"))
            fresh = amount is not None and (item.get("status") or wallet.get("status")) == "OK"
            balances.append({
                "assetId": asset, "network": chain, "total": amount if fresh else None,
                "available": None, "locked": None,
                "state": "FRESH" if fresh else "ERROR",
                "asOf": observed.isoformat() if fresh else None,
                "observedAt": observed.isoformat(),
                "errorCode": None if fresh else "BALANCE_UNAVAILABLE",
            })
        sources.append({
            "sourceId": source_id, "kind": "VERIFIED_WALLET",
            "custodyDomain": "SELF_CUSTODY", "providerId": chain.lower(),
            "state": "AVAILABLE" if all(x["state"] == "FRESH" for x in balances) else "DEGRADED",
            "balances": balances,
        })
    return sources


def _exchange_source(orders: list) -> dict:
    successful = [row for row in (orders or []) if row.get("status") in {"sent", "completed"}]
    return {
        "sourceId": "obsidian_exchange", "kind": "OBSIDIAN_EXCHANGE",
        "custodyDomain": "OBSIDIAN_OPERATIONAL", "providerId": "obsidian_exchange",
        "state": "AVAILABLE", "balances": [],
        "activity": {
            "orderCount": len(orders or []), "successfulOrderCount": len(successful),
            "latestOrderAt": (orders[0].get("created_at") if orders else None),
        },
    }


def _cex_sources(items: list) -> list:
    output = []
    for item in items or []:
        source = item.get("source") if isinstance(item, dict) else None
        if not isinstance(source, dict):
            continue
        balances = []
        for row in item.get("balances") or []:
            if not isinstance(row, dict):
                continue
            balances.append({key: row.get(key) for key in (
                "assetId", "network", "total", "available", "locked", "state",
                "asOf", "observedAt", "errorCode")})
        output.append({
            "sourceId": source.get("sourceId"), "kind": "CEX_ACCOUNT",
            "custodyDomain": "CEX_CUSTODY", "providerId": source.get("providerId"),
            "state": source.get("state"), "balances": balances,
            "permissionCheckedAt": item.get("permissionCheckedAt"),
            "balanceCheckedAt": item.get("balanceCheckedAt"),
            "lastErrorCode": item.get("lastErrorCode"),
        })
    return output


def aggregate(
    *, wallets: list, exchange_orders: list, cex_items: list,
    cex_available: bool, wallet_available: bool = True,
    exchange_available: bool = True, observed_at: datetime | None = None,
) -> dict:
    observed = _now(observed_at)
    wallet_sources = _wallet_sources(wallets, observed)
    cex_sources = _cex_sources(cex_items)
    lanes = [
        {"id": "wallets", "custodyDomain": "SELF_CUSTODY",
         "state": "UNAVAILABLE" if not wallet_available else ("EMPTY" if not wallet_sources else (
             "DEGRADED" if any(s["state"] == "DEGRADED" for s in wallet_sources) else "AVAILABLE")),
         "sources": wallet_sources},
        {"id": "obsidian_exchange", "custodyDomain": "OBSIDIAN_OPERATIONAL",
         "state": "AVAILABLE" if exchange_available else "UNAVAILABLE",
         "sources": [_exchange_source(exchange_orders)] if exchange_available else []},
        {"id": "verified_exchanges", "custodyDomain": "CEX_CUSTODY",
         "state": "UNAVAILABLE" if not cex_available else (
             "EMPTY" if not cex_sources else (
                 "DEGRADED" if any(s["state"] != "READ_ONLY_VERIFIED" for s in cex_sources) else "AVAILABLE")),
         "sources": cex_sources},
    ]
    issues = []
    if any(lane["state"] in {"DEGRADED", "UNAVAILABLE"} for lane in lanes):
        issues.extend(lane["id"] + "_" + lane["state"].lower()
                      for lane in lanes if lane["state"] in {"DEGRADED", "UNAVAILABLE"})
    if any(balance.get("state") in _BAD_STATES
           for lane in lanes for source in lane["sources"] for balance in source.get("balances", [])):
        issues.append("balance_data_incomplete")
    return {
        "schemaVersion": SCHEMA_VERSION, "observedAt": observed.isoformat(),
        "complete": not issues, "issues": issues, "lanes": lanes,
    }
