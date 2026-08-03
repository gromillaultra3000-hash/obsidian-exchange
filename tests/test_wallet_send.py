#!/usr/bin/env python3
"""Тесты подготовки перевода из подключённого кошелька (core.wallet_send).

Три вещи, ради которых набор написан:
  1. Получателя, сумму и метку задаёт СЕРВЕР по заявке. Из запроса приходит
     только номер заявки, и он проверяется на принадлежность — иначе Mini App
     превращается в кнопку «отправь куда скажут» от нашего имени.
  2. Комментарий собирается вручную (библиотек TON в окружении нет), поэтому
     BOC разбирается обратно и сверяется побайтово. Ошибка в раскладке даёт не
     «подписалось не то», а отказ кошелька, который пришлось бы разбирать по
     скриншоту клиента.
  3. Подпись в кошельке — не поступление денег: `mark_signed` ставит отметку
     времени и НИЧЕГО не решает про заявку.

Запуск: python3 tests/test_wallet_send.py
"""
import base64
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["DB_PATH"] = _db_path
os.environ["RELAY_SECRET"] = "test-secret-for-marker"

from core import wallet_send as WS      # noqa: E402
from core import wallet_link as WL      # noqa: E402

WL.DB_PATH = _db_path
WS.DB_PATH = _db_path

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


