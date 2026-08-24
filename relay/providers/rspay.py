"""RSPay (rspay.win) — приём рублёвых платежей через агрегатор.

Дока: https://merchant.rspay.win/api-docs (SPA, весь текст в бандле фронта;
выжимка — docs/rspay/api.md в этом репозитории).

Чем отличается от остальных наших провайдеров:

* подпись у КАЖДОГО запроса, а не только у создания: HMAC-SHA256 (hex) от
  ТОЧНЫХ БАЙТОВ тела, ключ — секрет мерчанта. Поэтому отправляем ровно ту
  строку, которую подписали (`data=`, не `json=`), а для GET подписываем
  пустую строку;
* защита от повтора: `X-Timestamp` (мс, окно ±5 минут) и `X-Nonce` (UUID,
  живёт 5 минут и второй раз не принимается). Оба заголовка обязательны —
  без них ответ 401, неотличимый по коду от «неверный ключ»;
* сопоставление с нашей заявкой идёт по `merchant_transaction_id` — поле
  `external_id` в вебхуке мерчанта НЕ приходит (сказано в доке прямым текстом).

Учётные данные (bot/.env):
    RSPAY_SHOP_API_KEY / RSPAY_API_SECRET       — QR/deeplink кабинет
    RSPAY_BT_SHOP_API_KEY / RSPAY_BT_API_SECRET — card/sbp кабинет
    RSPAY_BASE_URL      — по умолчанию https://rspay.win/api/v1

Ключ и секрет — из разных разделов кабинета. Перепутать их местами легко, а
ошибка выглядит как «неверная подпись»: см. `credentials_hint()`.
"""
import os
import json
import time
import uuid
import hmac
import hashlib
import requests

from providers.base import PaymentProvider
from core import attempt_id
from repositories.operational_read_store import from_environment as _read_store_from_environment
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

