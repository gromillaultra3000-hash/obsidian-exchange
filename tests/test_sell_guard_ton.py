#!/usr/bin/env python3
"""Страж продажи, ветка TON: депозит засчитывается только привязанный.

Адрес приёма один на всех заявках, поэтому «пришла нужная сумма» — не
доказательство оплаты именно этой заявки. У TON есть два признака привязки:
метка в комментарии перевода и адрес отправителя, доказанный подписью при
подключении кошелька. Набор проверяет, что без них рубли не уходят, а перевод
уходит человеку с отдельным вердиктом, а не молча пропадает.

Отдельно проверяется ловушка сравнения: обозреватель отдаёт отправителя в виде
`0:…`, а подпись подключения дала дружественный `UQ…`. Сравнение строк здесь не
«иногда ошибётся» — оно не совпадёт никогда.

Запуск: python3 tests/test_sell_guard_ton.py
"""
import os
import sqlite3
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))
sys.path.insert(0, os.path.join(ROOT, "bot"))

_fd, _db = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["DB_PATH"] = _db
os.environ["RELAY_SECRET"] = "test-secret-for-marker"

import sell_guard as SG                     # noqa: E402
from core import wallet_send as WS          # noqa: E402
from core.address import ton_friendly_address  # noqa: E402

SG.DB_PATH = _db
WS.DB_PATH = _db

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


OUR = ton_friendly_address("0:" + "ab" * 32)
CLIENT_RAW = "0:" + "cd" * 32
CLIENT_FRIENDLY = ton_friendly_address(CLIENT_RAW)
STRANGER_RAW = "0:" + "ef" * 32

conn = sqlite3.connect(_db)
conn.execute("""CREATE TABLE sell_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, currency TEXT,
    crypto_amount REAL, rub_amount REAL, sbp_phone TEXT, receive_address TEXT,
    status TEXT, tx_hash TEXT, created_at TEXT, updated_at TEXT)""")
conn.execute("""CREATE TABLE wallet_send_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    chain TEXT NOT NULL, sell_id INTEGER NOT NULL, from_address TEXT NOT NULL,
    to_address TEXT NOT NULL, amount REAL NOT NULL, marker TEXT NOT NULL,
    created_at TEXT NOT NULL, signed_at TEXT)""")
conn.commit()
conn.close()


def add_sell(amount=5.0, currency="TON", address=OUR):
    c = sqlite3.connect(_db)
    cur = c.execute(
        "INSERT INTO sell_orders (user_id, currency, crypto_amount, rub_amount,"
        " sbp_phone, receive_address, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,'pending',datetime('now'),datetime('now'))",
        (42, currency, amount, amount * 250, "79001234567", address))
    c.commit()
    sid = cur.lastrowid
    c.close()
    return sid


def tx_hash_of(sell_id):
    c = sqlite3.connect(_db)
    v = c.execute("SELECT tx_hash FROM sell_orders WHERE id=?", (sell_id,)).fetchone()[0]
    c.close()
    return v


_real_import = SG._relay_import
_fake_history = {"items": [], "status": "OK", "reason": None}


def _patched_import(module, name):
    if (module, name) == ("wallet.ton_wallet", "history"):
        return lambda addr, limit=20: _fake_history
    return _real_import(module, name)


SG._relay_import = _patched_import


def chain(*items):
    global _fake_history
    _fake_history = {"items": list(items), "status": "OK", "reason": None}


def deposit(amount, *, comment="", source=STRANGER_RAW, age=600, txid="tx-1", failed=False):
    return {"direction": "in", "amount": amount, "counterparty": source,
            "comment": comment, "ts": int(time.time()) - age, "txid": txid, "fee": 0.001,
            "failed": failed}


# ── 1. Перевод с меткой заявки ───────────────────────────────────────────────
sid = add_sell(5.0)
chain(deposit(5.0, comment=f"перевод {WS.marker_for(sid)}", txid="tx-marker"))
r = SG.verify_sell_deposit(sid)
check("перевод с меткой заявки подтверждается", r["verdict"] == "confirmed")
check("txid закреплён за заявкой", tx_hash_of(sid) == "tx-marker")

# ── 2. Тот же перевод без метки и от постороннего ────────────────────────────
sid2 = add_sell(5.0)
chain(deposit(5.0, txid="tx-plain"))
r = SG.verify_sell_deposit(sid2)
check("нужная сумма без привязки НЕ подтверждается", r["verdict"] != "confirmed")
check("непривязанный перевод получает свой вердикт", r["verdict"] == "unbound")
check("вердикт объясняет, чего не хватило", "метк" in r["reason"])
check("непривязанный перевод не закрепляется за заявкой", not tx_hash_of(sid2))
check("вердикт описан человеческим текстом",
      "не привязан" in SG.describe_verdict(r, "TON").lower())