def setup_db():
    conn = sqlite3.connect(_db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS sell_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, currency TEXT,
        crypto_amount REAL, rub_amount REAL, sbp_phone TEXT, receive_address TEXT,
        status TEXT, tx_hash TEXT, created_at TEXT, updated_at TEXT)""")
    conn.commit()
    conn.close()


def add_sell(user_id, currency, amount, address, status="pending"):
    conn = sqlite3.connect(_db_path)
    cur = conn.execute(
        "INSERT INTO sell_orders (user_id, currency, crypto_amount, rub_amount,"
        " sbp_phone, receive_address, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        (user_id, currency, amount, amount * 250, "79001234567", address, status))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


setup_db()

# Адреса строим тем же кодером, что и прод: выдуманная «похожая» строка не
# проходит контрольную сумму — и правильно, что не проходит.
from core.address import ton_friendly_address  # noqa: E402

OUR = ton_friendly_address("0:" + "ab" * 32)
CLIENT = ton_friendly_address("0:" + "cd" * 32)

# ── CRC32C: проверочное значение полинома Castagnoli ─────────────────────────
# Не zlib.crc32 — другой полином. Спутать их = собрать BOC, который кошелёк
# отвергнет; поймать это без вектора нечем.
check("crc32c(\"123456789\") == 0xE3069283", WS.crc32c(b"123456789") == 0xE3069283)
check("crc32c пустой строки == 0", WS.crc32c(b"") == 0)
check("crc32c отличается от zlib.crc32", WS.crc32c(b"123456789") != __import__("zlib").crc32(b"123456789"))


# ── BOC комментария: разбираем обратно ───────────────────────────────────────
def decode_comment_boc(b64):
    """Минимальный разборщик ровно нашего случая: одна ячейка без ссылок."""
    raw = base64.b64decode(b64)
    assert raw[:4] == b"\xb5\xee\x9c\x72", "не та магия BOC"
    flags = raw[4]
    has_crc = bool(flags & 0x40)
    size = flags & 0x07
    assert size == 1, f"размер индекса {size}"
    off_bytes = raw[5]
    assert off_bytes == 1, f"байт смещения {off_bytes}"
    cells, roots, absent = raw[6], raw[7], raw[8]
    tot = raw[9]
    root_idx = raw[10]
    body = raw[11:11 + tot]
    if has_crc:
        tail = raw[11 + tot:]
        assert len(tail) == 4, "нет контрольной суммы"
        assert int.from_bytes(tail, "little") == WS.crc32c(raw[:11 + tot]), "crc32c не сошлась"
    d1, d2 = body[0], body[1]
    data = body[2:]
    return {"cells": cells, "roots": roots, "absent": absent, "root_idx": root_idx,
            "refs": d1 & 0x07, "exotic": bool(d1 & 0x08), "data_bytes": d2,
            "op": int.from_bytes(data[:4], "big"),
            "text": data[4:].decode("utf-8"), "raw_len": len(raw)}


d = decode_comment_boc(WS.text_comment_boc("OE-123"))
check("BOC: одна ячейка, один корень", d["cells"] == 1 and d["roots"] == 1 and d["absent"] == 0)
check("BOC: корень с индексом 0", d["root_idx"] == 0)
check("BOC: ссылок нет, ячейка обычная", d["refs"] == 0 and not d["exotic"])
check("BOC: код операции 0 = текстовый комментарий", d["op"] == 0)
check("BOC: текст восстановился", d["text"] == "OE-123")
check("BOC: длина данных = 2×байт (данные выровнены)", d["data_bytes"] == 2 * (4 + len(b"OE-123")))

d2 = decode_comment_boc(WS.text_comment_boc("OE-9-абв"))
check("BOC: кириллица переживает round-trip", d2["text"] == "OE-9-абв")
check("BOC: длина считается в БАЙТАХ, а не в символах",
      d2["data_bytes"] == 2 * (4 + len("OE-9-абв".encode("utf-8"))))

# Реальные BOC начинаются с «te6cck» — это те же байты b5ee9c72 41 в base64.
# Внешний признак того, что заголовок собран как у всех, а не «как получилось».
check("BOC узнаваем снаружи (te6cck…)", WS.text_comment_boc("OE-1").startswith("te6cck"))

try:
    WS.text_comment_boc("x" * (WS.COMMENT_MAX_BYTES + 1))
    too_long_ok = False
except ValueError:
    too_long_ok = True
check("слишком длинная метка — отказ, а не порча ячейки", too_long_ok)

# ── метка платежа ────────────────────────────────────────────────────────────
m = WS.marker_for(77)
check("метка детерминирована", m == WS.marker_for(77))
check("метка содержит номер заявки", m.startswith("OE-77"))
check("метка разных заявок различается", WS.marker_for(77) != WS.marker_for(78))
check("метка помечена подписью при заданном RELAY_SECRET", len(m) > len("OE-77"))
check("мусорный номер метки не даёт", WS.marker_for("abc") == "" and WS.marker_for(0) == "")
check("совпадение метки — по своей заявке", WS.comment_matches(f"платёж {m}", 77))
check("чужая метка не подходит", not WS.comment_matches(WS.marker_for(78), 77))

# Метка ищется как целый токен: «OE-12» лежит внутри «OE-123», и подстрочное
# сравнение привязало бы депозит одной заявки к другой — рубли ушли бы не тому
# клиенту. Нашёл codex; проверяем в обе стороны и без подписи тоже.
_secret_backup = os.environ.pop("RELAY_SECRET", None)
check("без RELAY_SECRET метка короткая", WS.marker_for(12) == "OE-12")
check("метка №12 не находится внутри метки №123",
      not WS.comment_matches(WS.marker_for(123), 12))
check("метка №123 не находится внутри метки №12",
      not WS.comment_matches(WS.marker_for(12), 123))
check("своя метка по-прежнему находится", WS.comment_matches("оплата OE-12", 12))
check("метка находится в конце строки", WS.comment_matches("заявка OE-12", 12))
check("метка находится в скобках", WS.comment_matches("платёж (OE-12)", 12))
if _secret_backup is not None:
    os.environ["RELAY_SECRET"] = _secret_backup
check("пустой комментарий не подходит", not WS.comment_matches("", 77))
check("метка без подписи не выдаётся за подписанную",
      not WS.comment_matches("OE-77", 77) or WS.marker_for(77) == "OE-77")

# ── нанотоны ─────────────────────────────────────────────────────────────────
check("1 TON = 10^9 нанотон", WS.to_nano(1) == 10 ** 9)
check("дробная сумма без плавающей ошибки", WS.to_nano("0.1") == 100_000_000)
check("0.000000001 — минимальная единица", WS.to_nano(0.000000001) == 1)
check("ноль не отправляем", WS.to_nano(0) is None)
check("отрицательное не отправляем", WS.to_nano(-5) is None)
check("мусор не отправляем", WS.to_nano("abc") is None)
# 5.7 в float — 5.700000000000000177…; наивное умножение дало бы 5699999999
check("5.7 TON не теряет нанотоны", WS.to_nano(5.7) == 5_700_000_000)

# ── подготовка перевода: владение и состояние заявки ─────────────────────────
UID, OTHER = 555001, 555002
sid = add_sell(UID, "TON", 5.5, OUR)

r = WS.build_request(UID, sid)
check("без подключённого кошелька перевод не готовится", not r["ok"] and r["reason"] == "not_connected")

WL.remember(UID, "TON", CLIENT)
r = WS.build_request(UID, sid)
check("с подключённым кошельком запрос готов", r["ok"])
check("получатель — адрес ИЗ ЗАЯВКИ", r["request"]["messages"][0]["address"] == OUR)
check("сумма — из заявки, в нанотонах строкой",
      r["request"]["messages"][0]["amount"] == str(5_500_000_000))
check("сеть указана основная", r["request"]["network"] == WS.MAINNET)
check("срок жизни запроса конечен",
      r["request"]["validUntil"] > 0 and r["request"]["validUntil"] < __import__("time").time() + 3600)
check("метка вложена в перевод",
      decode_comment_boc(r["request"]["messages"][0]["payload"])["text"] == WS.marker_for(sid))
check("отправитель — доказанный адрес клиента", r["from_address"] == CLIENT)

# Ответ про чужую заявку обязан совпадать с ответом про несуществующую ЦЕЛИКОМ:
# отдельный код отказа ушёл бы клиенту и перебором номеров выдал бы, какие
# заявки живут.
check("чужая заявка неотличима от несуществующей",
      WS.build_request(OTHER, sid) == WS.build_request(OTHER, 999999))
check("чужую заявку не готовим", not WS.build_request(OTHER, sid)["ok"])

sid_btc = add_sell(UID, "BTC", 0.01, "bc1qexample")
check("не-TON заявку кошелёк TON не оплачивает",
      WS.build_request(UID, sid_btc)["reason"] == "wrong_currency")

sid_paid = add_sell(UID, "TON", 5.5, OUR, status="paid")
check("оплаченную заявку второй раз не платим",
      WS.build_request(UID, sid_paid)["reason"] == "not_pending")

sid_noaddr = add_sell(UID, "TON", 5.5, "")
check("заявка без адреса приёма — отказ",
      WS.build_request(UID, sid_noaddr)["reason"] == "no_address")

sid_badaddr = add_sell(UID, "TON", 5.5, "не-адрес-вовсе")
check("испорченный адрес приёма — отказ, а не перевод в никуда",
      WS.build_request(UID, sid_badaddr)["reason"] == "bad_address")

sid_zero = add_sell(UID, "TON", 0, OUR)
check("нулевая сумма — отказ", WS.build_request(UID, sid_zero)["reason"] == "bad_amount")

check("отказ всегда с человеческим текстом",
      all(WS.build_request(OTHER, s)["message"] for s in (sid, sid_btc, sid_paid)))

# Ключей у модуля нет и быть не может: он не подписывает, а собирает запрос.
src = open(os.path.join(ROOT, "relay", "core", "wallet_send.py"), encoding="utf-8").read()
check("модуль не читает секретных ключей",
      "PRIVATE" not in src.upper() and "mnemonic" not in src.lower() and "seed" not in src.lower())
check("модуль не умеет подписывать", "sign(" not in src and "Ed25519" not in src)

# ── намерение и отметка подписи ──────────────────────────────────────────────
check("намерение записано ДО подписи", CLIENT in WS.senders_for_order(sid))
check("намерение чужой заявки не появилось", not WS.senders_for_order(sid_btc))
intents = WS.intents_for_order(sid)
check("в намерении сохранена метка", intents and intents[0]["marker"] == WS.marker_for(sid))
check("до подписи отметки нет", intents and intents[0]["signed_at"] is None)

check("отметка подписи ставится", WS.mark_signed(UID, sid))
check("повторная отметка не дублируется", not WS.mark_signed(UID, sid))
check("после отметки время проставлено", WS.intents_for_order(sid)[0]["signed_at"])

# Главное: отметка подписи НЕ трогает заявку — деньги подтверждает только сеть.
conn = sqlite3.connect(_db_path)
status = conn.execute("SELECT status FROM sell_orders WHERE id=?", (sid,)).fetchone()[0]
conn.close()
check("подпись в кошельке НЕ переводит заявку в оплаченную", status == "pending")
check("чужую заявку подписью не отметить", not WS.mark_signed(OTHER, sid))

# ── список ждущих перевода ───────────────────────────────────────────────────
dues = WS.pending_sells(UID)
ids = {d["sell_id"] for d in dues}
check("в списке — только заявки клиента", ids and all(
    d["sell_id"] in (sid, sid_noaddr, sid_badaddr, sid_zero) for d in dues))
check("оплаченной заявки в списке нет", sid_paid not in ids)
check("чужих заявок в списке нет", not WS.pending_sells(OTHER))
check("не-TON заявки в списке нет", sid_btc not in ids)
check("у каждой строки есть метка", all(d["marker"] for d in dues))

# Сбой базы не должен выглядеть как «ничего не ждёт перевода»… но и падать не
# должен: список — вспомогательная поверхность, а не решение о деньгах.
WS.DB_PATH = "/nonexistent/dir/x.db"
check("недоступная база не роняет список", WS.pending_sells(UID) == [])
check("недоступная база не готовит перевод", not WS.build_request(UID, sid)["ok"])
WS.DB_PATH = _db_path

os.unlink(_db_path)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
