import os, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

MONTERA_BASE_URL = os.getenv('MONTERA_BASE_URL', 'https://montera.one/api')
MONTERA_API_TOKEN = os.getenv('MONTERA_API_TOKEN', '')
MONTERA_MERCHANT_ID = os.getenv('MONTERA_MERCHANT_ID', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')


class MonteraProvider(PaymentProvider):
    def __init__(self):
        self.base_url = MONTERA_BASE_URL.rstrip('/')
        self.api_token = MONTERA_API_TOKEN
        self.merchant_id = MONTERA_MERCHANT_ID

    def _headers(self):
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Access-Token": self.api_token,
        }

    def create_invoice(self, order_id, amount, payment_method=None):
        detail_type = "phone" if payment_method == "sbp" else "card"
        payload = {
            "external_id": f"obsidian_{order_id}",
            "amount": int(round(float(amount))),
            "currency": "rub",
            "payment_detail_type": detail_type,
            "merchant_id": self.merchant_id,
            "callback_url": f"{PUBLIC_RELAY}/montera/webhook",
        }
        try:
            r = requests.post(
                f"{self.base_url}/h2h/order",
                json=payload, headers=self._headers(), timeout=PROVIDER_TIMEOUT,
            )
            data = r.json()
            if r.status_code != 200 or not data.get("success"):
                logger.error(f"Montera error {r.status_code}: {data}")
                return {"error": data.get("message") or f"Montera error: {r.status_code}"}

            inner = data.get("data", {})
            detail = inner.get("payment_detail") or {}
            requisites = {}
            if detail.get("detail_type") == "phone":
                requisites["phone"] = detail.get("detail")
            else:
                requisites["card_number"] = detail.get("detail")
            if inner.get("payment_gateway_name"):
                requisites["bank_name"] = inner["payment_gateway_name"]
            if detail.get("initials"):
                requisites["recipient"] = detail["initials"]

            raw = dict(inner)
            raw["requisites"] = requisites
            return {
                "invoice_id": inner.get("order_id"),
                "amount": amount,
                "status": "awaiting_payment",
                "qr_payload": None,
                "banks": [],
                "raw": raw,
            }
        except Exception as e:
            logger.error(f"Montera request failed: {e}")
            return {"error": str(e)}

    def get_status(self, invoice_id):
        try:
            r = requests.get(
                f"{self.base_url}/h2h/order/{invoice_id}",
                headers=self._headers(), timeout=PROVIDER_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                inner = data.get("data", {})
                status = inner.get("status")
                normalized = "paid" if status == "success" else ("failed" if status == "fail" else status)
                return {"status": normalized or "unknown", "raw": inner}
            return {"status": "unknown"}
        except Exception as e:
            logger.error(f"Montera status check failed: {e}")
            return {"status": "unknown"}

    def get_payment_methods(self, invoice_id):
        return []

    def parse_webhook(self, data):
        external_id = data.get('external_id', '') or ''
        order_id = None
        if external_id.startswith('obsidian_'):
            order_id = external_id.split('_', 1)[1]
        status = data.get('status')
        normalized_status = 'paid' if status == 'success' else status
        if order_id and normalized_status:
            return order_id, normalized_status
        return None, None
