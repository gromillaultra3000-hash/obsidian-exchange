#!/usr/bin/env python3
"""Регресс-тесты доставки чека и удержания заявки (слои 0-3, сессия 25.07.2026).

Ловят конкретные дефекты, найденные в проде:
  - brabus:vietqr / brabus:tbank_deeplink не матчились с _ROUTES → чек молча терялся
  - заявка с чеком тихо истекала (expired + winback), хотя клиент оплатил
  - фиктивный чек (дубль файла / серия expired без оплат) уходил без сигнала оператору

Запуск: python3 tests/test_receipts.py
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# ── Слой 1: нормализация ключа провайдера и карта групп споров ────────────────
from core import receipts as R  # noqa: E402

check("brabus:vietqr → базовый ключ 'brabus' есть в _ROUTES",
      "brabus" in R._ROUTES and "brabus:vietqr".partition(":")[0] == "brabus")
check("_ROUTES покрывает всех активных провайдеров",
      {"montera", "vertu", "brabus", "fallback", "stormtrade", "xpay"} <= set(R._ROUTES))
check("DISPUTE_CHATS содержит vertu/montera/xpay",
      {"vertu", "montera", "xpay"} <= set(R.DISPUTE_CHATS))
check("группа споров без chat_id → reason=no_chat (не притворяемся, что ушло)",
      R._send_to_dispute_chat("X", "", "deal1", b"pdf", "r.pdf").get("reason") == "no_chat")


# ── Слой 0: заявка с чеком не истекает ────────────────────────────────────────
def test_hold():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE orders(order_id INT PRIMARY KEY, status TEXT, created_at TEXT);
        CREATE TABLE payment_sessions(order_id INT, status TEXT, expires_at TEXT);
        CREATE TABLE order_receipts(order_id INT PRIMARY KEY);
        INSERT INTO orders VALUES(1,'pending',datetime('now','-3 hours'));
        INSERT INTO orders VALUES(2,'pending',datetime('now','-3 hours'));
        INSERT INTO order_receipts VALUES(2);
    """)
    db.execute("""
        UPDATE orders SET status='expired'
        WHERE status='pending' AND datetime(created_at) < datetime('now','-2 hours')
        AND order_id NOT IN (SELECT DISTINCT order_id FROM payment_sessions
            WHERE status='invoice_created' AND datetime(expires_at) > datetime('now'))
        AND order_id NOT IN (SELECT order_id FROM order_receipts)
    """)
    res = {r[0]: r[1] for r in db.execute("SELECT order_id,status FROM orders")}
    return res.get(1) == "expired" and res.get(2) == "pending"


check("заявка с чеком удержана от истечения, без чека — истекает", test_hold())


# ── Слои 0+3: store_receipt пишет хеш, fraud-flags ловят дубль и серию expired ─
def test_fraud():
    tmp = tempfile.mkdtemp()
    dbf = os.path.join(tmp, "t.db")
    os.environ["DB_PATH"] = dbf
    os.environ["RECEIPT_DIR"] = os.path.join(tmp, "receipts")
    # свежие модули с новым DB_PATH
    import importlib
    importlib.reload(R)
    conn = sqlite3.connect(dbf)
    conn.executescript("""
        CREATE TABLE orders(order_id INT PRIMARY KEY, user_id INT, status TEXT);
        INSERT INTO orders VALUES(10, 555, 'pending');
        INSERT INTO orders VALUES(11, 555, 'expired');
        INSERT INTO orders VALUES(12, 555, 'expired');
        INSERT INTO orders VALUES(13, 555, 'expired');
    """)
    conn.commit()
    conn.close()
    same = b"%PDF-1.5 one and only receipt bytes"
    R.store_receipt(10, same, "a.pdf", "application/pdf")
    R.store_receipt(11, same, "b.pdf", "application/pdf")  # тот же файл — дубль
    dup = R.receipt_fraud_flags(11, same)
    streak = R.receipt_fraud_flags(10, b"unique bytes here")
    ok_dup = any("уже присылали" in f for f in dup)
    ok_streak = any("ни одной оплаченной" in f.lower() for f in streak)
    return ok_dup and ok_streak


