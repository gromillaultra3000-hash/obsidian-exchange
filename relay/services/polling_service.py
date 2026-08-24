import logging, time, threading, os
from datetime import datetime, timedelta, timezone
from repositories.payment_session_store import from_environment as payment_session_store

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')

def start_polling_service():
    """Запускает умную фоновую проверку статусов сессий с приоритетами."""
    def poll():
        sessions = payment_session_store(sqlite_path=DB_PATH)
        while True:
            try:
                rows = sessions.active()

                now = datetime.now(timezone.utc)
                for row in rows:
                    token, invoice_id = row['session_token'], row['provider_invoice_id']
                    created_str, expires_str = row['created_at'], row['expires_at']
                    if not created_str:
                        continue
                    created = (created_str if isinstance(created_str, datetime) else
                               datetime.strptime(created_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc))

                    # Экспирация — ТОЛЬКО по собственному expires_at сессии.
                    # Раньше здесь стоял жёсткий порог 900 с: сессия с окном 30 мин
                    # убивалась на 15-й минуте, у клиента пропадала кнопка «я оплатил»,
                    # и оплата уходила трейдеру без подтверждения провайдеру.
                    if expires_str:
                        try:
                            expires = (expires_str if isinstance(expires_str, datetime) else
                                       datetime.strptime(expires_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc))
                        except (ValueError, TypeError):
                            expires = created + timedelta(minutes=30)
                    else:
                        expires = created + timedelta(minutes=30)

                    if now >= expires:
                        sessions.expire(token)
                        continue
                    
                    # Пока нет реальной проверки статуса (нужен API провайдера)
                    # Здесь будет вызов provider.get_status(invoice_id)
                    
                time.sleep(10)  # базовый интервал опроса
            except Exception as e:
                logging.error(f"Polling error: {e}")
                time.sleep(10)
    
    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    logging.info("Smart polling service started")
