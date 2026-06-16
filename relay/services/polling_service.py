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
                c.execute("SELECT session_token, provider_invoice_id, created_at FROM payment_sessions WHERE status IN ('invoice_created', 'awaiting_payment')")
                rows = c.fetchall()
                conn.close()
                
                now = datetime.now()
                for token, invoice_id, created_str in rows:
                    if not created_str:
                        continue
                    created = datetime.strptime(created_str, '%Y-%m-%d %H:%M:%S')
                    age_seconds = (now - created).total_seconds()
                    
                    # Приоритетная очередь: первые 3 минуты — каждые 10 секунд
                    if age_seconds <= 180:
                        interval = 10
                    elif age_seconds <= 900:  # 15 минут
                        interval = 30
                    else:
                        # Экспирация — помечаем как expired
                        conn = sqlite3.connect(DB_PATH, timeout=5)
                        c = conn.cursor()
                        c.execute("UPDATE payment_sessions SET status='expired' WHERE session_token=?", (token,))
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
