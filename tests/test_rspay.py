#!/usr/bin/env python3
"""RSPay: подпись, разбор реквизитов, статусы, чек, вебхук.

Живого ключа у нас нет, поэтому проверяется то, что от ключа не зависит:
что подписываются ровно отправляемые байты, что штатное «нет реквизитов» не
выглядит сбоем канала, что возврат не считается оплатой и что вебхук без
верной подписи не проходит.
"""
import hashlib
import hmac
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
os.environ.setdefault("RSPAY_SHOP_API_KEY", "shopkey")
os.environ.setdefault("RSPAY_API_SECRET", "s3cret")
os.environ.setdefault("RSPAY_BT_SHOP_API_KEY", "bt-shopkey")
os.environ.setdefault("RSPAY_BT_API_SECRET", "bt-s3cret")
# Счётчики клиента читаются из базы; боевую трогать незачем, а в CI её нет —
# путь в никуда проверяет заодно, что отсутствие базы не срывает платёж.
os.environ["DB_PATH"] = "/tmp/rspay-test-no-such.db"

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


from providers import rspay as R  # noqa: E402
from core import attempt_id  # noqa: E402


# ── подставной requests ───────────────────────────────────────────────────────

class Resp:
    def __init__(self, code=200, payload=None, text=""):
        self.status_code = code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("не JSON")
        return self._payload


class FakeRequests:
    """Запоминает КАЖДЫЙ вызов целиком: тело, заголовки, параметры."""

    def __init__(self):
        self.calls = []
        self.next = []
        # настоящие Request/Session нужны сборке multipart — их не подменяем
        self.Request = __import__("requests").Request
        self.Session = _FakeSession(self)

    def _answer(self):
        return self.next.pop(0) if self.next else Resp(200, {})

    def post(self, url, data=None, headers=None, timeout=None, **kw):
        self.calls.append({"m": "POST", "url": url, "body": data,
                           "headers": headers or {}, "kw": kw})
        return self._answer()

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append({"m": "GET", "url": url, "params": params,
                           "body": b"", "headers": headers or {}})
        return self._answer()


class _FakeSession:
    """Фабрика сессий: `with requests.Session() as s: s.send(prepared)`."""

    def __init__(self, owner):
        self.owner = owner

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send(self, prepared, timeout=None):
        self.owner.calls.append({"m": "SEND", "url": prepared.url,
                                 "body": prepared.body,
                                 "headers": dict(prepared.headers)})
        return self.owner._answer()


def provider(*answers):
    fake = FakeRequests()
    fake.next = list(answers)
    R.requests = fake
    p = R.RSPayProvider()
    p.api_key, p.secret = "shopkey", "s3cret"
    p.bt_api_key, p.bt_secret = "bt-shopkey", "bt-s3cret"
    return p, fake


def expected_sig(body: bytes, secret: bytes = b"s3cret") -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


OK_CARD = {
    "success": True, "ready": True, "status": "available", "payment_method": "card",
    "requisites": {"card_number": "2200153697400076", "bank_name": "Альфа-Банк",
                   "owner_name": "Иван Иванов"},
    "fees": {"total_fee": "128.56"}, "merchant_transaction_id": "order_123",
}

# ── 1. подпись считается от ТЕХ ЖЕ байтов, что уходят ────────────────────────

p, fake = provider(Resp(200, OK_CARD))
p.create_invoice(4242, 8571, payment_method="card", user_id=777)
call = fake.calls[0]
sent = call["body"] if isinstance(call["body"], bytes) else str(call["body"]).encode()
check(call["headers"].get("X-Signature") == expected_sig(sent, b"bt-s3cret"),
      "подпись POST не совпадает с HMAC от отправленного тела — RSPay ответит 401, "
      "а причина будет выглядеть как «неверный ключ»")
check(call["headers"].get("X-Shop-API-Key") == "bt-shopkey",
      "ключ магазина не уходит в X-Shop-API-Key")
