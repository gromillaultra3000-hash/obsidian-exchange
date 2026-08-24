import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_market_contracts import build_market_snapshot
from app.e3_paper_ledger import (apply_paper_trade, create_paper_ledger,
                                 validate_paper_ledger)


def book():
    return build_market_snapshot(
        source="bybit", symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT",
        observed_at_epoch_ms=1786420800123,
        bids=[["99", "2"], ["98", "3"]], asks=[["101", "1"], ["102", "2"]])


def ledger():
    return create_paper_ledger(account_id="sandbox_1", balances={"BTC": "1", "USDT": "1000"})


def trade(state=None, **changes):
    values = dict(side="BUY", input_amount="203", fee_bps=10,
                  idempotency_key="order_1", recorded_at_epoch_ms=1786420801000)
    values.update(changes)
    return apply_paper_trade(state or ledger(), book(), **values)


def test_genesis_and_trade_are_canonical_non_executing_and_json_stable():
    genesis = ledger()
    fixture = json.loads((ROOT / "contracts/e3-market/paper-trade-ledger.v1.json").read_text())
    assert genesis == fixture
    assert create_paper_ledger(account_id=" sandbox_1 ",
                               balances={"usdt": "1000.00", "btc": "1.0"}) == genesis
    result = trade(genesis)
    assert result["sequence"] == 1
    assert result["balances"] == {"BTC": "2.998", "USDT": "797"}
    assert result["entries"][0]["previousHash"] == "0" * 64
    assert result["headHash"] == result["entries"][0]["entryHash"]
    assert result["simulationOnly"] is True
    assert result["executionEffect"] == "NONE"
    assert result["actionAllowed"] is False
    assert validate_paper_ledger(json.loads(json.dumps(result))) == result


def test_exact_retry_is_idempotent_but_key_drift_fails_closed():
    first = trade()
    assert trade(first) == first
    with pytest.raises(ValueError, match="another request"):
        trade(first, input_amount="101")


def test_restart_round_trip_then_second_trade_preserves_chain_and_balances():
    first = json.loads(json.dumps(trade()))
    second = trade(first, side="SELL", input_amount="1", fee_bps=20,
                   idempotency_key="order_2", recorded_at_epoch_ms=1786420802000)
    assert second["sequence"] == 2
    assert second["entries"][1]["previousHash"] == second["entries"][0]["entryHash"]
    assert second["balances"] == {"BTC": "1.998", "USDT": "895.802"}
    assert validate_paper_ledger(second) == second


@pytest.mark.parametrize("field,value", [
    ("balances", {"BTC": "999", "USDT": "0"}),
    ("headHash", "0" * 64),
    ("sequence", 9),
    ("executionEffect", "LIVE"),
    ("actionAllowed", True),
])
def test_ledger_tamper_fails_closed(field, value):
    changed = copy.deepcopy(trade())
    changed[field] = value
    with pytest.raises(ValueError):
        validate_paper_ledger(changed)


def test_entry_tamper_and_duplicate_idempotency_fail_closed():
    changed = copy.deepcopy(trade())
    changed["entries"][0]["netOutputAmount"] = "999"
    with pytest.raises(ValueError):
        validate_paper_ledger(changed)
    duplicate = trade(trade(), side="SELL", input_amount="1", fee_bps=20,
                      idempotency_key="order_2", recorded_at_epoch_ms=1786420802000)
    duplicate["entries"][1]["idempotencyHash"] = duplicate["entries"][0]["idempotencyHash"]
    with pytest.raises(ValueError):
        validate_paper_ledger(duplicate)


def test_consistently_rehashed_balance_forgery_still_fails_semantic_replay():
    changed = copy.deepcopy(trade())
    changed["entries"][0]["balancesAfter"]["BTC"] = "999"
    entry = changed["entries"][0]
    unsigned_entry = dict(entry)
    unsigned_entry.pop("entryHash")
    from app.e3_paper_ledger import _hash
    entry["entryHash"] = _hash(unsigned_entry)
    changed["headHash"] = entry["entryHash"]
    changed["balances"] = dict(entry["balancesAfter"])
    unsigned_ledger = dict(changed)
    unsigned_ledger.pop("ledgerHash")
    changed["ledgerHash"] = "pl_" + _hash(unsigned_ledger)
    with pytest.raises(ValueError, match="balance arithmetic"):
        validate_paper_ledger(changed)


@pytest.mark.parametrize("changes", [
    {"input_amount": "2000"},
    {"idempotency_key": "bad key"},
    {"recorded_at_epoch_ms": 0},
])
def test_trade_rejects_insufficient_balance_bad_key_or_time(changes):
    with pytest.raises(ValueError):
        trade(**changes)


def test_trade_requires_both_assets_in_genesis():
    state = create_paper_ledger(account_id="sandbox_1", balances={"USDT": "1000"})
    with pytest.raises(ValueError, match="both paper assets"):
        trade(state)
