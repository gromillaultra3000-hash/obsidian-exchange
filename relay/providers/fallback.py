from providers.base import PaymentProvider
class FallbackProvider(PaymentProvider):
    def create_invoice(self, order_id, amount, payment_method=None):
        return {"error": "Fallback provider not configured"}
    def get_status(self, invoice_id):
        return {"status": "unknown"}
    def get_payment_methods(self, invoice_id):
        return []
    def parse_webhook(self, data):
        return None, None
