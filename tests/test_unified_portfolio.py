import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELAY = ROOT / "relay"
if str(RELAY) not in sys.path:
    sys.path.insert(0, str(RELAY))

from core.unified_portfolio import aggregate


NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


def test_three_custody_lanes_share_honest_freshness_semantics():
    result = aggregate(
        wallets=[{"chain": "BTC", "address": "bc1-test", "status": "OK", "balance": 0.125}],
        exchange_orders=[{"status": "sent", "created_at": "2026-08-10T19:00:00+00:00"}],
        cex_items=[{
            "source": {"sourceId": "src_" + "a" * 24, "providerId": "bybit", "state": "DEGRADED"},
            "balances": [{"assetId": "USDT", "total": "12.3400", "available": "12.3400",
                          "locked": "0", "state": "STALE", "asOf": NOW.isoformat(),
                          "observedAt": NOW.isoformat(), "errorCode": None}],
        }], cex_available=True, observed_at=NOW)
    assert [lane["custodyDomain"] for lane in result["lanes"]] == [
        "SELF_CUSTODY", "OBSIDIAN_OPERATIONAL", "CEX_CUSTODY"]
    assert result["complete"] is False
    cex = result["lanes"][2]["sources"][0]
    assert cex["balances"][0]["total"] == "12.3400"
    assert cex["balances"][0]["state"] == "STALE"
    assert result["lanes"][1]["sources"][0]["balances"] == []
    assert result["lanes"][1]["sources"][0]["activity"]["successfulOrderCount"] == 1
    assert "bc1-test" not in str(result)


def test_unavailable_cex_is_fail_soft_and_unknown_wallet_is_never_zero():
    result = aggregate(
        wallets=[{"chain": "ETH", "address": "0x-test", "status": "ERROR", "balance": None}],
        exchange_orders=[], cex_items=[], cex_available=False, observed_at=NOW)
    wallet = result["lanes"][0]["sources"][0]["balances"][0]
    assert wallet["total"] is None and wallet["state"] == "ERROR"
    assert result["lanes"][1]["state"] == "AVAILABLE"
    assert result["lanes"][2]["state"] == "UNAVAILABLE"
    assert result["complete"] is False


def test_empty_optional_lanes_are_complete_not_errors():
    result = aggregate(
        wallets=[], exchange_orders=[], cex_items=[], cex_available=True, observed_at=NOW)
    assert result["complete"] is True
    assert [lane["state"] for lane in result["lanes"]] == ["EMPTY", "AVAILABLE", "EMPTY"]


def test_each_backend_failure_marks_only_its_lane_unavailable():
    result = aggregate(
        wallets=[], exchange_orders=[], cex_items=[], cex_available=True,
        wallet_available=False, exchange_available=False, observed_at=NOW)
    assert [lane["state"] for lane in result["lanes"]] == [
        "UNAVAILABLE", "UNAVAILABLE", "EMPTY"]
    assert result["complete"] is False
    assert set(result["issues"]) == {
        "wallets_unavailable", "obsidian_exchange_unavailable"}
