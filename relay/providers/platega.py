import os
import requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT

PLATEGA_BASE_URL = "https://app.platega.io"


class PlategaProvider(PaymentProvider):
    def __init__(self):
        self.merchant_id = os.getenv('PLATEGA_MERCHANT_ID')
        self.secret = os.getenv('PLATEGA_SECRET_KEY') or os.getenv('PLATEGA_SECRET')

    def _headers(self):
        return {
            'X-MerchantId': self.merchant_id,
            'X-Secret': self.secret,
            'Content-Type': 'application/json'
        }

    def create_invoice(self, order_id, amount, payment_method=None):
        try:
            payload = {
                "paymentMethod": 2,  # СБП (QR-код)
                "paymentDetails": {"amount": float(amount), "currency": "RUB"},
                "description": f"Order #{order_id}",
                "return": "https://obsidian-exchange.org/success",
                "failedUrl": "https://obsidian-exchange.org/fail"
            }
            r = requests.post(
                f"{PLATEGA_BASE_URL}/transaction/process",
                json=payload, headers=self._headers(), timeout=PROVIDER_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "invoice_id": data.get("transactionId"),
                    "amount": amount,
                    "status": "awaiting_payment",
                    "qr_payload": data.get("redirect"),
                    "banks": data.get("banks", []),
                    "raw": data
                }
            else:
                return {"error": f"Platega error: {r.status_code} {r.text[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def get_status(self, invoice_id):
        # Не реализовано: Platega пока не используется для авто-проверки статуса
        return {"status": "unknown"}

    def get_payment_methods(self, invoice_id):
        # Возвращаем заглушку банков (можно доработать позже)
        return [
            {"name": "Сбер", "code": "sber"},
            {"name": "Т-Банк", "code": "tbank"},
            {"name": "Альфа", "code": "alfa"},
            {"name": "ВТБ", "code": "vtb"},
        ]

    def parse_webhook(self, data):
        order_id = data.get('order_id')
        status = data.get('status')
        if order_id and status:
            return order_id, status
        return None, None
