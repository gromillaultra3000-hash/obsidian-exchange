import sqlite3, logging, time, threading, os
from datetime import datetime, timedelta

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')

def start_polling_service():
    """Запускает умную фоновую проверку статусов сессий с приоритетами."""
    def poll():
        while True:
            try:
                conn = sqlite3.connect(DB_PATH, timeout=5)
                c = conn.cursor()
                
                # Выбираем сессии, ожидающие оплаты
                c.execute("SELECT session_token, provider_invoice_id, created_at, expires_at FROM payment_sessions WHERE status IN ('invoice_created', 'awaiting_payment')")
                rows = c.fetchall()
                conn.close()

                now = datetime.now()
                for token, invoice_id, created_str, expires_str in rows:
                    if not created_str:
                        continue
                    created = datetime.strptime(created_str, '%Y-%m-%d %H:%M:%S')

                    # Экспирация — ТОЛЬКО по собственному expires_at сессии.
                    # Раньше здесь стоял жёсткий порог 900 с: сессия с окном 30 мин
                    # убивалась на 15-й минуте, у клиента пропадала кнопка «я оплатил»,
                    # и оплата уходила трейдеру без подтверждения провайдеру.
                    if expires_str:
                        try:
                            expires = datetime.strptime(expires_str, '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            expires = created + timedelta(minutes=30)
                    else:
                        expires = created + timedelta(minutes=30)

                    if now >= expires:
                        conn = sqlite3.connect(DB_PATH, timeout=5)
                        c = conn.cursor()
                        c.execute(
                            "UPDATE payment_sessions SET status='expired', "
                            "updated_at=datetime('now') WHERE session_token=?", (token,))
                        conn.commit()
                        conn.close()
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
