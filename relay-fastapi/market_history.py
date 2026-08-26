"""Strict normalization for public, read-only market-history cards."""

from __future__ import annotations

from math import isfinite
from typing import Any


# Deliberately small allow-list: this endpoint never proxies an arbitrary
# instrument requested by a browser.  The pairs are observations only and do
# not imply that an exchange route is available for the asset.
MARKET_HISTORY_INSTRUMENTS = {
    "BTC": "BTC-USDT",
    "ETH": "ETH-USDT",
    "LTC": "LTC-USDT",
}


def okx_instrument_for_asset(asset: Any) -> tuple[str, str]:
    """Return an explicitly supported asset and its public OKX instrument."""
    if not isinstance(asset, str):
        raise ValueError("unsupported market asset")
    code = asset.upper()
    instrument = MARKET_HISTORY_INSTRUMENTS.get(code)
    if not instrument:
        raise ValueError("unsupported market asset")
    return code, instrument


def normalize_okx_candles(payload: Any, *, limit: int = 48) -> list[dict[str, int | float]]:
    """Return chronological validated close points from an OKX candle payload."""
    if not isinstance(payload, dict) or payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise ValueError("invalid market history response")
    points: list[tuple[int, float]] = []
    for row in payload["data"]:
        if not isinstance(row, list) or len(row) < 5:
            continue
        try:
            observed_at = int(row[0])
            close = float(row[4])
        except (TypeError, ValueError):
            continue
        if observed_at <= 0 or not isfinite(close) or close <= 0:
            continue
        points.append((observed_at, close))
    points.sort(key=lambda point: point[0])
    unique: list[tuple[int, float]] = []
    for observed_at, close in points:
        if not unique or observed_at != unique[-1][0]:
            unique.append((observed_at, close))
    if len(unique) < 2:
        raise ValueError("not enough valid market history points")
    return [{"observedAt": observed_at, "close": close} for observed_at, close in unique[-limit:]]
