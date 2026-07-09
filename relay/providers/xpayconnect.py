import os, time, json, hashlib, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

XPAY_BASE_URL = os.getenv('XPAY_BASE_URL', 'https://api.xpayconnect.io').rstrip('/')
XPAY_API_KEY = os.getenv('XPAY_API_KEY', '')
XPAY_MERCHANT_ID = os.getenv('XPAY_MERCHANT_ID', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')

# Коды методов XPayConnect (поле type): sim = СБП РФ, card = карта РФ,
# any = карта/СБП на усмотрение системы (docs.xpayconnect.io/reference/payment-methods.md)
XPAY_TYPE_SBP = os.getenv('XPAY_TYPE_SBP', 'sim')
XPAY_TYPE_CARD = os.getenv('XPAY_TYPE_CARD', 'card')
XPAY_TYPE_DEFAULT = os.getenv('XPAY_TYPE_DEFAULT', 'any')

# Статусы XPayConnect: pending / success / error
_STATUS_MAP = {
    "pending": "awaiting_payment",
    "success": "paid",
    "error": "failed",
}


def sign_body(api_key: str, body_str: str) -> str:
    """x-api-key = SHA-256 от строки '<API_KEY>|<тело_запроса>' (пустое тело для GET)."""
    return hashlib.sha256(f"{api_key}|{body_str}".encode()).hexdigest()


class XPayConnectProvider(PaymentProvider):
    def __init__(self):
        self.base_url = XPAY_BASE_URL
        self.api_key = XPAY_API_KEY
        self.merchant_id = XPAY_MERCHANT_ID

    # ── HTTP с подписью ─────────────────────────────────────────────────────────

    def _post(self, path, body: dict):
        # Подпись считается от JSON-строки без пробелов; отправляем ровно ту же
        # строку (data=, не json=), иначе подпись не совпадёт на стороне XPay
        body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
        try:
            return requests.post(
                f"{self.base_url}{path}",
                data=body_str.encode(),
                headers={
                    "Content-Type": "application/json",
                    "client-api-key": self.api_key,
                    "x-api-key": sign_body(self.api_key, body_str),
                },
                timeout=PROVIDER_TIMEOUT,
            )
        except Exception as e:
            logger.error(f"XPay POST {path} failed: {e}")
            return None

    def _get(self, path):
        try:
            return requests.get(
                f"{self.base_url}{path}",
                headers={
                    "client-api-key": self.api_key,
                    "x-api-key": sign_body(self.api_key, ""),
                },
                timeout=PROVIDER_TIMEOUT,
            )
        except Exception as e:
            logger.error(f"XPay GET {path} failed: {e}")
            return None

    # ── Создание платежа (PAYIN-FIAT) ───────────────────────────────────────────

    def create_invoice(self, order_id, amount, payment_method=None, user_id=None):
        if not self.api_key or not self.merchant_id:
            return {"error": "XPay: не настроены XPAY_API_KEY / XPAY_MERCHANT_ID"}

        if payment_method == "sbp":
            pay_type = XPAY_TYPE_SBP
        elif payment_method == "card":
            pay_type = XPAY_TYPE_CARD
        else:
            pay_type = XPAY_TYPE_DEFAULT

        body = {
            # timestamp — чтобы retry в PaymentService не ловил ORDER_ALREADY_EXISTS (409)
            "order_id": f"obsidian_{order_id}_{int(time.time())}",
            "amount": int(round(float(amount))),
            "type": pay_type,
            "merchant_id": self.merchant_id,
            "success_callback_url": f"{PUBLIC_RELAY}/xpay/webhook",
            "currency": "RUB",
        }
        if user_id:
            body["client_id"] = str(user_id)

        r = self._post("/merchant/createOrder", body)
        if r is None:
            return {"error": "XPay недоступен (сеть)"}
        try:
            data = r.json()
        except Exception:
            return {"error": f"XPay HTTP {r.status_code}: не-JSON ответ"}
        if r.status_code != 200 or not data.get("ok"):
            msg = data.get("message") or f"HTTP {r.status_code}"
            logger.error(f"XPay create error {r.status_code}: {r.text[:300]} | "
                         f"amount={amount} type={pay_type}")
            return {"error": f"XPay: {msg}"}

        details = data.get("payment_details") or {}
        address = details.get("address") or ""
        det_type = details.get("type") or pay_type
        requisites = {}
        if address.startswith("http"):
            # nspk / qr-методы отдают ссылку
            requisites["payment_link"] = address
        elif det_type in ("sim", "sngs", "simcard"):
            requisites["phone"] = address
        else:
            requisites["card_number"] = address
        if details.get("bank"):
            requisites["bank_name"] = details["bank"]
        if details.get("holder_name"):
            requisites["recipient"] = details["holder_name"]

        # payment_details.amount — ФИНАЛЬНАЯ сумма к оплате: XPay может сдвинуть её
        # для уникализации (матчинг банковских уведомлений) — показывать клиенту её
        try:
            final_amount = float(details.get("amount") or amount)
        except (TypeError, ValueError):
            final_amount = float(amount)
        if abs(final_amount - float(amount)) > 0.004:
            logger.info(f"XPay уникализация суммы: {amount} → {final_amount} (order {order_id})")

        raw = dict(data)
        raw["requisites"] = requisites
        raw["amount_rub"] = final_amount  # бот берёт сумму к оплате отсюда
        return {
            # internal_id (lux…) — ключ для GET /merchant/order/{id}
            "invoice_id": data.get("id"),
            "amount": final_amount,
            "status": _STATUS_MAP.get(data.get("status"), "awaiting_payment"),
            "qr_payload": requisites.get("payment_link"),
            "banks": [],
            "raw": raw,
        }

    # ── Статус платежа ──────────────────────────────────────────────────────────

    def get_status(self, invoice_id):
        if not invoice_id:
            return {"status": "unknown"}
        r = self._get(f"/merchant/order/{invoice_id}")
        if r is None:
            return {"status": "unknown"}
        try:
            data = r.json()
        except Exception:
            return {"status": "unknown"}
        if r.status_code != 200 or not data.get("ok"):
            logger.warning(f"XPay get_status {invoice_id}: {r.status_code} {r.text[:200]}")
            return {"status": "unknown"}
        status = data.get("status")
        return {"status": _STATUS_MAP.get(status, status or "unknown"),
                "raw_status": status, "raw": data}

    # ── Баланс (для мониторинга) ────────────────────────────────────────────────

    def get_balance(self):
        r = self._get(f"/merchant/balance/{self.merchant_id}")
        if r is None or r.status_code != 200:
            return None
        try:
            # приходит строкой: {"balance": "0.00", ...}
            return float(r.json().get("balance"))
        except Exception:
            return None

    # ── Прочие обязательные методы ─────────────────────────────────────────────

    def get_payment_methods(self, invoice_id):
        return []

    def parse_webhook(self, data):
        """Вебхук приходит только при success; order_id = наш external_id."""
        external = data.get("order_id", "") or ""
        order_id = None
        if external.startswith("obsidian_"):
            order_id = external.split("_")[1]
        status = _STATUS_MAP.get(data.get("status"), "unknown")
        return order_id, status
