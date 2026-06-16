from abc import ABC, abstractmethod

class PaymentProvider(ABC):
    @abstractmethod
    def create_invoice(self, order_id, amount, payment_method=None):
        """Создаёт инвойс в платёжной системе. Возвращает нормализованный словарь."""
        pass

    @abstractmethod
    def get_status(self, invoice_id):
        """Возвращает текущий статус инвойса."""
        pass

    @abstractmethod
    def get_payment_methods(self, invoice_id):
        """Возвращает список доступных методов оплаты (банков)."""
        pass

    @abstractmethod
    def parse_webhook(self, data):
        """Обрабатывает данные вебхука и возвращает (order_id, status)."""
        pass
