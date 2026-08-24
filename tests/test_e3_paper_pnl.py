import copy, json, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_market_contracts import build_market_snapshot
from app.e3_paper_admission import assess_paper_admission, create_admission_control
from app.e3_paper_intents import open_paper_intent, project_paper_fill, reconcile_paper_fill
from app.e3_paper_ledger import create_paper_ledger
from app.e3_paper_pnl import (append_pnl_reconciliation, create_pnl_journal,
                              build_total_pnl_snapshot, reconcile_paper_pnl,
                              validate_pnl_journal, validate_pnl_reconciliation,
                              validate_total_pnl_snapshot)
from app.e3_paper_risk import DAY_MS, build_paper_risk_policy, evaluate_paper_risk
from app.e3_paper_valuation import build_equity_valuation, create_equity_baseline

NOW = 1786420801000

def book():
    return build_market_snapshot(source="bybit", symbol="BTCUSDT", base_asset="BTC",
        quote_asset="USDT", observed_at_epoch_ms=1786420800123,
        bids=[["99","5"]], asks=[["101","5"]])

def initial():
    return create_paper_ledger(account_id="sandbox_1", balances={"BTC":"2","USDT":"1000"})

def completed(before=None, *, side="BUY", amount="202", fee=10, key="paper_1"):
    before = before or initial()
    policy = build_paper_risk_policy(account_id="sandbox_1", allowed_symbols=["BTCUSDT"],
        max_order_notional_quote="500", max_daily_notional_quote="2000",
        max_trades_per_day=10, max_drawdown_quote="500")
    risk = evaluate_paper_risk(before, book(), policy, side=side, input_amount=amount,
        fee_bps=fee, idempotency_key=key, evaluated_at_epoch_ms=NOW,
        usage_day_epoch=NOW//DAY_MS, daily_trade_count=0,
        daily_notional_quote="0", current_drawdown_quote="0")
    admission = assess_paper_admission(create_admission_control(account_id="sandbox_1"), risk)
    opened = open_paper_intent(risk, admission, recorded_at_epoch_ms=NOW+1)
    filled, after = project_paper_fill(opened, before, book(), idempotency_key=key,
                                      recorded_at_epoch_ms=NOW+2)
    state = reconcile_paper_fill(filled, after, recorded_at_epoch_ms=NOW+3)
    recon = reconcile_paper_pnl(before, after, state, risk, book(), [book()],
        quote_asset="USDT", assessed_at_epoch_ms=NOW, idempotency_key=key)
    return before, after, state, risk, recon

def test_buy_execution_pnl_and_base_fee_are_exact_and_non_executing():
    _, _, _, _, recon = completed()
    assert recon["feeAsset"] == "BTC"
    assert recon["feeAmount"] == "0.002"
    assert recon["feeQuote"] == "0.2"
    assert recon["equityBeforeQuote"] == "1200"
    assert recon["equityAfterQuote"] == "1197.8"
    assert recon["netExecutionPnlQuote"] == "-2.2"
    assert recon["grossExecutionPnlQuote"] == "-2"
    assert recon["paperOnly"] is True and recon["actionAllowed"] is False
    assert validate_pnl_reconciliation(json.loads(json.dumps(recon))) == recon

def test_sell_execution_pnl_and_quote_fee_are_exact():
    _, _, _, _, recon = completed(side="SELL", amount="1", fee=20)
    assert recon["feeAsset"] == "USDT"
    assert recon["feeAmount"] == "0.198"
    assert recon["feeQuote"] == "0.198"
    assert recon["netExecutionPnlQuote"] == "-1.198"
    assert recon["grossExecutionPnlQuote"] == "-1"

def test_journal_continuity_totals_restart_and_exact_retry():
    before, after, _, _, first = completed()
    fixture = json.loads((ROOT / "contracts/e3-market/paper-pnl-journal.v1.json").read_text())
    assert create_pnl_journal(account_id="sandbox_1", quote_asset="USDT",
                              start_ledger_hash="pl_start") == fixture
    journal = create_pnl_journal(account_id="sandbox_1", quote_asset="USDT",
                                 start_ledger_hash=before["ledgerHash"])
    journal = append_pnl_reconciliation(journal, first)
    _, after2, _, _, second = completed(after, side="SELL", amount="1", fee=20, key="paper_2")
    journal = append_pnl_reconciliation(json.loads(json.dumps(journal)), second)
    assert journal["tradeCount"] == 2
    assert journal["headLedgerHash"] == after2["ledgerHash"]
    assert journal["totalFeesQuote"] == "0.398"
    assert journal["totalNetExecutionPnlQuote"] == "-3.398"
    assert journal["totalGrossExecutionPnlQuote"] == "-3"
    assert append_pnl_reconciliation(journal, first) == journal
    assert validate_pnl_journal(json.loads(json.dumps(journal))) == journal

def test_only_reconciled_exact_single_entry_and_correct_key_are_accepted():
    before, after, state, risk, _ = completed()
    changed = copy.deepcopy(state); changed["status"] = "REVIEW"
    with pytest.raises(ValueError):
        reconcile_paper_pnl(before, after, changed, risk, book(), [book()],
            quote_asset="USDT", assessed_at_epoch_ms=NOW, idempotency_key="paper_1")
    with pytest.raises(ValueError):
        reconcile_paper_pnl(before, after, state, risk, book(), [book()],
            quote_asset="USDT", assessed_at_epoch_ms=NOW, idempotency_key="wrong")

