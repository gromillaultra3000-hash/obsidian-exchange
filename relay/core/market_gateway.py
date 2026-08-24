"""Fail-soft read-only мост Obsidian Wallet → KAIROS market data."""

import os
from urllib.parse import urlencode, urlparse

import requests


def _base_url() -> str:
    value = (os.getenv("KAIROS_URL") or "http://127.0.0.1:8000").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("KAIROS_URL must be a loopback HTTP address")
    return value


def public_market(assets=None, timeout=6.0) -> dict:
    """Возвращает только публичные цены; сбой KAIROS не ломает кошелёк."""
    wanted = [str(x).upper() for x in (assets or ["BTC", "ETH", "LTC", "TON", "TRX"])]
    try:
        url = _base_url() + "/api/market/quotes?" + urlencode({"assets": ",".join(wanted)})
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        quotes = data.get("quotes") if isinstance(data, dict) else None
        if not isinstance(quotes, list):
            raise ValueError("invalid quote payload")
        clean = []
        for row in quotes[:100]:
            if not isinstance(row, dict):
                continue
            asset = str(row.get("asset") or "").upper()
            exchange = str(row.get("exchange") or "").lower()
            last = float(row.get("last") or 0)
            if asset not in wanted or not exchange or last <= 0:
                continue
            clean.append({"asset": asset, "exchange": exchange, "pair": f"{asset}/USDT",
                          "last": last, "bid": row.get("bid"), "ask": row.get("ask")})
        return {"status": "ok" if clean else "unavailable", "quotes": clean,
                "sources": sorted({x["exchange"] for x in clean}), "asOf": data.get("asOf")}
    except Exception as exc:
        return {"status": "unavailable", "quotes": [], "sources": [],
                "message": "Биржевые котировки временно недоступны.", "errorClass": type(exc).__name__}
