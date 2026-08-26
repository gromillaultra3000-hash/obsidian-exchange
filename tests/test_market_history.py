from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


SPEC = spec_from_file_location("market_history", Path(__file__).resolve().parents[1] / "relay-fastapi" / "market_history.py")
market_history = module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(market_history)


def test_normalize_okx_candles_validates_and_orders_public_close_points():
    payload = {"code": "0", "data": [
        ["3000", "0", "0", "0", "12.5"],
        ["1000", "0", "0", "0", "10"],
        ["2000", "0", "0", "0", "11"],
        ["oops", "0", "0", "0", "11"],
    ]}
    assert market_history.normalize_okx_candles(payload) == [
        {"observedAt": 1000, "close": 10.0},
        {"observedAt": 2000, "close": 11.0},
        {"observedAt": 3000, "close": 12.5},
    ]


def test_normalize_okx_candles_rejects_unknown_or_insufficient_payloads():
    with pytest.raises(ValueError):
        market_history.normalize_okx_candles({"code": "1", "data": []})
    with pytest.raises(ValueError):
        market_history.normalize_okx_candles({"code": "0", "data": [["1", "0", "0", "0", "0"]]})