ts = call["headers"].get("X-Timestamp", "")
check(ts.isdigit() and len(ts) >= 13,
      f"X-Timestamp={ts!r} не миллисекунды — окно ±5 минут проверяется в мс, "
      f"секунды отвергнутся как устаревшие на 50 лет")
check(len(call["headers"].get("X-Nonce", "")) >= 32,
      "X-Nonce не похож на UUID — RSPay держит nonce 5 минут и повтор не принимает")

# nonce обязан отличаться от запроса к запросу
p2, fake2 = provider(Resp(200, OK_CARD), Resp(200, OK_CARD))
p2.create_invoice(1, 1000, user_id=1)
p2.create_invoice(2, 1000, user_id=1)
check(fake2.calls[0]["headers"]["X-Nonce"] != fake2.calls[1]["headers"]["X-Nonce"],
      "nonce одинаковый у двух запросов — второй уйдёт в 401 как повтор")

# ── 2. GET подписывается пустой строкой ──────────────────────────────────────

p, fake = provider(Resp(200, {"balance_rub": "1500.50", "balance_usdt": "15.005000"}))
check(p.get_balance() == 15.005, "баланс USDT не разобран")
check(fake.calls[0]["headers"]["X-Signature"] == expected_sig(b""),
      "GET подписан не пустой строкой — по доке тела нет, подпись от ''")

# ── 3. реквизиты всех форм ───────────────────────────────────────────────────

p, fake = provider(Resp(200, OK_CARD))
inv = p.create_invoice(4242, 8571, payment_method="card", user_id=777)
check(inv.get("raw", {}).get("requisites", {}).get("card_number") == "2200153697400076",
      "карта не разобрана")
check(inv["raw"]["requisites"].get("recipient") == "Иван Иванов",
      "owner_name не стал получателем — клиент увидит перевод «в никуда»")
check(inv["raw"].get("amount_rub") == 8571.0,
      "суммы нет в raw — страж выплаты останется без сверки и отправит заявку к человеку")
check(attempt_id.parse(inv["invoice_id"]) == "4242",
      "invoice_id не разбирается обратно в номер заявки")

p, fake = provider(Resp(200, {**OK_CARD, "requisites": {
    "phone_number": "+79001234567", "bank_name": "Т-Банк", "owner_name": "Иван Иванов"}}))
inv = p.create_invoice(1, 5000, payment_method="sbp", user_id=1)
check(inv["raw"]["requisites"].get("phone") == "+79001234567", "телефон СБП не разобран")

p, fake = provider(Resp(200, {**OK_CARD, "requisites": {
    "payment_link": "https://qr.nspk.ru/AS10", "qr_data": "BANK0001|SUM2500"}}))
inv = p.create_invoice(1, 2500, payment_method="qr", user_id=1)
check(inv["qr_payload"] == "BANK0001|SUM2500",
      "qr_data не стал payload QR — для внутрибанковых QR это единственный способ "
      "показать код, ссылка ведёт на другую страницу")
check(inv["raw"]["requisites"].get("payment_link") == "https://qr.nspk.ru/AS10",
      "ссылка на оплату потерялась")
check(fake.calls[0]["headers"].get("X-Shop-API-Key") == "shopkey",
      "QR ушёл в БТ-кабинет вместо QR-кабинета")

# форма, которой мы не знаем: показать клиенту пустую карточку нельзя
p, fake = provider(Resp(200, {**OK_CARD, "requisites": {"iban": "RU00"}}))
check("error" in p.create_invoice(1, 1000, user_id=1),
      "неизвестная форма реквизитов принята — клиенту покажут пустую карточку")

# ── 4. «нет реквизитов» — не сбой канала ─────────────────────────────────────

from services.smart_router import is_no_trader_error  # noqa: E402

p, fake = provider(Resp(200, {"success": False, "ready": True, "status": "none",
                              "error": "По выбранному методу оплаты нет реквизитов",
                              "merchant_transaction_id": "order_123"}))
res = p.create_invoice(1, 1000, user_id=1)
check("error" in res, "ответ без реквизитов принят за успех")
check(is_no_trader_error(res["error"]),
      "«нет реквизитов» классифицируется как поломка — RSPay получит штраф здоровья "
      "и выпадет из выбора целиком, хотя канал исправен")

