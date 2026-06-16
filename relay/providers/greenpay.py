import hmac, hashlib, time, uuid, os, json, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

GREENPAY_BASE_URL = os.getenv('GREENPAY_BASE_URL', 'https://greenpay.win/api/v1')
GREENPAY_SHOP_API_KEY = os.getenv('GREENPAY_SHOP_API_KEY', '')
GREENPAY_API_SECRET = os.getenv('GREENPAY_API_SECRET', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')


class GreenPayProvider(PaymentProvider):
    def __init__(self):
        self.base_url = GREENPAY_BASE_URL.rstrip('/')
        self.api_key = GREENPAY_SHOP_API_KEY
        self.api_secret = GREENPAY_API_SECRET

    def _sign(self, body: bytes) -> str:
        return hmac.new(self.api_secret.encode(), body, hashlib.sha256).hexdigest()

    def _headers(self, body: bytes) -> dict:
        return {
            "X-Shop-API-Key": self.api_key,
            "X-Signature": self._sign(body),
            "X-Timestamp": str(int(time.time() * 1000)),
            "X-Nonce": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    def create_invoice(self, order_id, amount, payment_method=None):
        payment_method = payment_method or 'sbp'
        transaction_id = f"obsidian_{order_id}"
        payload = {
            "transaction_id": transaction_id,
            "payment_method": payment_method,
            "amount": str(amount),
            "currency": "RUB",
            "callback_url": f"{PUBLIC_RELAY}/greenpay/webhook",
            "additional_info": {"order_id": order_id},
            "kyc": False,
        }
        body = json.dumps(payload).encode()
        try:
            r = requests.post(
                f"{self.base_url}/requisites/request/",
                data=body,
                headers=self._headers(body),
                timeout=PROVIDER_TIMEOUT,
            )
            if r.status_code in (200, 201):
                data = r.json()
                logger.info(f"GreenPay requisites response for order {order_id}: {data}")
                if data.get("success") is False:
                    return {"error": data.get("error", "GreenPay: success=false")}
                return {
                    "invoice_id": data.get("id") or data.get("transaction_id") or transaction_id,
                    "amount": amount,
                    "status": "awaiting_payment",
                    "qr_payload": None,
                    "banks": [],
                    "raw": data,
                }
            else:
                logger.error(f"GreenPay error {r.status_code}: {r.text}")
                return {"error": f"GreenPay error: {r.status_code}"}
        except Exception as e:
            logger.error(f"GreenPay request failed: {e}")
            return {"error": str(e)}

    def get_status(self, invoice_id):
        body = b''
        try:
            r = requests.get(
                f"{self.base_url}/transactions/{invoice_id}/",
                headers=self._headers(body),
                timeout=PROVIDER_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                return {"status": data.get("status", "unknown"), "raw": data}
            return {"status": "unknown"}
        except Exception as e:
            logger.error(f"GreenPay status check failed: {e}")
            return {"status": "unknown"}

    def get_payment_methods(self, invoice_id):
        return []

    def parse_webhook(self, data):
        external_id = data.get('external_id', '') or ''
        order_id = None
        if external_id.startswith('obsidian_'):
            order_id = external_id.split('_', 1)[1]
        if not order_id:
            order_id = (data.get('additional_info') or {}).get('order_id')
        status = data.get('status')
        normalized_status = 'paid' if status == 'success' else status
        if order_id and normalized_status:
            return order_id, normalized_status
        return None, None
