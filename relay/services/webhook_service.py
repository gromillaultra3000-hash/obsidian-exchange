import json, logging, os
from services.payment_service import PaymentService

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv('RELAY_SECRET', 'fallback')

class WebhookService:
    def __init__(self):
        self.payment_service = PaymentService()

    def handle_platega_webhook(self, data):
        """
        Обрабатывает вебхук от Platega.
        Ожидаемый формат: {"order_id": "...", "status": "paid", "key": "..."}
        Возвращает (success: bool, message: str)
        """
        try:
            if data.get('key') != SECRET_KEY:
                return False, "Forbidden: invalid key"

            order_id = data.get('order_id')
            status = data.get('status')
            if not order_id or not status:
                return False, "Missing order_id or status"

            # Обновляем статус заказа в базе (старый механизм)
            import sqlite3, os
            DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
            conn = sqlite3.connect(DB_PATH, timeout=5)
            c = conn.cursor()
            if status == 'paid':
                c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()
            conn.close()

            # Пытаемся найти связанную сессию и обновить её статус
            conn = sqlite3.connect(DB_PATH, timeout=5)
            c = conn.cursor()
            c.execute("SELECT session_token FROM payment_sessions WHERE order_id=?", (order_id,))
            session_row = c.fetchone()
            conn.close()
            if session_row:
                self.payment_service.update_status(session_row[0], 'paid')

            logger.info(f"Webhook processed: order #{order_id} -> {status}")
            return True, f"Order #{order_id} updated to {status}"
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return False, str(e)
