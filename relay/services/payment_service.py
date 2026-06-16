import sqlite3, os, time
from datetime import datetime, timedelta
from providers.platega import PlategaProvider
from providers.fallback import FallbackProvider
from utils.tokens import generate_session_token
from utils.logger import get_logger
from services.state_machine import PaymentStateMachine

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
logger = get_logger(__name__)

class PaymentService:
    def __init__(self, provider=None):
        self.provider = provider if provider else PlategaProvider()

    def create_session(self, order_id, amount, client_ip=None, user_agent=None, telegram_id=None, payment_method=None):
        token = generate_session_token()
        expires_at = (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Попытка создать инвойс с retry (до 2 попыток)
        max_retries = 2
        invoice = None
        last_error = None
        for attempt in range(max_retries):
            start_time = time.time()
            invoice = self.provider.create_invoice(order_id, amount, payment_method=payment_method)
            elapsed = time.time() - start_time
            
            # Обновляем метрики здоровья провайдера
            self._update_health_metrics(self.provider.__class__.__name__, elapsed, 'error' in invoice)
            
            if 'error' not in invoice:
                break
            last_error = invoice['error']
            logger.warning(f"Попытка {attempt+1}/{max_retries} для order {order_id} не удалась: {last_error}")
            time.sleep(1)  # пауза перед повторной попыткой
        
        if invoice is None or 'error' in invoice:
            logger.error(f"Все попытки создать инвойс для order {order_id} не удались")
            invoice = invoice or {"error": last_error or "Unknown error"}
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()

        if 'error' in invoice:
            logger.warning(f"Основной провайдер {self.provider.__class__.__name__} недоступен: {invoice['error']}. Пробуем fallback.")
            fallback = FallbackProvider()
            invoice = fallback.create_invoice(order_id, amount, payment_method=payment_method)
            if 'error' in invoice:
                logger.error(f"Fallback также не сработал: {invoice['error']}")
                c.execute("INSERT INTO payment_sessions (session_token, order_id, amount, provider, status) VALUES (?,?,?,?,'failed')",
                          (token, order_id, amount, 'fallback'))
                conn.commit()
                conn.close()
                return {"error": "All providers failed"}
            provider_name = 'fallback'
        else:
            provider_names = {'PlategaProvider': 'platega', 'GreenPayProvider': 'greenpay', 'MonteraProvider': 'montera'}
            provider_name = provider_names.get(self.provider.__class__.__name__, 'platega')

        c.execute("INSERT INTO payment_sessions (session_token, order_id, amount, provider, status, expires_at, client_ip, user_agent, telegram_id) VALUES (?,?,?,?,'invoice_created',?,?,?,?)",
                  (token, order_id, amount, provider_name, expires_at, client_ip, user_agent, telegram_id))
        c.execute("UPDATE payment_sessions SET provider_invoice_id=?, qr_payload=?, provider_payload=?, updated_at=datetime('now') WHERE session_token=?",
                  (invoice.get('invoice_id'), invoice.get('qr_payload'), str(invoice.get('raw', {})), token))
        conn.commit()
        conn.close()

        logger.info(f"Session {token} created for order {order_id}")
        return {
            "session_token": token,
            "invoice_id": invoice.get('invoice_id'),
            "qr_payload": invoice.get('qr_payload'),
            "banks": invoice.get('banks', []),
            "amount": amount,
            "raw": invoice.get('raw', {})
        }

    def get_session(self, token):
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
        session = self.get_session(token)
        if not session:
            return False
        current_status = session['status']
        try:
            PaymentStateMachine.transition(current_status, new_status)
        except ValueError as e:
            logger.error(f"Invalid state transition: {e}")
            return False
        
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("UPDATE payment_sessions SET status=?, updated_at=datetime('now') WHERE session_token=?",
                  (new_status, token))
        conn.commit()
        conn.close()
        return True

    def get_payment_methods(self, token):
        session = self.get_session(token)
        if not session:
            return []
        return self.provider.get_payment_methods(session.get('provider_invoice_id'))


    def _update_health_metrics(self, provider_name, response_time, is_error):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5)
            c = conn.cursor()
            c.execute("SELECT avg_response_time, failed_count FROM provider_health WHERE provider=?", (provider_name,))
            row = c.fetchone()
            if row:
                # Обновляем скользящее среднее
                new_avg = (row[0] * 0.9 + response_time * 0.1) if row[0] else response_time
                new_failed = row[1] + (1 if is_error else 0)
                c.execute("UPDATE provider_health SET avg_response_time=?, failed_count=?, last_checked=datetime('now'), is_healthy=? WHERE provider=?",
                          (round(new_avg, 3), new_failed, 0 if new_failed > 5 else 1, provider_name))
            else:
                c.execute("INSERT INTO provider_health (provider, avg_response_time, failed_count, last_checked, is_healthy) VALUES (?,?,?,datetime('now'),?)",
                          (provider_name, response_time, 1 if is_error else 0, 0 if is_error else 1))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Ошибка обновления метрик здоровья: {e}")

