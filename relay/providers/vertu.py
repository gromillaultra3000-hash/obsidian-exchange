import os, time, threading, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

VERTU_BASE_URL = os.getenv('VERTU_BASE_URL', 'https://api.vertu.sh').rstrip('/')
VERTU_LOGIN = os.getenv('VERTU_LOGIN', '')
VERTU_PASSWORD = os.getenv('VERTU_PASSWORD', '')
# Статичный API-ключ из ЛК мерчанта — работает как Bearer напрямую,
# без /v1/auth/login/ (проверено на /v1/balance/). Если задан — логин не нужен
VERTU_API_KEY = os.getenv('VERTU_API_KEY', '')
# Коды методов оплаты (payment_method.code в терминах Vertu) — могут отличаться
# в зависимости от настроек мерчанта, поэтому переопределяемы через env
VERTU_TYPE_SBP = os.getenv('VERTU_TYPE_SBP', 'wt_sbp')
VERTU_TYPE_CARD = os.getenv('VERTU_TYPE_CARD', 'wt_c2c')

# Bearer-токен (refresh_token из /v1/auth/login/) кешируется на процесс;
# срок жизни в доке не указан — обновляем раз в 30 минут и при AuthError
_TOKEN_TTL = 1800
_token_lock = threading.Lock()
_token_cache = {"value": None, "obtained_at": 0.0}

# Статусы Vertu: Pending / Approved / Declined / Revoked
_STATUS_MAP = {
    "Pending": "awaiting_payment",
    "Approved": "paid",
    "Declined": "failed",
    "Revoked": "failed",
}


