#!/usr/bin/env python3
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))
from core import payout_intents as pi

failures = []


def check(name, condition):
    print(("✅ " if condition else "❌ ") + name)
    if not condition:
        failures.append(name)


with tempfile.TemporaryDirectory() as td:
    path = os.path.join(td, "intents.db")
    a = sqlite3.connect(path, timeout=5, isolation_level=None)
    b = sqlite3.connect(path, timeout=5, isolation_level=None)
    values = dict(order_id=71, rub_amount=5000, crypto_amount=0.00123456,
                  currency="btc", network=None, destination="bc1qexample",
                  source="auto", requested_by="exchange-bot")

    first = pi.create(a, **values)
    again = pi.create(b, **values)
    check("одна заявка создаёт один intent", first["id"] == again["id"])
    check("idempotency key детерминирован по order", first["idempotency_key"] == "payout_71")

    try:
        pi.create(b, **{**values, "destination": "bc1qchanged"})
        mismatch_rejected = False
    except ValueError as exc:
        mismatch_rejected = str(exc) == "payout_intent_payload_mismatch"
    check("payload существующего intent нельзя изменить", mismatch_rejected)

    claimed_a = pi.claim(a, 71)
    claimed_b = pi.claim(b, 71)
    check("атомарный claim достаётся только одному исполнителю",
          claimed_a is not None and claimed_b is None)
    check("claim увеличивает attempts ровно один раз", pi.get(a, 71)["attempts"] == 1)
    check("успех требует processing и сохраняет txid", pi.succeed(a, 71, "tx-71"))
    check("успешный intent не claim'ится повторно", pi.claim(b, 71) is None)
    check("терминальное состояние и txid сохранены",
          pi.get(b, 71)["state"] == "succeeded" and pi.get(b, 71)["txid"] == "tx-71")

    review_values = {**values, "order_id": 72, "destination": "bc1qreview"}
    pi.create(a, **review_values)
    pi.claim(a, 72)
    check("неопределённый исход переводится в review", pi.review(a, 72, "RuntimeError"))
    check("review никогда не повторяется автоматически", pi.claim(b, 72) is None)
    check("в error_code нет сырого текста исключения",
          pi.get(a, 72)["error_code"] == "RuntimeError")
    a.close()
    b.close()

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
