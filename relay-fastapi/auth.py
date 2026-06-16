"""Аутентификация личных кабинетов ObsidianExchange (email/пароль + сессии + 2FA)."""
import os
import sqlite3
import secrets
import re
import hmac
import hashlib
import time
from datetime import datetime, timedelta

import bcrypt
import pyotp

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
SESSION_COOKIE = 'oe_session'
SESSION_TTL_DAYS = 30

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _conn():
    return sqlite3.connect(DB_PATH, timeout=5)


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ''))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def get_user_by_email(email: str):
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT id, email, password_hash, telegram_id, telegram_username, totp_secret, totp_enabled FROM web_users WHERE email=?", (email,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "email": row[1], "password_hash": row[2], "telegram_id": row[3],
            "telegram_username": row[4], "totp_secret": row[5], "totp_enabled": bool(row[6])}


def get_user_by_id(user_id: int):
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT id, email, telegram_id, telegram_username, totp_secret, totp_enabled FROM web_users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "email": row[1], "telegram_id": row[2], "telegram_username": row[3],
            "totp_secret": row[4], "totp_enabled": bool(row[5])}


def create_user(email: str, password: str) -> int:
    conn = _conn()
    c = conn.cursor()
    c.execute("INSERT INTO web_users (email, password_hash) VALUES (?, ?)", (email, hash_password(password)))
    conn.commit()
    user_id = c.lastrowid
    conn.close()
    return user_id


def create_session(web_user_id: int):
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(16)
    expires_at = (datetime.now() + timedelta(days=SESSION_TTL_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    conn = _conn()
    conn.execute(
        "INSERT INTO web_sessions (token, web_user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
        (token, web_user_id, csrf_token, expires_at)
    )
    conn.commit()
    conn.close()
    return token, csrf_token


def destroy_session(token: str):
    conn = _conn()
    conn.execute("DELETE FROM web_sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


def get_web_user(request):
    """Возвращает данные текущего пользователя личного кабинета по cookie сессии, либо None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        SELECT u.id, u.email, u.telegram_id, u.telegram_username, s.csrf_token, u.totp_enabled
        FROM web_sessions s
        JOIN web_users u ON u.id = s.web_user_id
        WHERE s.token = ? AND s.expires_at > datetime('now')
    """, (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0],
        "email": row[1],
        "telegram_id": row[2],
        "telegram_username": row[3],
        "csrf_token": row[4],
        "session_token": token,
        "totp_enabled": bool(row[5]),
    }


def set_session_cookie(response, token: str):
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True, secure=True, samesite='lax', path='/',
    )


def clear_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path='/')


def verify_csrf(web_user: dict, form_token: str) -> bool:
    return bool(web_user) and bool(form_token) and secrets.compare_digest(web_user.get('csrf_token', ''), form_token or '')


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name="ObsidianExchange")


def verify_totp_code(secret: str, code: str) -> bool:
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False


def enable_totp(user_id: int, secret: str):
    conn = _conn()
    conn.execute("UPDATE web_users SET totp_secret=?, totp_enabled=1 WHERE id=?", (secret, user_id))
    conn.commit()
    conn.close()


def disable_totp(user_id: int):
    conn = _conn()
    conn.execute("UPDATE web_users SET totp_secret=NULL, totp_enabled=0 WHERE id=?", (user_id,))
    conn.commit()
    conn.close()


_TOTP_STEP_SECRET = os.getenv('INTERNAL_ADMIN_SECRET', secrets.token_hex(16))


def make_totp_step_token(user_id: int) -> str:
    """Подписанный токен для второго шага логина (после пароля, до TOTP)."""
    ts = str(int(time.time()))
    payload = f"{user_id}:{ts}"
    sig = hmac.new(_TOTP_STEP_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{payload}:{sig}"


def verify_totp_step_token(token: str) -> int | None:
    """Возвращает user_id если токен действителен (≤5 мин), иначе None."""
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id, ts, sig = parts
        payload = f"{user_id}:{ts}"
        expected_sig = hmac.new(_TOTP_STEP_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(expected_sig, sig):
            return None
        if time.time() - int(ts) > 300:
            return None
        return int(user_id)
    except Exception:
        return None


def verify_telegram_login_widget(data: dict, bot_token: str):
    """Проверяет подпись данных Telegram Login Widget (HMAC-SHA256 с SHA256(bot_token) как ключом).

    Возвращает словарь данных пользователя при успехе, иначе None.
    """
    if not bot_token:
        return None
    data = dict(data)
    received_hash = data.pop('hash', None)
    if not received_hash:
        return None
    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None
    try:
        auth_date = int(data.get('auth_date', 0))
    except (TypeError, ValueError):
        return None
    if time.time() - auth_date > 86400:
        return None
    return data
