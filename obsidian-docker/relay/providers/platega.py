import requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT

class PlategaProvider(PaymentProvider):
    def __init__(self):
        self.proxy_url = "http://5.206.224.157:5003/platega/invoice"

    def create_invoice(self, order_id, amount):
        try:
            r = requests.post(
                self.proxy_url,
                json={"order_id": order_id, "amount": str(amount)},
                timeout=PROVIDER_TIMEOUT
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "invoice_id": data.get("transactionId"),
                    "amount": amount,
                    "status": "awaiting_payment",
                    "qr_payload": data.get("url"),
                    "banks": data.get("banks", []),
                    "raw": data
                }
            else:
                return {"error": f"Proxy error: {r.status_code}"}
        except Exception as e:
            return {"error": str(e)}

    def get_status(self, invoice_id):
        # Пока не реализовано, т.к. Platega-прокси не предоставляет статус
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
