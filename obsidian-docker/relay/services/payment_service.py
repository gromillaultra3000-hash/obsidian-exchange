import sqlite3, os
from utils.logger import get_logger
from datetime import datetime
from providers.platega import PlategaProvider
from providers.fallback import FallbackProvider
from utils.tokens import generate_session_token

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')

logger = get_logger(__name__)

class PaymentService:
    def __init__(self, provider=None):
        # По умолчанию используется PlategaProvider, но можно передать другого
        self.provider = provider if provider else PlategaProvider()

    def create_session(self, order_id, amount):
        """
        Создаёт payment session и инвойс через провайдера.
        Возвращает словарь с информацией о сессии.
        """
        token = generate_session_token()
        logger.info(f"Creating payment session for order {order_id}")

        # Сначала создаём запись в БД со статусом 'created'
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute(
            "INSERT INTO payment_sessions (session_token, order_id, amount, provider, status) VALUES (?, ?, ?, ?, 'created')",
            (token, order_id, amount, self.provider.__class__.__name__.replace('Provider', '').lower())
        )
        conn.commit()

        # Создаём инвойс через провайдера
        invoice = self.provider.create_invoice(order_id, amount)

        if 'error' in invoice:
            # Если провайдер вернул ошибку, помечаем сессию как failed
            c.execute(
                "UPDATE payment_sessions SET status='failed', updated_at=datetime('now') WHERE session_token=?",
                (token,)
            )
            conn.commit()
            conn.close()
            return {"error": invoice['error']}

        # Обновляем сессию данными от провайдера
        c.execute(
            "UPDATE payment_sessions SET provider_invoice_id=?, qr_payload=?, provider_payload=?, status='invoice_created', updated_at=datetime('now') WHERE session_token=?",
            (invoice.get('invoice_id'), invoice.get('qr_payload'), str(invoice.get('raw', {})), token)
        )
        conn.commit()
        conn.close()

        return {
            "session_token": token,
            "invoice_id": invoice.get('invoice_id'),
            "qr_payload": invoice.get('qr_payload'),
            "banks": invoice.get('banks', []),
            "amount": amount
        }

    def get_session(self, token):
        """Возвращает полную информацию о сессии по токену."""
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("SELECT * FROM payment_sessions WHERE session_token=?", (token,))
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        columns = [desc[0] for desc in c.description]
        return dict(zip(columns, row))

    def update_status(self, token, new_status):
        """Обновляет статус сессии."""
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute(
            "UPDATE payment_sessions SET status=?, updated_at=datetime('now') WHERE session_token=?",
            (new_status, token)
        )
        conn.commit()
        conn.close()
        return True

    def get_payment_methods(self, token):
        """Возвращает список доступных банков для сессии."""
        session = self.get_session(token)
        if not session:
            return []
        # Если есть данные о банках в provider_payload, используем их,
        # иначе запрашиваем у провайдера
        if session.get('provider_invoice_id'):
            return self.provider.get_payment_methods(session['provider_invoice_id'])
        return []