# ── 3. Перевод от доказанного отправителя, но без метки ──────────────────────
# Ровно тот случай, ради которого пишется намерение: клиент подписал в кошельке,
# комментарий по дороге потерялся (кошелёк, обменник, ручная отправка).
sid3 = add_sell(5.0)
WS.remember_intent(42, sid3, CLIENT_FRIENDLY, OUR, 5.0, WS.marker_for(sid3))
chain(deposit(5.0, source=CLIENT_RAW, txid="tx-sender"))
r = SG.verify_sell_deposit(sid3)
check("перевод с доказанного счёта подтверждается без метки", r["verdict"] == "confirmed")
# Та самая ловушка: если сравнивать строки, «0:cdcd…» и «UQ…» не совпадут никогда.
check("формы записи одного счёта не различаются",
      CLIENT_RAW != CLIENT_FRIENDLY and WS.same_account(CLIENT_RAW, CLIENT_FRIENDLY))
check("чужой счёт не выдаётся за доказанный",
      not WS.same_account(STRANGER_RAW, CLIENT_FRIENDLY))

# Намерение другой заявки не годится этой
sid4 = add_sell(5.0)
chain(deposit(5.0, source=CLIENT_RAW, txid="tx-other-intent"))
check("намерение по другой заявке не привязывает перевод",
      SG.verify_sell_deposit(sid4)["verdict"] == "unbound")

# ── 4. Свежий перевод: подтверждений ещё нет ─────────────────────────────────
sid5 = add_sell(5.0)
chain(deposit(5.0, comment=WS.marker_for(sid5), age=5, txid="tx-fresh"))
r = SG.verify_sell_deposit(sid5)
check("свежий перевод — ждём сеть, а не платим", r["verdict"] == "pending")
check("свежий перевод не закрепляется за заявкой", not tx_hash_of(sid5))

# ── 5. Сумма вне окна ────────────────────────────────────────────────────────
sid6 = add_sell(5.0)
chain(deposit(0.5, comment=WS.marker_for(sid6), txid="tx-small"))
check("недостача с меткой — решает человек",
      SG.verify_sell_deposit(sid6)["verdict"] == "amount_mismatch")

# ── 6. Обозреватель недоступен ───────────────────────────────────────────────
sid7 = add_sell(5.0)
_fake_history = {"items": [], "status": "ERROR", "reason": "Timeout"}
r = SG.verify_sell_deposit(sid7)
check("недоступный обозреватель — не «денег нет», а «не смогли спросить»",
      r["verdict"] == "unavailable")
check("причина недоступности видна", "toncenter" in r["reason"].lower())

_fake_history = {"items": [], "status": "OK", "reason": None}
check("пустая история — честное «не поступало»",
      SG.verify_sell_deposit(sid7)["verdict"] == "not_found")

# ── 7. Один депозит не оплачивает две заявки ─────────────────────────────────
sid8 = add_sell(5.0)
chain(deposit(5.0, comment=WS.marker_for(sid8), txid="tx-marker"))   # уже за sid
check("txid, закреплённый за другой заявкой, повторно не засчитывается",
      SG.verify_sell_deposit(sid8)["verdict"] == "not_found")

# ── 8. Исходящие переводы не считаются приходом ──────────────────────────────
sid9 = add_sell(5.0)
_fake_history = {"items": [dict(deposit(5.0, comment=WS.marker_for(sid9), txid="tx-out"),
                                direction="out")], "status": "OK", "reason": None}
check("исходящий перевод не выдаётся за депозит",
      SG.verify_sell_deposit(sid9)["verdict"] == "not_found")

# ── 9. Откатившийся перевод — не депозит ─────────────────────────────────────
# Сумма во входящем сообщении положительна, но транзакция завершилась откатом:
# монеты вернулись отправителю. Засчитать её значит выдать рубли за перевод,
# которого нет. Нашёл codex.
sid_ab = add_sell(5.0)
chain(deposit(5.0, comment=WS.marker_for(sid_ab), txid="tx-aborted", failed=True))
check("откатившийся перевод не считается депозитом",
      SG.verify_sell_deposit(sid_ab)["verdict"] == "not_found")
chain(deposit(5.0, comment=WS.marker_for(sid_ab), txid="tx-good"))
check("успешный перевод по той же заявке засчитывается",
      SG.verify_sell_deposit(sid_ab)["verdict"] == "confirmed")

# ── 10. Привязка требуется ТОЛЬКО у TON ──────────────────────────────────────
# У BTC/LTC/USDT признака нет, и вводить его задним числом значило бы объявить
# все прошлые депозиты непривязанными.
src = open(os.path.join(ROOT, "bot", "sell_guard.py"), encoding="utf-8").read()
check("привязка включается по валюте, а не для всех подряд",
      'currency == "TON" else None' in src)

os.unlink(_db)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