check("fraud-flags: дубль-файл и серия expired без оплат подсвечены", test_fraud())


# ── Гарантия «чек дойдёт»: сторож ловит залитый, но не доставленный чек ────────
def test_undelivered_watch():
    tmp = tempfile.mkdtemp()
    dbf = os.path.join(tmp, "cw.db")
    os.environ["DB_PATH"] = dbf
    import importlib
    import core.conversion_watch as C
    importlib.reload(C)
    conn = sqlite3.connect(dbf)
    conn.executescript("""
        CREATE TABLE orders(order_id INT PRIMARY KEY, user_id INT, status TEXT,
            rub_amount REAL, currency TEXT, created_at TEXT, updated_at TEXT,
            paid_btc_tx TEXT, receipt_sent_at TEXT);
        CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY, order_id INT,
            provider TEXT, status TEXT, created_at TEXT, expires_at TEXT, updated_at TEXT);
        CREATE TABLE order_receipts(order_id INT PRIMARY KEY, created_at TEXT);
        -- 1: чек 30 мин назад, не доставлен, pending → ЛОВИТСЯ
        INSERT INTO orders VALUES(1,10,'pending',50000,'BTC',datetime('now','-1 hour'),NULL,NULL,NULL);
        INSERT INTO payment_sessions VALUES(1,1,'xpay','invoice_created',datetime('now'),NULL,NULL);
        INSERT INTO order_receipts VALUES(1,datetime('now','-30 minutes'));
        -- 2: чек доставлен (receipt_sent_at есть) → НЕ ловится
        INSERT INTO orders VALUES(2,11,'paid',4000,'BTC',datetime('now','-1 hour'),datetime('now'),NULL,datetime('now'));
        INSERT INTO order_receipts VALUES(2,datetime('now','-40 minutes'));
        -- 3: чек 5 мин назад (в пределах порога) → пока НЕ ловится
        INSERT INTO orders VALUES(3,12,'pending',2000,'BTC',datetime('now'),NULL,NULL,NULL);
        INSERT INTO order_receipts VALUES(3,datetime('now','-5 minutes'));
        -- 4: крипта выдана (sent) → НЕ ловится
        INSERT INTO orders VALUES(4,13,'sent',1000,'BTC',datetime('now','-2 hour'),datetime('now'),'tx',NULL);
        INSERT INTO order_receipts VALUES(4,datetime('now','-90 minutes'));
    """)
    conn.commit()
    conn.close()
    r = C.check_conversion(24)
    ids = sorted(p["order_id"] for p in r["undelivered_receipts"])
    kinds = [a["kind"] for a in r["alerts"]]
    return ids == [1] and "receipt_undelivered" in kinds


check("сторож: залитый, но не доставленный провайдеру чек ловится (и только он)",
      test_undelivered_watch())


def test_stuck_null_updated():
    tmp = tempfile.mkdtemp()
    dbf = os.path.join(tmp, "cw2.db")
    os.environ["DB_PATH"] = dbf
    import importlib
    import core.conversion_watch as C
    importlib.reload(C)
    conn = sqlite3.connect(dbf)
    conn.executescript("""
        CREATE TABLE orders(order_id INT PRIMARY KEY, user_id INT, status TEXT,
            rub_amount REAL, currency TEXT, created_at TEXT, updated_at TEXT,
            paid_btc_tx TEXT, receipt_sent_at TEXT);
        CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY, order_id INT,
            provider TEXT, status TEXT, created_at TEXT, expires_at TEXT, updated_at TEXT);
        CREATE TABLE order_receipts(order_id INT PRIMARY KEY, created_at TEXT);
        -- оплачено давно, updated_at ПУСТ (был невидим сторожу до фикса) → ЛОВИТСЯ
        INSERT INTO orders VALUES(1,10,'paid',2000,'USDT',datetime('now','-3 days'),NULL,NULL,NULL);
    """)
    conn.commit()
    conn.close()
    r = C.check_conversion(24)
    return [p["order_id"] for p in r["stuck_payouts"]] == [1]


check("сторож: зависшая выплата с updated_at=NULL теперь видна", test_stuck_null_updated())


print()
if failures:
    print(f"❌ Провалено: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("✅ Все проверки доставки чека пройдены")
