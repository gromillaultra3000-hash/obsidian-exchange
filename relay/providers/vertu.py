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

    # ── Баланс (для мониторинга) ────────────────────────────────────────────────

    def get_balance(self):
        r = self._request("GET", "/v1/balance/")
        if r is None or r.status_code != 200:
            return None
        try:
            return r.json().get("balance")
        except Exception:
            return None

    # ── Прочие обязательные методы ─────────────────────────────────────────────

    def get_payment_methods(self, invoice_id):
        return []

    def parse_webhook(self, data):
        # Вебхуков у Vertu нет (по OpenAPI-спеке) — статус получаем опросом
        return None, None
