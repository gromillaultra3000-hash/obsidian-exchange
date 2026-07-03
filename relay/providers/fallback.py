import os, sys
sys.path.insert(0, '/root/relay')
from providers.brabus import BrabusProvider
from providers.base import PaymentProvider

class FallbackProvider(PaymentProvider):
    """Резервный провайдер — Brabus T-Bank deeplink."""
    def __init__(self):
        self._provider = BrabusProvider(variant="tbank_deeplink")

    def create_invoice(self, order_id, amount, payment_method=None):
        return self._provider.create_invoice(order_id, amount, payment_method)

    def get_status(self, invoice_id):
        return self._provider.get_status(invoice_id)

    def parse_webhook(self, data):
        return self._provider.parse_webhook(data)

    def get_payment_methods(self, invoice_id):
        return []
