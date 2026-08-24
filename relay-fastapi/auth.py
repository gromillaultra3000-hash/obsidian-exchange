"""Аутентификация личных кабинетов ObsidianExchange (email/пароль + сессии + 2FA)."""
import os
import secrets
import re
import hmac
import hashlib
import time
from pathlib import Path
import sys
from datetime import datetime, timedelta

import bcrypt
import pyotp

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
RELAY_PATH = str(Path(__file__).resolve().parent.parent / 'relay')
if RELAY_PATH not in sys.path:
    sys.path.insert(0, RELAY_PATH)
from repositories import web_auth_store as _web_auth_store
SESSION_COOKIE = 'oe_session'
SESSION_TTL_DAYS = 30

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


_store = _web_auth_store.from_environment(sqlite_path=DB_PATH)


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
    return _store.get_user_by_email(email)


def get_user_by_id(user_id: int):
    return _store.get_user_by_id(user_id)


def get_user_by_telegram_id(telegram_id: int):
    return _store.get_user_by_telegram_id(telegram_id)


def create_user(email: str, password: str) -> int:
    return _store.create_user(email, hash_password(password))


def create_session(web_user_id: int):
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(16)
    expires_at = datetime.now().astimezone() + timedelta(days=SESSION_TTL_DAYS)
    _store.create_session(token, web_user_id, csrf_token, expires_at)
    return token, csrf_token


def destroy_session(token: str):
    _store.destroy_session(token)


def get_web_user(request):
    """Возвращает данные текущего пользователя личного кабинета по cookie сессии, либо None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = _store.get_session_user(token)
    if not row:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "telegram_id": row["telegram_id"],
        "telegram_username": row["telegram_username"],
        "csrf_token": row["csrf_token"],
        "session_token": token,
        "totp_enabled": bool(row["totp_enabled"]),
    }


def is_web_admin(web_user: dict | None, admin_ids) -> bool:
    """Deny-by-default web admin check using an immutable Telegram identity.

    Email text is user-controlled at registration time and must never grant a
    role.  Normalize IDs to strings because SQLite/env values can differ in
    type while still representing the same Telegram account.
    """
    if not web_user:
        return False
    telegram_id = web_user.get("telegram_id")
    if telegram_id in (None, ""):
        return False
    allowed = {str(admin_id) for admin_id in admin_ids if admin_id not in (None, "")}
    return str(telegram_id) in allowed


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
    return _store.set_totp(user_id, secret)


def disable_totp(user_id: int):
    return _store.set_totp(user_id, None)


def set_password_hash(user_id: int, password_hash: str):
    return _store.set_password_hash(user_id, password_hash)


def link_telegram(user_id: int, telegram_id: int, telegram_username: str | None):
    return _store.link_telegram(user_id, telegram_id, telegram_username)


def cleanup_expired_sessions() -> int:
    return _store.cleanup_expired_sessions()


DuplicateIdentityError = _web_auth_store.DuplicateIdentityError


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
