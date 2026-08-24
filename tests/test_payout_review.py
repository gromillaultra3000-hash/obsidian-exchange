import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from core import payout_intents as pi
from core import payout_discovery
from services import payout_signer


def conn_with_intent(state="review"):
    conn = sqlite3.connect(":memory:")
    pi.ensure_schema(conn)
    pi.create(conn, order_id=7, rub_amount=1000, crypto_amount=.001,
              currency="BTC", network=None, destination="bc1qdest", source="test")
    assert pi.claim(conn, 7)
    if state == "review":
        assert pi.review(conn, 7, "TimeoutError")
    return conn


def test_confirm_requires_uncertain_state_and_appends_audit():
    conn = conn_with_intent()
    txid = "a" * 64
    assert pi.admin_confirm_txid(conn, 7, txid, actor=99,
                                 evidence="chain_final amount=.001 destination=bc1qdest")
    assert pi.get(conn, 7)["state"] == "succeeded"
    row = conn.execute("SELECT action,from_state,to_state,txid FROM payout_intent_audit").fetchone()
    assert row == ("confirm_txid", "review", "succeeded", txid)
    assert not pi.admin_confirm_txid(conn, 7, txid, actor=99, evidence="again")


def test_requeue_only_review_and_appends_audit():
    processing = conn_with_intent("processing")
    assert not pi.admin_requeue_absent(processing, 7, actor=99,
                                       evidence="signer ledger absent")
    conn = conn_with_intent()
    assert pi.admin_requeue_absent(conn, 7, actor=99,
                                   evidence="signer ledger absent")
    row = pi.get(conn, 7)
    assert row["state"] == "pending" and row["txid"] is None
    assert conn.execute("SELECT action FROM payout_intent_audit").fetchone()[0] == "requeue_after_absence"


def test_signer_ledger_absence_and_ambiguity_are_distinct():
    old = os.environ.get("WALLET_DATA_DIR")
    with tempfile.TemporaryDirectory() as td:
        os.environ["WALLET_DATA_DIR"] = td
        intent = {"currency": "BTC", "network": None,
                  "idempotency_key": "payout_7"}
        assert payout_signer.inspect_attempt(intent)["verdict"] == "absent"
        secure = Path(td) / "secure"
        secure.mkdir()
        path = secure / "btc-sends.json"
        path.write_text(json.dumps({"payout_7": {"status": "broadcasting"}}))
        assert payout_signer.inspect_attempt(intent)["verdict"] == "ambiguous"
        path.write_text(json.dumps({"payout_7": {"status": "CONFIRMED", "txHash": "b" * 64}}))
        result = payout_signer.inspect_attempt(intent)
        assert result["verdict"] == "txid" and result["txid"] == "b" * 64
        path.write_text("not json")
        assert payout_signer.inspect_attempt(intent)["verdict"] == "unknown"
    if old is None:
        os.environ.pop("WALLET_DATA_DIR", None)
    else:
        os.environ["WALLET_DATA_DIR"] = old


def test_non_order_debt_requires_exact_final_trusted_transfer():
    old_used, old_trusted = payout_discovery._used_txids, payout_discovery.trusted_senders
    payout_discovery._used_txids = lambda: set()
    payout_discovery.trusted_senders = lambda _currency: {"our-wallet"}
    try:
        transfer = {"txid": "a" * 64, "amount": .001, "ts": 200,
                    "senders": {"our-wallet"}, "confirmations": 10,
                    "confirmed": True}
        verdict = payout_discovery.candidates_for_debt(
            currency="BTC", network=None, destination="dest", expected_amount=.001,
            created_ts=100, fetch=lambda *_args: [transfer])
        assert verdict["candidates"][0]["trusted"] is True
        wrong = payout_discovery.candidates_for_debt(
            currency="BTC", network=None, destination="dest", expected_amount=.002,
            created_ts=100, fetch=lambda *_args: [transfer])
        assert not wrong["candidates"]
    finally:
        payout_discovery._used_txids, payout_discovery.trusted_senders = old_used, old_trusted


if __name__ == "__main__":
    test_confirm_requires_uncertain_state_and_appends_audit()
    test_requeue_only_review_and_appends_audit()
    test_signer_ledger_absence_and_ambiguity_are_distinct()
    test_non_order_debt_requires_exact_final_trusted_transfer()
    print("payout review tests: OK")