def test_mismatched_price_or_stale_vector_fails_closed():
    before, after, state, risk, _ = completed()
    other = build_market_snapshot(source="okx", symbol="BTCUSDT", base_asset="BTC",
        quote_asset="USDT", observed_at_epoch_ms=1786420800123,
        bids=[["109","5"]], asks=[["111","5"]])
    with pytest.raises(ValueError):
        reconcile_paper_pnl(before, after, state, risk, book(), [other, book()],
            quote_asset="USDT", assessed_at_epoch_ms=NOW, idempotency_key="paper_1")

@pytest.mark.parametrize("field,value", [("totalFeesQuote","999"),("tradeCount",9),
    ("headHash","0"*64),("actionAllowed",True)])
def test_journal_tamper_fails_closed(field,value):
    before, _, _, _, recon = completed()
    journal = append_pnl_reconciliation(create_pnl_journal(account_id="sandbox_1",
        quote_asset="USDT", start_ledger_hash=before["ledgerHash"]), recon)
    changed=copy.deepcopy(journal); changed[field]=value
    with pytest.raises(ValueError): validate_pnl_journal(changed)

def test_discontinuous_journal_and_evidence_drift_fail_closed():
    before, _, _, _, recon = completed()
    wrong = create_pnl_journal(account_id="sandbox_1", quote_asset="USDT",
                               start_ledger_hash="pl_wrong")
    with pytest.raises(ValueError, match="continuity"):
        append_pnl_reconciliation(wrong, recon)
    journal = append_pnl_reconciliation(create_pnl_journal(account_id="sandbox_1",
        quote_asset="USDT", start_ledger_hash=before["ledgerHash"]), recon)
    changed=copy.deepcopy(recon); changed["reconciliationId"]="ppr_"+"0"*64
    with pytest.raises(ValueError): append_pnl_reconciliation(journal, changed)

def test_total_pnl_separates_execution_from_market_and_holding_residual():
    before, after, _, _, recon = completed()
    origin_value = build_equity_valuation(before, [book()], quote_asset="USDT",
                                          assessed_at_epoch_ms=NOW)
    baseline = create_equity_baseline(origin_value)
    journal = append_pnl_reconciliation(create_pnl_journal(account_id="sandbox_1",
        quote_asset="USDT", start_ledger_hash=before["ledgerHash"]), recon)
    higher = build_market_snapshot(source="bybit", symbol="BTCUSDT", base_asset="BTC",
        quote_asset="USDT", observed_at_epoch_ms=1786420800123,
        bids=[["109","5"]], asks=[["111","5"]])
    current = build_equity_valuation(after, [higher], quote_asset="USDT",
                                     assessed_at_epoch_ms=NOW)
    total = build_total_pnl_snapshot(baseline, current, journal)
    assert total["baselineEquityQuote"] == "1200"
    assert total["currentEquityQuote"] == "1237.78"
    assert total["totalPnlQuote"] == "37.78"
    assert total["executionNetPnlQuote"] == "-2.2"
    assert total["marketAndHoldingPnlQuote"] == "39.98"
    assert total["totalFeesQuote"] == "0.2"
    assert total["grossPnlBeforeFeesQuote"] == "37.98"
    assert total["taxLotAccounting"] is False
    assert not any("realized" in key.lower() or "unrealized" in key.lower() for key in total)
    assert validate_total_pnl_snapshot(json.loads(json.dumps(total))) == total

def test_empty_journal_total_snapshot_is_zero_and_bound_to_genesis():
    before = initial()
    value = build_equity_valuation(before, [book()], quote_asset="USDT",
                                   assessed_at_epoch_ms=NOW)
    total = build_total_pnl_snapshot(create_equity_baseline(value), value,
        create_pnl_journal(account_id="sandbox_1", quote_asset="USDT",
                           start_ledger_hash=before["ledgerHash"]))
    assert total["totalPnlQuote"] == "0"
    assert total["executionNetPnlQuote"] == "0"
    assert total["marketAndHoldingPnlQuote"] == "0"

@pytest.mark.parametrize("field,value", [("totalPnlQuote","999"),
    ("marketAndHoldingPnlQuote","999"),("taxLotAccounting",True),
    ("actionAllowed",True),("totalPnlId","ptp_"+"0"*64)])
def test_total_pnl_tamper_fails_closed(field,value):
    before, after, _, _, recon = completed()
    base_value=build_equity_valuation(before,[book()],quote_asset="USDT",assessed_at_epoch_ms=NOW)
    current=build_equity_valuation(after,[book()],quote_asset="USDT",assessed_at_epoch_ms=NOW)
    journal=append_pnl_reconciliation(create_pnl_journal(account_id="sandbox_1",
        quote_asset="USDT",start_ledger_hash=before["ledgerHash"]),recon)
    total=build_total_pnl_snapshot(create_equity_baseline(base_value),current,journal)
    changed=copy.deepcopy(total); changed[field]=value
    with pytest.raises(ValueError): validate_total_pnl_snapshot(changed)

def test_total_pnl_rejects_baseline_or_current_ledger_boundary_mismatch():
    before, after, _, _, recon = completed()
    baseline=create_equity_baseline(build_equity_valuation(before,[book()],quote_asset="USDT",assessed_at_epoch_ms=NOW))
    journal=append_pnl_reconciliation(create_pnl_journal(account_id="sandbox_1",
        quote_asset="USDT",start_ledger_hash=before["ledgerHash"]),recon)
    wrong_current=build_equity_valuation(before,[book()],quote_asset="USDT",assessed_at_epoch_ms=NOW)
    with pytest.raises(ValueError,match="boundary"):
        build_total_pnl_snapshot(baseline,wrong_current,journal)