class VertuProvider(PaymentProvider):
    def __init__(self):
        self.base_url = VERTU_BASE_URL
        self.login = VERTU_LOGIN
        self.password = VERTU_PASSWORD
        self.api_key = VERTU_API_KEY

    # ── Авторизация ────────────────────────────────────────────────────────────

    def _get_token(self, force: bool = False):
        if self.api_key:
            return self.api_key
        with _token_lock:
            fresh = time.time() - _token_cache["obtained_at"] < _TOKEN_TTL
            if _token_cache["value"] and fresh and not force:
                return _token_cache["value"]
            try:
                r = requests.post(
                    f"{self.base_url}/v1/auth/login/",
                    json={"login": self.login, "password": self.password},
                    timeout=PROVIDER_TIMEOUT,
                )
                data = r.json()
                token = data.get("refresh_token")
                if r.status_code != 200 or not token:
                    logger.error(f"Vertu login failed {r.status_code}: {r.text[:200]}")
                    return None
                _token_cache["value"] = token
                _token_cache["obtained_at"] = time.time()
                return token
            except Exception as e:
                logger.error(f"Vertu login request failed: {e}")
                return None

    def _request(self, method, path, **kwargs):
        """Запрос с Bearer-токеном; при AuthError один раз перелогинивается."""
        for attempt in range(2):
            token = self._get_token(force=attempt > 0)
            if not token:
                return None
            try:
                r = requests.request(
                    method, f"{self.base_url}{path}",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=PROVIDER_TIMEOUT, **kwargs,
                )
            except Exception as e:
                logger.error(f"Vertu {method} {path} failed: {e}")
                return None
            # 401 / {"error": "AuthError"} — токен протух, пробуем с новым
            auth_failed = r.status_code == 401
            if not auth_failed and r.status_code == 400:
                try:
                    auth_failed = (r.json().get("error") == "AuthError")
                except Exception:
                    pass
            if auth_failed and attempt == 0:
                continue
            return r
        return None

    # ── Создание платежа ────────────────────────────────────────────────────────

    def create_invoice(self, order_id, amount, payment_method=None, user_id=None):
        if not self.api_key and (not self.login or not self.password):
            return {"error": "Vertu: не настроены VERTU_API_KEY или VERTU_LOGIN/VERTU_PASSWORD"}

        type_pay = VERTU_TYPE_SBP if payment_method == "sbp" else VERTU_TYPE_CARD
        # POST /v1/deals/ ТРЕБУЕТ поле deal_id (иначе HTTP 422 "deal_id: Field
        # required"). Коммит 7743de9 переименовал его в platform_id — это ломало
        # ВСЕ сделки Vertu с 10.07 (проверено живым API: platform_id-only → 422,
        # deal_id-only → доходит до подбора трейдера). platform_id в ЗАПРОСЕ
        # игнорируется; свой platform_id для GET-статуса Vertu возвращает в
        # ОТВЕТЕ. timestamp — чтобы retry в PaymentService не упирался в дубль ID.
        payload = {
            "deal_id": f"obsidian_{order_id}_{int(time.time())}",
            "amount": float(amount),
            "type_pay": type_pay,
        }
        if user_id:
            payload["client_id"] = str(user_id)

        r = self._request("POST", "/v1/deals/", json=payload)
        if r is None:
            return {"error": "Vertu недоступен (авторизация или сеть)"}
        try:
            data = r.json()
        except Exception:
            return {"error": f"Vertu HTTP {r.status_code}: не-JSON ответ"}
        if r.status_code != 200 or data.get("error"):
            logger.error(f"Vertu create error {r.status_code}: {r.text[:300]} | "
                         f"amount={amount} type_pay={type_pay}")
            return {"error": data.get("error") or f"Vertu HTTP {r.status_code}"}

        details = data.get("bank_details") or ""
        requisites = {}
        if details.startswith("http"):
            # nspk / tpay / qr-методы отдают ссылку
            requisites["payment_link"] = details
        elif type_pay == VERTU_TYPE_SBP or data.get("type_pay") in ("sbp", "wt_sbp"):
            requisites["phone"] = details
        else:
            requisites["card_number"] = details
        if data.get("bank"):
            requisites["bank_name"] = data["bank"]
        if data.get("full_name"):
            requisites["recipient"] = data["full_name"]

        raw = dict(data)
        raw["requisites"] = requisites
        return {
            # platform_id — ключ для GET /v1/deals/{platform_deal_id}/
            "invoice_id": data.get("platform_id"),
            "amount": data.get("amount_rub") or amount,
            "status": _STATUS_MAP.get(data.get("status"), "awaiting_payment"),
            "qr_payload": requisites.get("payment_link"),
            "banks": [],
            "raw": raw,
        }

    # ── Статус платежа ──────────────────────────────────────────────────────────

    def get_status(self, invoice_id):
        if not invoice_id:
            return {"status": "unknown"}
        r = self._request("GET", f"/v1/deals/{invoice_id}/")
        if r is None:
            return {"status": "unknown"}
        try:
            data = r.json()
        except Exception:
            return {"status": "unknown"}
        if r.status_code != 200 or data.get("error"):
            logger.warning(f"Vertu get_status {invoice_id}: {r.status_code} {r.text[:200]}")
            return {"status": "unknown"}
        status = data.get("status")
        return {"status": _STATUS_MAP.get(status, status or "unknown"),
                "raw_status": status, "raw": data}

    # ── Подтверждение оплаты чеком ──────────────────────────────────────────────

    def upload_receipt(self, invoice_id: str, file_bytes: bytes,
                       filename: str = "receipt.pdf") -> dict:
        """Привязывает PDF-чек клиента к сделке (POST /v1/wt_receipts/).

        ⚠️ Этого канала не было с момента интеграции Vertu (реализованы были
        только create/status/balance/login). Когда трейдер требовал доказательство
        оплаты, отправить его было нечем: клиент платил, сделка уходила в Declined,
        деньги оставались у трейдера. Так 20.07.2026 потеряна заявка 99955056 на
        30 000 ₽ (сделка 0084-obsidian_99955056_1784547409 → Declined).

        Отправлять ТОЛЬКО PDF: поле описано в спеке как «PDF-чек», другие форматы
        Vertu отклоняет. Ответ: {"success": bool, "external_sync_success": bool} —
        external_sync_success=false означает, что Vertu чек принял, но не
        протолкнул его дальше трейдеру; для клиента это НЕ успех, иначе мы
        скажем «принято» там, где доказательство до трейдера не дошло.
        """
        if not invoice_id:
            return {"ok": False, "error": "нет platform_id сделки"}
        last_error = None
        for attempt in range(3):
            if attempt:
                time.sleep(4)
            r = self._request(
                "POST", "/v1/wt_receipts/",
                data={"platform_id": invoice_id},
                files={"file": (filename, file_bytes, "application/pdf")},
            )
            if r is None:
                last_error = "Vertu не отвечает, попробуйте через 1-2 минуты"
                continue
            if r.status_code in (502, 503, 504):
                last_error = f"Vertu временно недоступна (HTTP {r.status_code})"
                logger.warning("Vertu wt_receipts attempt %s got %s, retry",
                               attempt + 1, r.status_code)
                continue
            try:
                data = r.json()
            except Exception:
                data = {}
            if r.status_code == 200 and data.get("success"):
                if not data.get("external_sync_success", True):
                    logger.error("Vertu wt_receipts %s: чек принят, но external_sync "
                                 "не прошёл — трейдер его не увидит", invoice_id)
                    return {"ok": False, "raw": data,
                            "error": "Vertu приняла чек, но не передала его трейдеру. "
                                     "Нужен оператор."}
                logger.info("Vertu wt_receipts %s: чек привязан", invoice_id)
                return {"ok": True, "raw": data}
            err = data.get("error") or f"HTTP {r.status_code}: {r.text[:200]}"
            logger.warning("Vertu wt_receipts %s: %s", invoice_id, err)
            return {"ok": False, "error": err}
        return {"ok": False, "error": last_error or "Vertu недоступна"}

    def reject_deal(self, invoice_id: str) -> dict:
        """Отклоняет сделку с откатом резервов (POST /v1/deals/{id}/rejected/).

        Нужен, когда клиент точно не платил: иначе сделка висит до истечения и
        держит лимит трейдера, из-за чего следующим заявкам «не находится
        реквизитов».
        """
        if not invoice_id:
            return {"ok": False, "error": "нет platform_id сделки"}
        r = self._request("POST", f"/v1/deals/{invoice_id}/rejected/")
        if r is None:
            return {"ok": False, "error": "Vertu не отвечает"}
        try:
            data = r.json()
        except Exception:
            data = {}
        if r.status_code == 200 and data.get("success"):
            return {"ok": True, "raw": data}
        return {"ok": False,
                "error": data.get("error") or f"HTTP {r.status_code}: {r.text[:200]}"}

    # ── Баланс (для мониторинга) ────────────────────────────────────────────────

    def get_balance(self):
        r = self._request("GET", "/v1/balance/")
        if r is None or r.status_code != 200:
            return None
        try:
            return r.json().get("balance")
        except Exception:
            return None

    # ── Выплаты (сторона продажи: клиент отдаёт крипту, получает рубли) ─────────

    # Коды банков для выплат RUB (по спеке /v1/payout/). Отличаются от того, что
    # Vertu присылает в реквизитах пополнения ("Сбербанк"), поэтому маппим явно.
    PAYOUT_BANKS = {"t-bank", "alfa", "sber", "vtb", "gazprom", "psb"}
    _BANK_ALIASES = {
        "тбанк": "t-bank", "т-банк": "t-bank", "тинькофф": "t-bank", "tinkoff": "t-bank",
        "альфа": "alfa", "альфабанк": "alfa", "альфа-банк": "alfa",
        "сбер": "sber", "сбербанк": "sber",
        "втб": "vtb", "газпром": "gazprom", "газпромбанк": "gazprom",
        "псб": "psb", "промсвязьбанк": "psb",
    }

    @classmethod
    def normalize_bank(cls, bank: str) -> str | None:
        """Приводит название банка к коду Vertu. None — если код неизвестен.

        Молча подставлять «какой-нибудь» банк нельзя: деньги уйдут не туда.
        """
        b = (bank or "").strip().lower().replace(" ", "")
        if b in cls.PAYOUT_BANKS:
            return b
        return cls._BANK_ALIASES.get(b)

    def create_payout(self, order_id, amount, bank, bank_details, full_name,
                      payment_method=None, user_id=None, callback_url=None):
        """Создаёт выплату рублей клиенту (POST /v1/payout/).

        ⚠️ Это ОТПРАВКА ДЕНЕГ. Вызывать только после того, как крипта клиента
        подтверждена на нашей стороне (sell_guard), и только с проверенным кодом
        банка — неизвестный банк отклоняем, а не угадываем.
        """
        code = self.normalize_bank(bank)
        if not code:
            return {"error": f"Vertu: неизвестный код банка '{bank}'. "
                             f"Допустимы: {', '.join(sorted(self.PAYOUT_BANKS))}"}
        if not bank_details or not full_name:
            return {"error": "Vertu: для выплаты нужны реквизиты и ФИО получателя"}

        payload = {
            "deal_id": f"obsidian_out_{order_id}_{int(time.time())}",
            "amount": float(amount),
            "type_pay": "sbp" if payment_method == "sbp" else "c2c",
            "bank": code,
            "bank_details": str(bank_details),
            "full_name": str(full_name),
        }
        if user_id:
            payload["client_id"] = str(user_id)
        if callback_url:
            payload["callback_url"] = callback_url

        r = self._request("POST", "/v1/payout/", json=payload)
        if r is None:
            return {"error": "Vertu недоступна"}
        try:
            data = r.json()
        except Exception:
            return {"error": f"Vertu: некорректный ответ ({r.status_code})"}
        if r.status_code not in (200, 201) or data.get("error"):
            err = data.get("error") or f"HTTP {r.status_code}: {r.text[:200]}"
            logger.error("Vertu create_payout order=%s: %s", order_id, err)
            return {"error": str(err)}
        logger.info("Vertu payout создан: order=%s platform_id=%s",
                    order_id, data.get("platform_id"))
        return {"payout_id": data.get("platform_id"), "deal_id": data.get("deal_id"),
                "amount": data.get("amount_rub"),
                "status": _STATUS_MAP.get(data.get("status"), "pending"),
                "raw": data}

    def get_payout_status(self, payout_id):
        """Статус выплаты (GET /v1/payout/{platform_deal_id}/)."""
        if not payout_id:
            return {"status": "unknown"}
        r = self._request("GET", f"/v1/payout/{payout_id}/")
        if r is None:
            return {"status": "unknown"}
        try:
            data = r.json()
        except Exception:
            return {"status": "unknown"}
        if r.status_code != 200 or data.get("error"):
            logger.warning("Vertu get_payout_status %s: %s %s",
                           payout_id, r.status_code, r.text[:200])
            return {"status": "unknown"}
        status = data.get("status")
        return {"status": _STATUS_MAP.get(status, status or "unknown"),
                "raw_status": status, "raw": data}

    # ── Прочие обязательные методы ─────────────────────────────────────────────

    def get_payment_methods(self, invoice_id):
        return []

    def parse_webhook(self, data):
        # Вебхуков у Vertu нет (по OpenAPI-спеке) — статус получаем опросом
        return None, None