# 409 и 401 объясняются по-человечески
p, fake = provider(Resp(409, {"error": "exists"}))
check("409" in p.create_invoice(1, 1000, user_id=1).get("error", ""),
      "конфликт transaction_id не назван")
p, fake = provider(Resp(401, {"error": "unauthorized"}))
err = p.create_invoice(1, 1000, user_id=1).get("error", "")
check("часы" in err and "nonce" in err,
      "401 отдан как «неверный ключ» — у RSPay это ещё и разъехавшиеся часы и повтор nonce")

# ── 5. поля запроса ──────────────────────────────────────────────────────────

p, fake = provider(Resp(200, OK_CARD))
p.create_invoice(4242, 8571.5, payment_method="card", user_id=777)
body = json.loads(fake.calls[0]["body"].decode())
check(body["currency"] == "RUB" and body["amount"] == "8571.50",
      f"сумма/валюта неверны: {body.get('amount')!r}")
check(body["user"] == "777", "идентификатор клиента не уходит в антифрод RSPay")
check(body["kyc"] is False,
      "kyc=true без телефона плательщика — верификация уйдёт на чужой номер")
check(body.get("receipt") is None,
      "receipt=true по умолчанию: RSPay будет ждать от нас чек, которого не будет")
check(body["callback_url"].endswith("/rspay/webhook"), "callback_url не наш")

os.environ["RSPAY_RECEIPT"] = "1"
p, fake = provider(Resp(200, OK_CARD))
p.create_invoice(1, 1000, payment_method="card", user_id=1)
check(json.loads(fake.calls[0]["body"].decode()).get("receipt") is True,
      "RSPAY_RECEIPT=1 не включает сценарий с чеком")
os.environ.pop("RSPAY_RECEIPT")

# заявка без телеграм-идентификатора всё равно должна уйти
p, fake = provider(Resp(200, OK_CARD))
p.create_invoice(555, 1000, payment_method="card")
check(json.loads(fake.calls[0]["body"].decode())["user"] == "web_555",
      "без user_id поле user пустое — RSPay отклонит обязательное поле")

# ── 6. коды методов ──────────────────────────────────────────────────────────

p = R.RSPayProvider()
check(p._method_code("sbp") == "sbp" and p._method_code("card") == "card",
      "обобщённые методы не переводятся")
check(p._method_code(None) == "sbp", "метод по умолчанию потерян")
os.environ["RSPAY_METHODS"] = "alfabank, sberbank_qr_vnm ,card"
check(p._method_code("alfabank") == "alfabank",
      "код банка магазина не проходит как есть")
check("card" not in R.direct_methods(),
      "обобщённое имя попало в список «передаём как есть» — маппинг RSPAY_METHOD_CARD "
      "станет мёртвым кодом, как это было у XPay")
os.environ.pop("RSPAY_METHODS")

# ── 7. статусы ───────────────────────────────────────────────────────────────

for raw_st, want in (("pending", "awaiting_payment"), ("processing", "awaiting_payment"),
                     ("success", "paid"), ("failed", "failed"),
                     ("cancelled", "cancelled"), ("no_requisites", "failed"),
                     ("refunded", "refunded"), ("partial_refunded", "refunded")):
    p, fake = provider(Resp(200, {"success": True, "ready": True, "status": raw_st}))
    got = p.get_status("obsidian_1_1")["status"]
    check(got == want, f"статус {raw_st} нормализован в {got}, ожидалось {want}")

from services.payout_guard import _PAID  # noqa: E402

check("refunded" not in _PAID,
      "возврат считается оплатой — крипта уйдёт по заявке, деньги за которую вернули")
p, fake = provider(Resp(500, None, text="oops"))
check(p.get_status("x")["status"] == "unknown",
      "сбой опроса выдан за определённый статус")

# ── 8. отмена ────────────────────────────────────────────────────────────────

