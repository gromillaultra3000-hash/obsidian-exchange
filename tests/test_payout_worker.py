#!/usr/bin/env python3
import importlib.util
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))
from core import payout_intents as pi, referral_payout_intents as rpi

spec = importlib.util.spec_from_file_location(
    "payout_worker", os.path.join(ROOT, "payment", "payout_worker.py"))
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)

failures = []


def check(name, condition):
    print(("✅ " if condition else "❌ ") + name)
    if not condition:
        failures.append(name)


def add(conn, oid):
    return pi.create(conn, order_id=oid, rub_amount=1000,
                     crypto_amount=0.0001, currency="BTC", network=None,
                     destination=f"test-destination-{oid}", source="test")


with tempfile.TemporaryDirectory() as td:
    worker.DB_PATH = os.path.join(td, "worker.db")
    with sqlite3.connect(worker.DB_PATH) as conn:
        add(conn, 101)
        conn.commit()

    seen = []
    result = worker.run_once(lambda intent: seen.append(intent["order_id"]) or "tx-101")
    check("worker claim'ит и завершает один intent", result["action"] == "succeeded")
    with sqlite3.connect(worker.DB_PATH) as conn:
        row = pi.get(conn, 101)
    check("worker сохраняет succeeded и TXID",
          row["state"] == "succeeded" and row["txid"] == "tx-101")
    check("signer вызван ровно один раз", seen == [101])
    check("готовый intent повторно не исполняется", worker.run_once(lambda _: "bad")["action"] == "idle")

    with sqlite3.connect(worker.DB_PATH) as conn:
        add(conn, 102)
        conn.commit()
    result = worker.run_once(lambda _intent: (_ for _ in ()).throw(RuntimeError("secret detail")))
    with sqlite3.connect(worker.DB_PATH) as conn:
        review = pi.get(conn, 102)
    check("ошибка signer'а ведёт в review", result["action"] == "review" and review["state"] == "review")
    check("в БД хранится только класс ошибки", review["error_code"] == "RuntimeError")
    check("review не исполняется повторно", worker.run_once(lambda _: "bad")["action"] == "idle")

    with sqlite3.connect(worker.DB_PATH) as conn:
        conn.execute("CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,"
                     "total_bonus_btc REAL,bonus_paid INTEGER DEFAULT 0)")
        conn.execute("INSERT INTO referrals VALUES(7,8,.0002,0)")
        referral = rpi.create(conn, user_id=7, destination="ref-destination",
                              minimum_btc=.00001)
        conn.commit()
    result = worker.run_once(lambda intent: "tx-ref" if intent["intent_type"] == "referral" else "bad")
    check("worker обрабатывает отдельный referral intent",
          result["action"] == "succeeded" and result["intent_type"] == "referral")
    with sqlite3.connect(worker.DB_PATH) as conn:
        state = conn.execute("SELECT state,txid FROM referral_payout_intents WHERE id=?",
                             (referral["id"],)).fetchone()
    check("referral TXID сохраняется", state == ("succeeded", "tx-ref"))

old_flag = os.environ.pop("PAYOUT_WORKER_ENABLED", None)
try:
    check("worker без явного enable завершается fail-closed", worker.main() == 78)
finally:
    if old_flag is not None:
        os.environ["PAYOUT_WORKER_ENABLED"] = old_flag

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
