import sqlite3, logging, time, threading, os

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')

def start_payout_worker():
    """Обрабатывает очередь выплат (пока заглушка, так как выплаты идут через бота)."""
    def worker():
        while True:
            try:
                conn = sqlite3.connect(DB_PATH, timeout=5)
                c = conn.cursor()
                c.execute("SELECT id, order_id, amount, currency, address FROM payout_queue WHERE status='pending' AND retry_count < 3")
                rows = c.fetchall()
                conn.close()
                
                for job_id, order_id, amount, currency, address in rows:
                    # Здесь будет вызов process_payout из бота
                    # Пока просто логируем
                    logging.info(f"Payout worker: processing order #{order_id} for {amount} {currency} to {address}")
                    # Обновляем статус (заглушка)
                    conn = sqlite3.connect(DB_PATH, timeout=5)
                    c = conn.cursor()
                    c.execute("UPDATE payout_queue SET status='processed', updated_at=datetime('now') WHERE id=?", (job_id,))
                    conn.commit()
                    conn.close()
                
                time.sleep(5)
            except Exception as e:
                logging.error(f"Payout worker error: {e}")
                time.sleep(5)
    
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    logging.info("Payout worker started")
