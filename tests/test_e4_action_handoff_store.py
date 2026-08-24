import copy
import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_action_reservation import build_action_reservation_request
from core.e4_confirmation_draft import build_confirmation_draft
from repositories.e4_action_handoff_store import SQLiteE4ActionHandoffStore
from test_e4_action_acknowledgement import acknowledge, challenge
from test_e4_action_preview import preview
from test_e4_private_action_adapter import (
    ACTOR_USER_ID, PRINCIPAL, assess_private_action_draft, evidence,
)


def schema(path):
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE e4_action_reservations(
          reservation_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,
          draft_id TEXT NOT NULL UNIQUE,assessment_id TEXT NOT NULL,
          principal_ref TEXT NOT NULL,actor_user_id INTEGER NOT NULL,
          idempotency_key_sha256 TEXT NOT NULL,workflow_mapping TEXT NOT NULL,
          payload_sha256 TEXT NOT NULL,quote_expires_at_epoch_ms INTEGER NOT NULL,
          requested_at_epoch_ms INTEGER NOT NULL,expires_at_epoch_ms INTEGER NOT NULL,
          state TEXT NOT NULL CHECK(state IN('reserved','committed')),
          result_kind TEXT,result_id INTEGER,UNIQUE(principal_ref,idempotency_key_sha256));
        CREATE TABLE orders(
          order_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,
          currency TEXT,rub_amount TEXT,crypto_address TEXT,status TEXT,
          web_user_id INTEGER,network TEXT,agreed_rate TEXT,agreed_crypto_amount TEXT,
          agreed_at TEXT);
        CREATE TABLE sell_orders(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,currency TEXT,
          crypto_amount TEXT,rub_amount TEXT,sbp_phone TEXT,receive_address TEXT,
          status TEXT,payout_method TEXT,payout_bank TEXT,payout_details TEXT,payout_name TEXT);
        """)


def build(side="BUY_CRYPTO"):
    action = preview(side=side)
    gate, receipt = challenge(action), None
    receipt = acknowledge(action, gate)
    if side == "BUY_CRYPTO":
        destination = {"kind": "WALLET_ADDRESS", "network": "bitcoin",
                       "destinationFingerprintSha256": hashlib.sha256(
                           b"destination").hexdigest()}
        order = {"user_id": ACTOR_USER_ID, "username": "tester", "currency": "BTC",
                 "rub_amount": "10000", "destination": "destination",
                 "network": "bitcoin", "agreed_rate": "10000000",
                 "agreed_crypto_amount": "0.001", "web_user_id": 3}
    else:
        payout = {"sbp_phone": "+79990000000", "payout_method": "sbp",
                  "payout_bank": "bank", "payout_details": "+79990000000",
                  "payout_name": "User"}
        digest = hashlib.sha256(json.dumps(
            payout, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        destination = {"kind": "BANK_ACCOUNT", "network": None,
                       "destinationFingerprintSha256": digest}
        order = {"user_id": ACTOR_USER_ID, "currency": "BTC",
                 "crypto_amount": "0.001", "rub_amount": "10000",
                 "receive_address": "exchange_deposit", **payout}
    draft = build_confirmation_draft(
        preview=action, challenge=gate, acknowledgement_receipt=receipt,
        idempotency_key="confirm_handoff", destination_summary=destination,
        created_at_epoch_ms=receipt["acknowledgedAtEpochMs"] + 1)
    assessed_at = draft["createdAtEpochMs"] + 1
    proof = evidence(draft, assessed_at)
    assessment = assess_private_action_draft(
        draft=draft, preview=action, challenge=gate,
        acknowledgement_receipt=receipt, idempotency_key="confirm_handoff",
        principal_ref=PRINCIPAL, actor_user_id=ACTOR_USER_ID,
        evidence=proof, assessed_at_epoch_ms=assessed_at)
    reservation = build_action_reservation_request(
        draft=draft, assessment=assessment,
        requested_at_epoch_ms=assessed_at + 1,
        expires_at_epoch_ms=min(assessed_at + 10_000, draft["quoteExpiresAtEpochMs"]))
    return {"reservation": reservation, "draft": draft,
            "assessment": assessment, "order": order}


@pytest.mark.parametrize("side,table,kind", [
    ("BUY_CRYPTO", "orders", "BUY_ORDER"),
    ("SELL_CRYPTO", "sell_orders", "SELL_ORDER"),
])
def test_reservation_and_order_are_one_transaction_with_exact_replay(side, table, kind):
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "handoff.db"); schema(path)
        args, store = build(side), SQLiteE4ActionHandoffStore(path)
        created = store.handoff(**args)
        assert created == {"action": "created", "result_kind": kind, "result_id": 1}
        assert store.handoff(**copy.deepcopy(args)) == {
            "action": "replayed", "result_kind": kind, "result_id": 1}
        with sqlite3.connect(path) as conn:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1
            assert conn.execute("SELECT state,result_kind,result_id FROM "
                                "e4_action_reservations").fetchone() == ("committed", kind, 1)


@pytest.mark.parametrize("fault_name", ["fault_after_order", "fault_before_commit"])
def test_fault_rolls_back_both_reservation_and_order(fault_name):
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "handoff.db"); schema(path)
        def fail(): raise RuntimeError("injected")
        store = SQLiteE4ActionHandoffStore(path, **{fault_name: fail})
        with pytest.raises(RuntimeError): store.handoff(**build())
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM e4_action_reservations").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0


def test_parallel_handoff_has_one_order_and_one_replay():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "handoff.db"); schema(path)
        args, barrier, results = build(), threading.Barrier(2), []
        def worker():
            barrier.wait(); results.append(SQLiteE4ActionHandoffStore(path).handoff(**args))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert sorted(item["action"] for item in results) == ["created", "replayed"]
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1


def test_actor_amount_destination_or_payload_drift_fails_before_transaction():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "handoff.db"); schema(path)
        for field, value in (("user_id", 8), ("rub_amount", "9999"),
                             ("destination", "other")):
            args = build(); args["order"][field] = value
            with pytest.raises(ValueError): SQLiteE4ActionHandoffStore(path).handoff(**args)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM e4_action_reservations").fetchone()[0] == 0


def test_handoff_store_has_no_provider_network_payout_or_generic_callback_surface():
    source = (ROOT / "relay/repositories/e4_action_handoff_store.py").read_text()
    for forbidden in ("requests", "httpx", "aiohttp", "socket", "send_crypto",
                      "provider.create", "callback("):
        assert forbidden not in source
