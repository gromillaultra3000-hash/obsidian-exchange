import time
from collections import defaultdict

# Простейший rate limiter (в памяти)
class RateLimiter:
    def __init__(self, max_requests=60, window=60):
        self.max_requests = max_requests
        self.window = window
        self.requests = defaultdict(list)

    def is_allowed(self, client_ip):
        now = time.time()
        # Очищаем старые записи
        self.requests[client_ip] = [t for t in self.requests[client_ip] if now - t < self.window]
        if len(self.requests[client_ip]) >= self.max_requests:
            return False
        self.requests[client_ip].append(now)
        return True

# Глобальный экземпляр
rate_limiter = RateLimiter(max_requests=60, window=60)

def check_session_token(token):
    """Проверяет, что токен существует и не истёк."""
    import sqlite3, os
    from datetime import datetime, timedelta
    DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT created_at FROM payment_sessions WHERE session_token=?", (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    created = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
    # Токен действителен 30 минут
    return datetime.now() - created < timedelta(minutes=30)
