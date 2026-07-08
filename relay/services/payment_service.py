import sqlite3, os, time
from datetime import datetime, timedelta
from providers.fallback import FallbackProvider
from utils.tokens import generate_session_token
from utils.logger import get_logger
from services.state_machine import PaymentStateMachine
from services.smart_router import choose_provider, record_outcome, get_health_scores

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
logger = get_logger(__name__)

class PaymentService:
    def __init__(self, provider=None, amount=None):
        if provider is None:
            provider_name = choose_provider(amount or 10000)
            self.provider = self._load_provider(provider_name)
        else:
            self.provider = provider

    def _load_provider(self, name: str):
        """Загружает провайдер по имени класса."""
        try:
            if name == 'BrabusProvider':
                from providers.brabus import BrabusProvider
                return BrabusProvider()
            elif name == 'MonteraProvider':
                from providers.montera import MonteraProvider
                return MonteraProvider()
            elif name == 'GreenPayProvider':
                from providers.greenpay import GreenPayProvider
                return GreenPayProvider()
            elif name == 'LavaProvider':
                from providers.lava import LavaProvider
                return LavaProvider()
            elif name == 'VertuProvider':
                from providers.vertu import VertuProvider
                return VertuProvider()
            else:
                from providers.fallback import FallbackProvider
                return FallbackProvider()
        except Exception as e:
            logger.warning(f"Failed to load {name}: {e}, using Fallback")
            from providers.fallback import FallbackProvider
            return FallbackProvider()

    def create_session(self, order_id, amount, client_ip=None, user_agent=None, telegram_id=None, payment_method=None):
        token = generate_session_token()
        expires_at = (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Попытка создать инвойс с retry — для P2P-агрегаторов (Brabus/Montera/GreenPay)
        # окно доступности конкретного реквизита у трейдера может быть очень коротким,
        # поэтому даём больше попыток с увеличенной паузой, прежде чем уходить в fallback.
        max_retries = 3
        invoice = None
        last_error = None
        for attempt in range(max_retries):
            start_time = time.time()
            extra = {}
            if self.provider.__class__.__name__ in ('MonteraProvider', 'VertuProvider'):
                extra['user_id'] = telegram_id
            invoice = self.provider.create_invoice(order_id, amount, payment_method=payment_method, **extra)
            elapsed = time.time() - start_time

            # Обновляем метрики здоровья провайдера через smart_router
            success = 'error' not in invoice
            record_outcome(self.provider.__class__.__name__, success, elapsed)

            if 'error' not in invoice:
                break
            last_error = invoice['error']
            logger.warning(f"Попытка {attempt+1}/{max_retries} для order {order_id} не удалась: {last_error}")
            if attempt < max_retries - 1:
                time.sleep(2.5)  # пауза перед повторной попыткой
        
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
            if self.provider.__class__.__name__ == 'BrabusProvider':
                # Сохраняем вариант для корректного cancel при истечении заявки
                provider_name = f'brabus:{getattr(self.provider, "variant", "tbank_deeplink")}'
            else:
                provider_names = {'PlategaProvider': 'platega', 'GreenPayProvider': 'greenpay',
                                  'MonteraProvider': 'montera', 'LavaProvider': 'lava',
                                  'VertuProvider': 'vertu'}
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


    def get_provider_status(self) -> dict:
        """Возвращает health scores всех провайдеров из smart_router."""
        return get_health_scores()