p, fake = provider(Resp(200, {"success": True, "status": "cancelled",
                              "already_cancelled": False}))
check(p.cancel_order("obsidian_1_1")["ok"], "отмена не распознана")
p, fake = provider(Resp(200, {"success": True, "already_cancelled": True}))
check(p.cancel_order("obsidian_1_1")["already_cancelled"],
      "повторная отмена выдана за новую")

# ── 9. чек ───────────────────────────────────────────────────────────────────

p, fake = provider(Resp(200, {"ok": True, "result": {"status": "uploaded"}}))
res = p.upload_receipt("obsidian_1_1_bt", b"%PDF-1.4 fake", "receipt.pdf")
check(res.get("ok"), f"корректный PDF не принят: {res}")
sendcall = [c for c in fake.calls if c["m"] == "SEND"][0]
check(sendcall["headers"]["X-Signature"] == expected_sig(sendcall["body"], b"bt-s3cret"),
      "чек подписан не тем телом, которое отправлено — multipart собирается один раз, "
      "подписывать надо готовые байты")
check(b"proof" in sendcall["body"], "файл чека не попал в поле proof")

p, fake = provider(Resp(200, {"ok": True}))
check(not p.upload_receipt("x", b"...", "receipt.gif").get("ok"),
      "gif принят, хотя RSPay берёт только pdf/png/jpg/jpeg")
p, fake = provider(Resp(200, {"ok": True}))
check(not p.upload_receipt("x", b"x" * (11 * 1024 * 1024), "big.pdf").get("ok"),
      "PDF больше 10 МБ отправлен — вернётся 502 без объяснения")

# ── 10. вебхук ───────────────────────────────────────────────────────────────

hook = json.dumps({"event_type": "transaction.status_changed",
                   "merchant_transaction_id": attempt_id.make(4242),
                   "status": "success", "amount": "4475.00"}).encode()
check(R.verify_webhook_signature(hook, expected_sig(hook), "s3cret"),
      "верная подпись вебхука отвергнута")
check(not R.verify_webhook_signature(hook + b" ", expected_sig(hook), "s3cret"),
      "изменённое тело прошло проверку подписи")
check(not R.verify_webhook_signature(hook, "", "s3cret"),
      "пустая подпись принята — вебхук без заголовка пометит заявку оплаченной")
check(not R.verify_webhook_signature(hook, expected_sig(hook), ""),
      "пустой секрет = «проверять нечем», а не «проверка пройдена»")
check(R.verify_webhook_signature(hook, expected_sig(hook).upper(), "s3cret"),
      "подпись в верхнем регистре отвергнута — hex регистронезависим")

oid, st = R.RSPayProvider().parse_webhook(json.loads(hook))
check(oid == "4242" and st == "paid",
      f"вебхук разобран как {oid!r}/{st!r} — оплата придёт, а заявку мы не узнаем")

# ── 11. учётные данные ───────────────────────────────────────────────────────

from services import smart_router as sr  # noqa: E402

saved = dict(os.environ)
os.environ["RSPAY_SHOP_API_KEY"] = "key"
os.environ.pop("RSPAY_API_SECRET", None)
check(not sr.has_required_env("RSPayProvider"),
      "половины учётных данных хватило, чтобы роутер счёл канал настроенным — "
      "каждый запрос упадёт по подписи, а здоровье оштрафуется за нашу недонастройку")
os.environ["RSPAY_API_SECRET"] = "sec"
os.environ["RSPAY_BT_SHOP_API_KEY"] = "bt-key"
os.environ["RSPAY_BT_API_SECRET"] = "bt-sec"
check(sr.has_required_env("RSPayProvider"), "полные учётные данные не приняты")
os.environ.clear()
os.environ.update(saved)

check(sr.SHORT_NAMES.get("RSPayProvider") == "rspay",
      "провайдер не заведён в реестре коротких имён")

if FAILS:
    print(f"❌ RSPay: {len(FAILS)} провал(ов)")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("✅ RSPay: подпись от тех же байтов, реквизиты, статусы, чек и вебхук в порядке")
