import copy
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_market_contracts import (build_market_snapshot, compare_market_sources,
                                     estimate_market_fill, validate_market_snapshot)


def snapshot():
    return build_market_snapshot(
        source="bybit", symbol="BTC/USDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=1786420800123,
        bids=[["99", "2"], ["98", "3"]],
        asks=[["101", "1"], ["102", "2"]])


def source_snapshot(source, midpoint, observed_at=1786420800123):
    midpoint = int(midpoint)
    return build_market_snapshot(
        source=source, symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=observed_at,
        bids=[[str(midpoint - 1), "2"]], asks=[[str(midpoint + 1), "2"]])


def test_snapshot_is_canonical_content_addressed_and_non_executing():
    first = snapshot()
    second = build_market_snapshot(
        source=" BYBIT ", symbol="btcusdt", base_asset="btc", quote_asset="usdt",
        observed_at_epoch_ms=1786420800123,
        bids=[["99.0", "2.00"], ["98.00", "3.0"]],
        asks=[["101.0", "1.00"], ["102.00", "2.0"]])
    assert first == second
    assert first["snapshotId"].startswith("md_")
    assert validate_market_snapshot(json.loads(json.dumps(first))) == first
    assert first["executionEffect"] == "NONE"
    assert first["actionAllowed"] is False


def test_snapshot_matches_frozen_fixture():
    fixture = json.loads(
        (ROOT / "contracts/e3-market/market-depth-snapshot.v1.json").read_text())
    assert snapshot() == fixture


def test_buy_and_sell_walk_depth_with_decimal_fee_and_slippage():
    buy = estimate_market_fill(snapshot(), side="BUY", input_amount="203", fee_bps=10)
    assert buy["grossOutputAmount"] == "2"
    assert buy["feeOutputAmount"] == "0.002"
    assert buy["netOutputAmount"] == "1.998"
    assert buy["averagePrice"] == "101.5"
    assert buy["slippageBps"] == "150"
    assert buy["levelsUsed"] == 2

    sell = estimate_market_fill(snapshot(), side="SELL", input_amount="3", fee_bps=20)
    assert sell["grossOutputAmount"] == "296"
    assert sell["feeOutputAmount"] == "0.592"
    assert sell["netOutputAmount"] == "295.408"
    assert sell["averagePrice"] == "98.666666666666666666666666666666666666666666666667"
    assert sell["projectionOnly"] is True
    assert sell["actionAllowed"] is False


@pytest.mark.parametrize("field,value", [
    ("snapshotId", "md_" + "0" * 64),
    ("executionEffect", "TRADE"),
    ("actionAllowed", True),
    ("observedAtEpochMs", 0),
])
def test_snapshot_tamper_fails_closed(field, value):
    changed = copy.deepcopy(snapshot())
    changed[field] = value
    with pytest.raises(ValueError):
        validate_market_snapshot(changed)


@pytest.mark.parametrize("changes", [
    {"bids": [["98", "1"], ["99", "1"]]},
    {"asks": [["101", "1"], ["101", "2"]]},
    {"bids": [["102", "1"]]},
    {"asks": [["NaN", "1"]]},
    {"asks": [["1e2", "1"]]},
    {"asks": [["101", "0"]]},
])
def test_malformed_or_crossed_depth_fails_closed(changes):
    values = dict(source="bybit", symbol="BTCUSDT", base_asset="BTC",
                  quote_asset="USDT", observed_at_epoch_ms=1786420800123,
                  bids=[["99", "1"]], asks=[["101", "1"]])
    values.update(changes)
    with pytest.raises(ValueError):
        build_market_snapshot(**values)


@pytest.mark.parametrize("kwargs", [
    {"side": "HOLD", "input_amount": "1", "fee_bps": 10},
    {"side": "BUY", "input_amount": "9999", "fee_bps": 10},
    {"side": "SELL", "input_amount": "0", "fee_bps": 10},
    {"side": "BUY", "input_amount": "1e3", "fee_bps": 10},
    {"side": "BUY", "input_amount": "1", "fee_bps": 10001},
])
def test_estimate_rejects_unknown_side_bad_amount_fee_or_partial_fill(kwargs):
    with pytest.raises(ValueError):
        estimate_market_fill(snapshot(), **kwargs)


def test_multi_source_comparison_is_canonical_fresh_and_non_executing():
    assessed = 1786420801000
    result = compare_market_sources([
        source_snapshot("okx", 100), source_snapshot("bybit", 100),
        source_snapshot("kucoin", 101)], assessed_at_epoch_ms=assessed)
    reversed_result = compare_market_sources([
        source_snapshot("kucoin", 101), source_snapshot("bybit", 100),
        source_snapshot("okx", 100)], assessed_at_epoch_ms=assessed)
    assert result == reversed_result
    assert result["status"] == "CONSISTENT"
    assert result["freshSourceCount"] == 3
    assert result["referenceMidpointPrice"] == "100"
    assert result["comparisonId"].startswith("mc_")
    assert result["projectionOnly"] is True
    assert result["executionEffect"] == "NONE"
    assert result["actionAllowed"] is False


def test_stale_and_future_sources_are_explicit_and_never_zero_filled():
    assessed = 1786420810000
    result = compare_market_sources([
        source_snapshot("bybit", 100, assessed - 6000),
        source_snapshot("okx", 101, assessed + 1001),
        source_snapshot("kucoin", 102, assessed)], assessed_at_epoch_ms=assessed)
    assert result["status"] == "INSUFFICIENT_FRESH_SOURCES"
    assert result["freshSourceCount"] == 1
    assert result["referenceMidpointPrice"] is None
    assert result["maxDeviationBps"] is None
    assert {row["freshness"] for row in result["sources"]} == {"STALE", "FUTURE", "FRESH"}
    assert all(row["midpointPrice"] != "0" for row in result["sources"])


def test_divergent_fresh_sources_fail_closed():
    result = compare_market_sources([
        source_snapshot("bybit", 100), source_snapshot("okx", 104)],
        assessed_at_epoch_ms=1786420801000)
    assert result["status"] == "DIVERGENT"
    assert Decimal(result["maxDeviationBps"]) > Decimal(result["divergenceLimitBps"])
    assert result["actionAllowed"] is False


@pytest.mark.parametrize("books", [
    [source_snapshot("bybit", 100)],
    [source_snapshot("bybit", 100), source_snapshot("bybit", 101)],
    [source_snapshot("bybit", 100), build_market_snapshot(
        source="okx", symbol="ETHUSDT", base_asset="ETH", quote_asset="USDT",
        observed_at_epoch_ms=1786420800123,
        bids=[["99", "1"]], asks=[["101", "1"]])],
])
def test_comparison_rejects_unbounded_duplicate_or_mixed_market_inputs(books):
    with pytest.raises(ValueError):
        compare_market_sources(books, assessed_at_epoch_ms=1786420801000)
