import sqlite3, logging, time, threading, os

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')

def start_polling_service():
    """Запускает фоновую проверку статусов сессий (для будущего использования)."""
    def poll():
        while True:
            try:
                conn = sqlite3.connect(DB_PATH, timeout=5)
                c = conn.cursor()
                c.execute("SELECT session_token, provider_invoice_id FROM payment_sessions WHERE status IN ('invoice_created', 'awaiting_payment')")
                rows = c.fetchall()
                conn.close()
                for token, invoice_id in rows:
                    # Пока провайдер не умеет проверять статус, просто заглушка
                    pass
            except Exception as e:
                logging.error(f"Polling error: {e}")
            time.sleep(15)

    thread = threading.Thread(target=poll, daemon=True)
    thread.start()
    logging.info("Polling service started")
