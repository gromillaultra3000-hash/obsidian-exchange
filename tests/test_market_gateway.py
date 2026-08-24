#!/usr/bin/env python3
"""KAIROS market bridge is read-only, validated and fail-soft."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import market_gateway as gateway  # noqa: E402


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"asOf": "now", "quotes": [
            {"asset": "BTC", "exchange": "bybit", "last": 123.5, "bid": 123, "ask": 124},
            {"asset": "EVIL", "exchange": "x", "last": 999},
        ]}


old_get = gateway.requests.get
gateway.requests.get = lambda url, timeout: Response()
try:
    data = gateway.public_market(["BTC"])
finally:
    gateway.requests.get = old_get

assert data["status"] == "ok"
assert data["quotes"] == [{"asset": "BTC", "exchange": "bybit", "pair": "BTC/USDT",
                           "last": 123.5, "bid": 123, "ask": 124}]

gateway.requests.get = lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError())
try:
    failed = gateway.public_market(["BTC"])
finally:
    gateway.requests.get = old_get
assert failed["status"] == "unavailable" and failed["quotes"] == []

print("OK: KAIROS market gateway is validated and fail-soft")