RSPAY_BASE_URL = os.getenv('RSPAY_BASE_URL', 'https://rspay.win/api/v1').rstrip('/')
RSPAY_SHOP_API_KEY = os.getenv('RSPAY_SHOP_API_KEY', '')
RSPAY_API_SECRET = os.getenv('RSPAY_API_SECRET', '')
RSPAY_BT_SHOP_API_KEY = os.getenv('RSPAY_BT_SHOP_API_KEY', '')
RSPAY_BT_API_SECRET = os.getenv('RSPAY_BT_API_SECRET', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')
DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
def _store():return _read_store_from_environment(sqlite_path=DB_PATH)

# Коды методов у RSPay зависят от того, что включено КОНКРЕТНОМУ магазину
# (дока: «Список ниже соответствует методам, доступным вашему магазину»), и
# эндпоинта «перечисли мои методы» в API нет. Поэтому обобщённые «карта/СБП/QR»
# переводятся в коды через переменные окружения, а точные коды магазина
# (alfabank, sberbank_qr_vnm, …) перечисляются в RSPAY_METHODS и уходят как есть.
RSPAY_METHOD_SBP = os.getenv('RSPAY_METHOD_SBP', 'sbp')
RSPAY_METHOD_CARD = os.getenv('RSPAY_METHOD_CARD', 'card')
RSPAY_METHOD_QR = os.getenv('RSPAY_METHOD_QR', 'qr')
RSPAY_METHOD_DEFAULT = os.getenv('RSPAY_METHOD_DEFAULT', 'sbp')

# Обобщённые имена сюда не попадают НИКОГДА: у XPay ровно на этом обожглись —
# 'card' в списке «передаём как есть» сделал маппинг XPAY_TYPE_CARD мёртвым
# кодом, и карточный метод гарантированно падал в 403. Здесь фильтр явный.
_GENERIC = {"sbp", "card", "qr", "any", ""}


def direct_methods() -> set:
    raw = os.getenv('RSPAY_METHODS', '')
    return {m.strip().lower() for m in raw.split(',')
            if m.strip() and m.strip().lower() not in _GENERIC}


# Статусы транзакций RSPay → наши нормализованные.
# refunded/partial_refunded НЕ равны failed: деньги были, их вернули. Мешать их
# с «не оплачено» нельзя — страж выплаты (payout_guard) считает paid-подобные
# статусы поводом отдать крипту, а возврат это ровно обратное.
_STATUS_MAP = {
    "pending": "awaiting_payment",
    "processing": "awaiting_payment",
    "success": "paid",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "no_requisites": "failed",
    "refunded": "refunded",
    "partial_refunded": "refunded",
}

# Финальные статусы: дальше состояние не меняется, опрашивать больше нечего.
FINAL_STATUSES = {"paid", "failed", "cancelled", "refunded"}


def sign(secret: str, body: bytes) -> str:
    """HMAC-SHA256 (hex) от сырых байтов тела. Для запросов без тела — от пустой строки."""
    return hmac.new(secret.encode('utf-8'), body or b'', hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str = None) -> bool:
    """Проверка подписи входящего вебхука (заголовок X-Signature).

    Fail-closed: пустой секрет или пустая подпись — это НЕ «проверять нечего»,
    а «проверить невозможно», и такой запрос принимать нельзя. Сравнение
    постоянного времени: обычное `==` по hex-строке подсказывает подбирающему,
    сколько символов он уже угадал.
    """
    secret = RSPAY_API_SECRET if secret is None else secret
    if not secret or not signature:
        return False
    expected = sign(secret, raw_body if isinstance(raw_body, bytes)
                    else str(raw_body).encode('utf-8'))
    return hmac.compare_digest(expected, str(signature).strip().lower())


def credentials_hint() -> str:
    """Чего не хватает для работы канала. Пустая строка = всё на месте."""
    missing = []
    if not RSPAY_SHOP_API_KEY:
        missing.append("RSPAY_SHOP_API_KEY (ключ магазина, раздел «Магазины»)")
    if not RSPAY_API_SECRET:
        missing.append("RSPAY_API_SECRET (секрет мерчанта, раздел «Настройки»)")
    return "RSPay: не заданы " + ", ".join(missing) if missing else ""


def bt_credentials_hint() -> str:
    missing = []
    if not RSPAY_BT_SHOP_API_KEY:
        missing.append("RSPAY_BT_SHOP_API_KEY")
    if not RSPAY_BT_API_SECRET:
        missing.append("RSPAY_BT_API_SECRET")
    return "RSPay BT: не заданы " + ", ".join(missing) if missing else ""


def _client_counters(user_id) -> dict:
    """Сколько заявок клиент создал и сколько оплатил — поля антифрода RSPay.

    Опциональны: без них интеграция работает как раньше (дока). Поэтому любая
    ошибка чтения базы = просто не отправляем счётчики, а не срыв платежа.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return {}
    if uid <= 0:
        return {}
    try:
        counts = _store().client_order_counts(uid, ('paid','sent','completed'))
    except Exception as e:
        logger.warning("RSPay: счётчики клиента %s не прочитались: %s", uid, e)
        return {}
    created, paid = counts['created'], counts['paid']
    return {"client_created_count": created, "client_paid_count": paid}


class RSPayProvider(PaymentProvider):
    def __init__(self):
        self.base_url = RSPAY_BASE_URL
        self.api_key = RSPAY_SHOP_API_KEY
        self.secret = RSPAY_API_SECRET
        self.bt_api_key = RSPAY_BT_SHOP_API_KEY
        self.bt_secret = RSPAY_BT_API_SECRET

    def _use_profile(self, profile: str):
        if profile == "bt":
            self.api_key, self.secret = self.bt_api_key, self.bt_secret
        else:
            self.api_key, self.secret = RSPAY_SHOP_API_KEY, RSPAY_API_SECRET

    @staticmethod
    def _profile_for_method(method: str) -> str:
        return "bt" if method in (RSPAY_METHOD_CARD, RSPAY_METHOD_SBP, "card", "sbp") else "qr"

    def _profile_for_invoice(self, invoice_id) -> str:
        return "bt" if str(invoice_id or "").endswith("_bt") else "qr"

    # ── подписанный транспорт ───────────────────────────────────────────────

    def _headers(self, body: bytes, content_type: str = None) -> dict:
        h = {
            "X-Shop-API-Key": self.api_key,
            "X-Signature": sign(self.secret, body),
            # Часы сервера должны совпадать с их сервером в пределах 5 минут.
            # Расхождение выглядит как 401 «неверный ключ» — см. describe_401().
            "X-Timestamp": str(int(time.time() * 1000)),
            "X-Nonce": str(uuid.uuid4()),
        }
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _post(self, path: str, body: dict):
        # Подписываем и отправляем ОДНИ И ТЕ ЖЕ байты: если сериализовать дважды
        # (подписать одну строку, отправить другую), подпись не сойдётся, а
        # ответ будет 401 — про ключ, а не про сериализацию.
        raw = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        try:
            return requests.post(f"{self.base_url}{path}", data=raw,
                                 headers=self._headers(raw, "application/json"),
                                 timeout=PROVIDER_TIMEOUT)
        except Exception as e:
            logger.error("RSPay POST %s: %s", path, e)
            return None

    def _get(self, path: str, params: dict = None):
        # Тела нет — подпись от пустой строки (дока, раздел «Аутентификация»).
        try:
            return requests.get(f"{self.base_url}{path}", params=params or None,
                                headers=self._headers(b''),
                                timeout=PROVIDER_TIMEOUT)
        except Exception as e:
            logger.error("RSPay GET %s: %s", path, e)
            return None

    @staticmethod
    def describe_401(text: str = "") -> str:
        """401 у RSPay накрывает пять разных причин — не давать оператору гадать."""
        return ("RSPay 401: либо ключ магазина/секрет мерчанта неверны или перепутаны "
                "местами, либо часы сервера ушли больше чем на 5 минут, либо nonce "
                "повторился. " + (text[:150] if text else "")).strip()

    def _json(self, r, what: str):
        """(данные, ошибка). Ошибка — уже готовая к записи в лог строка."""
        if r is None:
            return None, "RSPay недоступен (сеть)"
        try:
            data = r.json()
        except Exception:
            return None, f"RSPay HTTP {r.status_code}: не-JSON ответ"
        if r.status_code == 401:
            return data, self.describe_401(r.text)
        if r.status_code == 409:
            return data, "RSPay: transaction_id уже существует (409)"
        if r.status_code >= 400:
            # В теле бывает {"error": ...} и {"errors": {"поле": ["текст"]}}
            err = data.get("error") or ""
            fields = data.get("errors") or {}
            if isinstance(fields, dict) and fields:
                err = (err + " " + "; ".join(
                    f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else v}"
                    for k, v in fields.items())).strip()
            return data, f"RSPay {what} HTTP {r.status_code}: {err or r.text[:200]}"
        return data, None

    # ── создание платежа ────────────────────────────────────────────────────

    def _method_code(self, payment_method) -> str:
        m = str(payment_method or "").strip().lower()
        if m in direct_methods():
            return m
        if m == "sbp":
            return RSPAY_METHOD_SBP
        if m == "card":
            return RSPAY_METHOD_CARD
        if m in ("qr", "sbp_qr"):
            return RSPAY_METHOD_QR
        return RSPAY_METHOD_DEFAULT

    def create_invoice(self, order_id, amount, payment_method=None, user_id=None):
        method = self._method_code(payment_method)
        profile = self._profile_for_method(method)
        hint = bt_credentials_hint() if profile == "bt" else credentials_hint()
        if hint:
            return {"error": hint}
        self._use_profile(profile)
        # Суффикс попытки: три быстрых ретрая с одним transaction_id упрутся
        # в 409 Conflict, и клиент не получит реквизиты из-за нашей же защиты.
        tx_id = f"{attempt_id.make(order_id)}_{profile}"

        # `user` обязателен и уходит в антифрод RSPay. Для платежей без телеграм-
        # идентификатора (веб-кабинет) честнее послать стабильный ключ заявки,
        # чем выдумывать чужой ID; в логе это видно.
        if user_id:
            user_ref = str(user_id)
        else:
            user_ref = f"web_{order_id}"
            logger.info("RSPay: заявка %s без telegram_id — в user уходит %s", order_id, user_ref)

        body = {
            "transaction_id": tx_id,
            "payment_method": method,
            "amount": f"{float(amount):.2f}",
            "currency": "RUB",
            "user": user_ref,
            # KYC-сценарий требует в поле `user` НОМЕР ТЕЛЕФОНА плательщика.
            # Телефона у нас нет (обмен non-KYC), и подставить туда что-то
            # похожее нельзя: верификация уйдёт на чужой номер. Поэтому false.
            "kyc": False,
            "callback_url": f"{PUBLIC_RELAY}/rspay/webhook",
        }
        # receipt=true ОБЯЗЫВАЕТ нас загрузить чек: без него сделка у RSPay
        # висит незакрытой. Включать только вместе с рабочим каналом чека —
        # отсюда отдельный флаг, по умолчанию выключенный.
        if os.getenv('RSPAY_RECEIPT', '') == '1' and method in ('card', 'sbp'):
            body["receipt"] = True
        body.update(_client_counters(user_id))

        r = self._post("/requisites/request/", body)
        data, err = self._json(r, "createOrder")
        if err:
            logger.error("RSPay create %s (%s ₽, %s): %s", order_id, amount, method, err)
            return {"error": err}

        # Реквизитов может не быть — это штатный ответ 200, а не сбой канала:
        # success=false, status='none'. Текст попадает в NO_TRADERS-классификатор
        # smart_router (в нём есть «реквизит»), поэтому здоровье не штрафуется.
        requisites = data.get("requisites") or {}
        if not data.get("success") or not requisites:
            reason = data.get("error") or "нет свободных реквизитов"
            logger.warning("RSPay %s: реквизиты не выданы (%s)", order_id, reason)
            return {"error": f"RSPay: {reason}"}

        norm = {}
        link = requisites.get("payment_link") or ""
        if link:
            norm["payment_link"] = link
        if requisites.get("card_number"):
            norm["card_number"] = requisites["card_number"]
        if requisites.get("phone_number"):
            norm["phone"] = requisites["phone_number"]
        if requisites.get("bank_name"):
            norm["bank_name"] = requisites["bank_name"]
        if requisites.get("owner_name"):
            norm["recipient"] = requisites["owner_name"]
        if not norm:
            # Метод отдал что-то, чего мы не понимаем. Показать клиенту пустую
            # карточку хуже, чем уйти на другой маршрут.
            logger.error("RSPay %s: непонятная форма реквизитов %s", order_id, requisites)
            return {"error": "RSPay: реквизиты в неизвестном формате"}

        raw = dict(data)
        raw["requisites"] = norm
        raw["merchant_transaction_id"] = data.get("merchant_transaction_id") or tx_id
        # Запоминаем, просили ли мы сценарий с чеком: приём чека у RSPay работает
        # только для таких заявок, а по ответу это уже не восстановить.
        raw["receipt"] = bool(body.get("receipt"))
        # Сумму RSPay не «уникализирует» (в ответе её нет вовсе) — клиент платит
        # ровно ту, что мы запросили. Кладём её явно: страж выплаты сверяет
        # оплаченное с ожидаемым и без суммы в raw остаётся без доказательства.
        raw["amount_rub"] = float(amount)
        return {
            # Ключ для статуса/отмены/чека — НАШ transaction_id: все три
            # эндпоинта RSPay принимают именно merchant_transaction_id.
            "invoice_id": tx_id,
            "amount": float(amount),
            "status": "awaiting_payment",
            # qr_data — строка для отрисовки QR (её отдают внутрибанковые QR),
            # payment_link — ссылка. Если есть и то и другое, QR точнее.
            "qr_payload": requisites.get("qr_data") or link or None,
            "banks": [],
            "raw": raw,
        }

    # ── статус ──────────────────────────────────────────────────────────────

    def get_status(self, invoice_id):
        """Платёжный статус по НАШЕМУ transaction_id (POST /requisites/status/)."""
        if not invoice_id:
            return {"status": "unknown"}
        profile = self._profile_for_invoice(invoice_id)
        hint = bt_credentials_hint() if profile == "bt" else credentials_hint()
        if hint:
            return {"status": "unknown"}
        self._use_profile(profile)
        r = self._post("/requisites/status/", {"transaction_id": str(invoice_id)})
        data, err = self._json(r, "status")
        if err:
            logger.warning("RSPay get_status %s: %s", invoice_id, err)
            return {"status": "unknown"}
        raw_status = data.get("status") or data.get("transaction_status")
        return {
            "status": _STATUS_MAP.get(raw_status, "unknown"),
            "raw_status": raw_status,
            "ready": bool(data.get("ready")),
            "raw": data,
        }

    def get_transaction(self, rspay_id):
        """Детальная карточка по ВНУТРЕННЕМУ id RSPay (GET /transactions/{id}/).

        Отдельный метод от get_status: там ключ наш, здесь — их числовой id.
        Перепутать их местами значит получить 404 и решить, что платежа нет.
        """
        if not rspay_id:
            return {}
        data, err = self._json(self._get(f"/transactions/{rspay_id}/"), "transaction")
        if err:
            logger.warning("RSPay get_transaction %s: %s", rspay_id, err)
            return {}
        return data

    def list_transactions(self, page=1, page_size=20, status=None, currency=None,
                          date_from=None, date_to=None):
        """Список транзакций магазина (GET /merchant/transactions/) — для сверки."""
        params = {"page": page, "page_size": min(int(page_size or 20), 100)}
        for k, v in (("status", status), ("currency", currency),
                     ("date_from", date_from), ("date_to", date_to)):
            if v:
                params[k] = v
        data, err = self._json(self._get("/merchant/transactions/", params), "transactions")
        if err:
            logger.warning("RSPay list_transactions: %s", err)
            return {"transactions": [], "error": err}
        return data

    def get_balance(self):
        """Доступный к выводу баланс. Источник истины — USDT, рубли считает их курс."""
        data, err = self._json(self._get("/balance/"), "balance")
        if err:
            logger.warning("RSPay get_balance: %s", err)
            return None
        try:
            return float(data.get("balance_usdt"))
        except (TypeError, ValueError):
            return None

    # ── отмена ──────────────────────────────────────────────────────────────

    def cancel_order(self, invoice_id):
        """Отмена заявки, когда клиент передумал (только pending/processing).

        Повторная отмена — не ошибка: RSPay отвечает 200 и already_cancelled.
        """
        if not invoice_id:
            return {"ok": False, "error": "нет transaction_id"}
        self._use_profile(self._profile_for_invoice(invoice_id))
        r = self._post("/transactions/cancel/", {"transaction_id": str(invoice_id)})
        data, err = self._json(r, "cancel")
        if err:
            return {"ok": False, "error": err}
        return {"ok": bool(data.get("success")),
                "already_cancelled": bool(data.get("already_cancelled")),
                "raw": data}

    # ── чек ─────────────────────────────────────────────────────────────────

    # Дока: PDF отправляется как есть и больше 10 МБ отклоняется; картинки
    # (png/jpg/jpeg) сжимаются на их стороне до 1 МБ. Проверяем ДО отправки —
    # иначе оператор увидит 502 «ошибка загрузки чека» без объяснения.
    _RECEIPT_EXT = {"pdf": "application/pdf", "png": "image/png",
                    "jpg": "image/jpeg", "jpeg": "image/jpeg"}
    _PDF_LIMIT = 10 * 1024 * 1024

    def upload_receipt(self, invoice_id, file_bytes: bytes,
                       filename: str = "receipt.pdf", comment: str = "") -> dict:
        """Чек мерчанта по транзакции, созданной с receipt=true (card/sbp).

        multipart/form-data. Подпись, как и везде, считается от точных байтов
        тела — поэтому запрос сначала СОБИРАЕТСЯ (PreparedRequest), а
        подписывается уже готовое тело. Считать подпись от пустой строки, как
        для GET, здесь неоткуда: тело есть. Если поддержка RSPay скажет иное —
        RSPAY_RECEIPT_SIGN_EMPTY=1 переключает на пустую подпись без правки кода.
        """
        if not invoice_id:
            return {"ok": False, "error": "нет transaction_id"}
        profile = self._profile_for_invoice(invoice_id)
        hint = bt_credentials_hint() if profile == "bt" else credentials_hint()
        if hint:
            return {"ok": False, "error": hint}
        self._use_profile(profile)
        ext = str(filename).rsplit(".", 1)[-1].lower()
        ctype = self._RECEIPT_EXT.get(ext)
        if not ctype:
            return {"ok": False, "reason": "unsupported",
                    "error": "RSPay принимает чек только в PDF, PNG, JPG или JPEG"}
        if ext == "pdf" and len(file_bytes) > self._PDF_LIMIT:
            return {"ok": False, "error": "RSPay не примет PDF больше 10 МБ"}

        req = requests.Request(
            "POST", f"{self.base_url}/requisites/receipt/",
            data={"transaction_id": str(invoice_id), **({"comment": comment} if comment else {})},
            files={"proof": (filename, file_bytes, ctype)},
        ).prepare()
        body = req.body if isinstance(req.body, bytes) else str(req.body or "").encode()
        if os.getenv("RSPAY_RECEIPT_SIGN_EMPTY", "") == "1":
            body = b""
        # Content-Type ставит сам PreparedRequest (в нём boundary) — не трогаем.
        for k, v in self._headers(body).items():
            req.headers[k] = v
        try:
            with requests.Session() as s:
                r = s.send(req, timeout=PROVIDER_TIMEOUT)
        except Exception as e:
            logger.error("RSPay receipt %s: %s", invoice_id, e)
            return {"ok": False, "error": str(e)}
        data, err = self._json(r, "receipt")
        if err:
            logger.warning("RSPay receipt %s: %s", invoice_id, err)
            return {"ok": False, "error": err}
        ok = bool(data.get("ok"))
        if not ok:
            return {"ok": False, "error": f"RSPay чек не принят: {str(data)[:200]}"}
        logger.info("RSPay receipt %s: принят", invoice_id)
        return {"ok": True, "raw": data}

    # ── вебхук ──────────────────────────────────────────────────────────────

    def get_payment_methods(self, invoice_id):
        # Эндпоинта «какие методы включены магазину» у RSPay нет — список
        # задаётся в кабинете и переносится к нам в RSPAY_METHODS.
        return []

    def parse_webhook(self, data):
        """(order_id, статус). Сопоставление ТОЛЬКО по merchant_transaction_id:
        external_id в мерчантском вебхуке не приходит (сказано в доке)."""
        order_id = attempt_id.parse(data.get("merchant_transaction_id"))
        return order_id, _STATUS_MAP.get(data.get("status"), "unknown")
