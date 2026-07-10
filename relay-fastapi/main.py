from dotenv import load_dotenv
load_dotenv("/root/bot/.env")

import os, json, sqlite3, qrcode, logging, re, asyncio, time, hmac, hashlib
from contextlib import contextmanager, asynccontextmanager
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
try:
    from ai_support import ask_ai as _ask_ai
    AI_ENABLED = True
except ImportError:
    AI_ENABLED = False
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
import sys
import urllib.parse

import auth

# Загрузка .env
env_path = Path('/root/bot/.env')
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
SECRET_KEY = os.getenv('RELAY_SECRET', 'fallback')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')
GREENPAY_API_SECRET = os.getenv('GREENPAY_API_SECRET', '')
MONTERA_API_TOKEN = os.getenv('MONTERA_API_TOKEN', '')
BRABUS_NOTIFICATION_TOKEN = os.getenv('BRABUS_NOTIFICATION_TOKEN', '')
STORMTRADE_NOTIFICATION_TOKEN = os.getenv('STORMTRADE_NOTIFICATION_TOKEN', '')
XPAY_API_KEY = os.getenv('XPAY_API_KEY', '')
MIN_AMOUNT = float(os.getenv('MIN_AMOUNT', 2000))
MAX_AMOUNT = float(os.getenv('MAX_AMOUNT', 500000))
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0') or '0')
ADMIN_ID_2 = int(os.getenv('ADMIN_ID_2', '0') or '0')  # второй админ (полные права, кроме удаления)
ADMIN_IDS = {a for a in (ADMIN_ID, ADMIN_ID_2) if a}
INTERNAL_ADMIN_SECRET = os.getenv('INTERNAL_ADMIN_SECRET', '')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'Obsidian666999bot')
SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', 'ObsidianSupBot')
REVIEWS_USERNAME = os.getenv('REVIEWS_USERNAME', 'ObsidianReviews')

# Добавляем путь к модулям
sys.path.insert(0, '/root/relay')

BASE_DIR = Path(__file__).resolve().parent

async def _session_cleanup_loop():
    """Удаляет истёкшие сессии раз в 6 часов и чистит audit_log старше 90 дней."""
    while True:
        try:
            with db_conn(5) as conn:
                conn.execute("DELETE FROM web_sessions WHERE expires_at < datetime('now')")
                conn.execute("DELETE FROM audit_log WHERE created_at < datetime('now', '-90 days')")
                conn.commit()
        except Exception as e:
            logger.warning(f"Session cleanup error: {e}")
        await asyncio.sleep(6 * 3600)

@asynccontextmanager
async def lifespan(app):
    asyncio.create_task(_session_cleanup_loop())
    asyncio.create_task(cleanup_expired_orders())
    asyncio.create_task(health_check_task())
    asyncio.create_task(vertu_poll_task())
    logger.info("Background tasks started: cleanup + health_check + vertu_poll")
    yield

app = FastAPI(title="ObsidianExchange Relay", version="3.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


from contextlib import contextmanager, asynccontextmanager

@contextmanager
def db_conn(timeout=5):
    conn = sqlite3.connect(DB_PATH, timeout=timeout)
    try:
        yield conn
    finally:
        conn.close()

def site_context(request: Request, **extra):
    try:
        with db_conn(3) as conn:
            c = conn.cursor()
            stats = c.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN status IN ('paid','sent','failed') THEN 1 ELSE 0 END) as attempted
                FROM orders
            """).fetchone()
            total_orders = stats[0] or 0
            completed_orders = stats[1] or 0
            attempted = stats[2] or 0
            # Показываем успешность только среди тех, кто дошёл до конца
            success_rate = round(completed_orders / max(attempted, 1) * 100, 1) if attempted > 0 else 99.2
    except Exception:
        total_orders, success_rate = 0, 99.2
    ctx = {
        "bot_username": BOT_USERNAME,
        "support_username": SUPPORT_USERNAME,
        "reviews_username": REVIEWS_USERNAME,
        "min_amount": MIN_AMOUNT,
        "max_amount": MAX_AMOUNT,
        "public_relay": PUBLIC_RELAY,
        "web_user": auth.get_web_user(request),
        "total_orders": total_orders,
        "success_rate": success_rate,
    }
    ctx.update(extra)
    return ctx

# Функция аудита
def audit_log(event, details=""):
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("INSERT INTO audit_log (event, details) VALUES (?, ?)", (event, str(details)))
            conn.commit()
    except Exception as e:
        logger.error(f"Audit log error: {e}")

def verify_init_data(init_data: str, max_age: int = 86400):
    """Проверяет HMAC-подпись Telegram WebApp initData.
    Возвращает dict user при валидной подписи и свежем auth_date, иначе None."""
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
        received_hash = parsed.pop('hash', None)
        if not received_hash:
            return None
        data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed_hash, received_hash):
            return None
        # защита от протухшего/переигранного initData
        try:
            auth_date = int(parsed.get('auth_date', '0'))
            if max_age and auth_date and (time.time() - auth_date) > max_age:
                return None
        except ValueError:
            pass
        user = json.loads(parsed.get('user', '{}'))
        if not user.get('id'):
            return None
        return user
    except Exception:
        return None

def verify_admin_init_data(init_data: str):
    """Проверяет подпись Telegram WebApp initData и что user.id ∈ ADMIN_IDS."""
    user = verify_init_data(init_data)
    if not user or user.get('id') not in ADMIN_IDS:
        return None
    return user

def require_admin(request: Request):
    init_data = request.headers.get('X-Telegram-Init-Data', '')
    user = verify_admin_init_data(init_data)
    if not user:
        raise HTTPException(status_code=403, detail="forbidden")
    return user

def notify_telegram(user_id, text, reply_markup=None):
    if not BOT_TOKEN:
        return
    try:
        payload = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
    except Exception as e:
        logger.error(f"notify_telegram error: {e}")

def notify_admins_tg(text, reply_markup=None):
    """Уведомление всем админам из ADMIN_IDS."""
    for _aid in ADMIN_IDS:
        notify_telegram(_aid, text, reply_markup=reply_markup)

# --- Личный кабинет: аутентификация ---

def get_user_orders(web_user, limit=20):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT order_id, currency, rub_amount, status, created_at
            FROM orders
            WHERE web_user_id = ? OR (? IS NOT NULL AND user_id = ?)
            ORDER BY created_at DESC LIMIT ?
        """, (web_user['id'], web_user['telegram_id'], web_user['telegram_id'], limit))
        rows = c.fetchall()
    return [
        {"order_id": r[0], "currency": r[1], "rub_amount": r[2], "status": r[3], "created_at": r[4]}
        for r in rows
    ]

def get_user_swaps(web_user, limit=20):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT session_token, coin_from, coin_to, amount_from, status, created_at
            FROM swap_sessions
            WHERE web_user_id = ? OR (? IS NOT NULL AND user_id = ?)
            ORDER BY created_at DESC LIMIT ?
        """, (web_user['id'], web_user['telegram_id'], web_user['telegram_id'], limit))
        rows = c.fetchall()
    return [
        {"token": r[0], "coin_from": r[1], "coin_to": r[2], "amount_from": r[3], "status": r[4], "created_at": r[5]}
        for r in rows
    ]

def get_open_tickets_count(web_user):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM support_tickets WHERE web_user_id=? AND status != 'closed'", (web_user['id'],))
        n = c.fetchone()[0]
    return n

def get_user_sell_orders(web_user, limit=20):
    with db_conn(5) as conn:
        c = conn.cursor()
        conditions = ["user_id = ?"]
        params = [web_user['telegram_id'] if web_user['telegram_id'] else -web_user['id']]
        c.execute(
            f"SELECT id, currency, crypto_amount, rub_amount, sbp_phone, status, created_at FROM sell_orders WHERE {' OR '.join(conditions)} ORDER BY created_at DESC LIMIT ?",
            params + [limit]
        )
        rows = c.fetchall()
    return [
        {"id": r[0], "currency": r[1], "crypto_amount": r[2], "rub_amount": r[3],
         "sbp_phone": r[4], "status": r[5], "created_at": r[6]}
        for r in rows
    ]

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if auth.get_web_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "register.html", site_context(request))

@app.post("/register", response_class=HTMLResponse)
async def register_submit(request: Request, email: str = Form(...), password: str = Form(...), password2: str = Form(...)):
    email = email.strip().lower()
    error = None
    if not auth.is_valid_email(email):
        error = "Введите корректный email."
    elif len(password) < 8:
        error = "Пароль должен быть не короче 8 символов."
    elif password != password2:
        error = "Пароли не совпадают."
    elif auth.get_user_by_email(email):
        error = "Этот email уже зарегистрирован."
    if error:
        return templates.TemplateResponse(request, "register.html", site_context(request, error=error, email=email), status_code=400)
    web_user_id = auth.create_user(email, password)
    token, _ = auth.create_session(web_user_id)
    response = RedirectResponse("/dashboard", status_code=302)
    auth.set_session_cookie(response, token)
    audit_log("web_register", f"email={email}")
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if auth.get_web_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", site_context(request))

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(default=None),
    password: str = Form(default=None),
    totp_code: str = Form(default=None),
    totp_step_token: str = Form(default=None),
):
    # Второй шаг: TOTP
    if totp_step_token:
        user_id = auth.verify_totp_step_token(totp_step_token)
        if not user_id:
            return templates.TemplateResponse(request, "login.html", site_context(
                request, error="Сессия проверки истекла. Войдите снова."), status_code=400)
        user = auth.get_user_by_id(user_id)
        if not user or not auth.verify_totp_code(user.get('totp_secret', ''), totp_code or ''):
            return templates.TemplateResponse(request, "login.html", site_context(
                request, totp_required=True, totp_step_token=totp_step_token,
                error="Неверный код 2FA. Попробуйте ещё раз."), status_code=400)
        token, _ = auth.create_session(user['id'])
        response = RedirectResponse("/dashboard", status_code=302)
        auth.set_session_cookie(response, token)
        audit_log("web_login_2fa", f"user_id={user_id}")
        return response
    # Первый шаг: пароль
    email = (email or '').strip().lower()
    user = auth.get_user_by_email(email)
    if not user or not auth.verify_password(password or '', user['password_hash']):
        return templates.TemplateResponse(request, "login.html", site_context(
            request, error="Неверный email или пароль.", email=email), status_code=400)
    if user.get('totp_enabled'):
        step_token = auth.make_totp_step_token(user['id'])
        return templates.TemplateResponse(request, "login.html", site_context(
            request, totp_required=True, totp_step_token=step_token))
    token, _ = auth.create_session(user['id'])
    response = RedirectResponse("/dashboard", status_code=302)
    auth.set_session_cookie(response, token)
    audit_log("web_login", f"email={email}")
    return response

@app.post("/logout")
async def logout(request: Request):
    web_user = auth.get_web_user(request)
    response = RedirectResponse("/", status_code=302)
    if web_user:
        auth.destroy_session(web_user['session_token'])
        auth.clear_session_cookie(response)
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    orders = get_user_orders(web_user, limit=5)
    swaps = get_user_swaps(web_user, limit=5)
    open_tickets = get_open_tickets_count(web_user)
    return templates.TemplateResponse(request, "dashboard.html", site_context(
        request, active="overview", orders=orders, swaps=swaps, open_tickets=open_tickets,
    ))

# --- Личный кабинет: обмен RUB → крипта ---
from utils import exchange_calc

@app.get("/dashboard/exchange", response_class=HTMLResponse)
async def dashboard_exchange_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    q = request.query_params
    prefill = {}
    if q.get("repeat"):
        prefill = {"currency": q.get("currency","BTC"), "amount": q.get("amount",""), "address": q.get("address","")}
    return templates.TemplateResponse(request, "dashboard_exchange.html", site_context(
        request, active="exchange", prefill=prefill,
    ))

@app.post("/dashboard/exchange", response_class=HTMLResponse)
async def dashboard_exchange_submit(
    request: Request,
    csrf_token: str = Form(...),
    currency: str = Form(...),
    amount: float = Form(...),
    address: str = Form(...),
    payment_method: str = Form("sbp"),
):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")

    currency = currency.upper().strip()
    address = address.strip()
    error = None
    if currency not in ("BTC", "LTC", "USDT"):
        error = "Неподдерживаемая валюта."
    elif amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        error = f"Сумма должна быть от {MIN_AMOUNT:.0f} до {MAX_AMOUNT:.0f} RUB."
    elif not exchange_calc.validate_crypto_address(address, currency):
        error = "Некорректный адрес для выбранной валюты."

    if error:
        return templates.TemplateResponse(request, "dashboard_exchange.html", site_context(
            request, active="exchange", error=error,
            form={"currency": currency, "amount": amount, "address": address},
        ), status_code=400)

    user_id = web_user['telegram_id'] if web_user['telegram_id'] else -web_user['id']
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status, web_user_id) VALUES (?,?,?,?,?,'pending',?)",
            (user_id, web_user['email'], currency, amount, address, web_user['id']),
        )
        conn.commit()
        order_id = c.lastrowid

    rate = exchange_calc.get_rate_with_markup(currency, amount)
    crypto_amount = round(amount / rate, 8) if rate else 0
    if ADMIN_ID:
        notify_admins_tg( (
            f"🆕 Новая заявка #{order_id} (сайт)\n"
            f"Аккаунт: {web_user['email']}\n"
            f"Сумма: {amount:g} RUB ≈ {crypto_amount} {currency}\n"
            f"Адрес: {address}"
        ))
    audit_log("web_order_created", f"order_id={order_id} web_user_id={web_user['id']}")

    try:
        from services.payment_service import PaymentService
        pm = payment_method if payment_method in ("sbp", "card") else "sbp"
        payment_service = PaymentService(amount=amount)
        session = payment_service.create_session(
            order_id, amount, client_ip=request.client.host,
            telegram_id=web_user['telegram_id'], payment_method=pm,
        )
        if 'session_token' in session:
            return RedirectResponse(f"/pay/{session['session_token']}", status_code=302)
    except Exception as e:
        logger.error(f"Не удалось создать payment session для заявки {order_id} (сайт): {e}")

    return RedirectResponse(f"/pay/{order_id}", status_code=302)

# Анти-спам создания заявок из Mini App: скользящее окно на пользователя + глобально.
from collections import deque as _deque
_order_rate = {}                 # tg_id -> deque[timestamps]
_ORDER_RATE_MAX = 5              # не более 5 заявок
_ORDER_RATE_WINDOW = 600         # за 10 минут на пользователя
_order_rate_global = _deque()    # общий поток
_ORDER_RATE_GLOBAL_MAX = 60      # не более 60 заявок/мин на весь сервис

def _check_order_rate(tg_id: int) -> bool:
    now = time.time()
    g = _order_rate_global
    while g and now - g[0] > 60:
        g.popleft()
    if len(g) >= _ORDER_RATE_GLOBAL_MAX:
        return False
    dq = _order_rate.setdefault(tg_id, _deque())
    while dq and now - dq[0] > _ORDER_RATE_WINDOW:
        dq.popleft()
    if len(dq) >= _ORDER_RATE_MAX:
        return False
    dq.append(now)
    g.append(now)
    if len(_order_rate) > 5000:   # защита от роста словаря
        for k in [k for k, v in _order_rate.items() if not v or now - v[-1] > _ORDER_RATE_WINDOW][:2000]:
            _order_rate.pop(k, None)
    return True

@app.post("/api/create_order")
async def api_create_order(request: Request):
    """Создание заявки из Telegram Mini App.
    Аутентификация — подпись initData (X-Telegram-Init-Data), а НЕ tg.sendData
    (последний работает только из reply-keyboard web_app-кнопки). Возвращает
    payment_url, чтобы Mini App сразу открыл экран оплаты."""
    from utils import exchange_calc
    user = verify_init_data(request.headers.get('X-Telegram-Init-Data', ''))
    if not user:
        raise HTTPException(status_code=403, detail="Откройте приложение через бота Telegram.")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Некорректный запрос.")

    currency = str(body.get('currency', '')).upper().strip()
    address = str(body.get('address', '')).strip()
    pay_method = body.get('pay_method') or body.get('payment_method') or 'sbp'
    pay_method = pay_method if pay_method in ('sbp', 'card') else 'sbp'
    try:
        amount = float(body.get('amount', 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Некорректная сумма.")

    if currency not in ('BTC', 'LTC', 'USDT'):
        raise HTTPException(status_code=400, detail="Неподдерживаемая валюта.")
    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        raise HTTPException(status_code=400, detail=f"Сумма должна быть от {MIN_AMOUNT:.0f} до {MAX_AMOUNT:.0f} ₽.")
    if not exchange_calc.validate_crypto_address(address, currency):
        raise HTTPException(status_code=400, detail="Некорректный адрес кошелька.")

    tg_id = int(user['id'])
    username = user.get('username') or ''

    # Идемпотентность: повторный тап/ретрай с теми же параметрами за 90 с
    # возвращает уже созданную заявку, а не плодит дубли (и не жжёт rate-limit).
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT o.order_id, ps.session_token FROM orders o
            LEFT JOIN payment_sessions ps ON ps.order_id=o.order_id AND ps.status NOT IN ('failed','expired')
            WHERE o.user_id=? AND o.currency=? AND o.rub_amount=? AND o.crypto_address=?
              AND o.status='pending' AND o.created_at > datetime('now','-90 seconds')
            ORDER BY o.created_at DESC LIMIT 1
        """, (tg_id, currency, amount, address))
        dup = c.fetchone()
    if dup:
        dup_url = f"{PUBLIC_RELAY}/pay/{dup[1]}" if dup[1] else f"{PUBLIC_RELAY}/pay/{dup[0]}"
        return {"ok": True, "order_id": dup[0], "payment_url": dup_url,
                "currency": currency, "duplicate": True}

    if not _check_order_rate(tg_id):
        logger.warning(f"[create_order] rate limit hit user={tg_id}")
        raise HTTPException(status_code=429, detail="Слишком много заявок подряд. Подождите пару минут.")
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) VALUES (?,?,?,?,?,'pending')",
            (tg_id, username, currency, amount, address),
        )
        conn.commit()
        order_id = c.lastrowid

    rate = exchange_calc.get_rate_with_markup(currency, amount)
    crypto_amount = round(amount / rate, 8) if rate else 0

    payment_url = f"{PUBLIC_RELAY}/pay/{order_id}"
    try:
        from services.payment_service import PaymentService
        payment_service = PaymentService(amount=amount)
        session = payment_service.create_session(
            order_id, amount, client_ip=request.client.host,
            telegram_id=tg_id, payment_method=pay_method,
        )
        if 'session_token' in session:
            payment_url = f"{PUBLIC_RELAY}/pay/{session['session_token']}"
    except Exception as e:
        logger.error(f"Не удалось создать payment session (miniapp) для заявки {order_id}: {e}")

    if ADMIN_ID:
        notify_admins_tg(
            f"🆕 Новая заявка #{order_id} (Mini App)\n"
            f"Клиент: {tg_id} @{username}\n"
            f"Сумма: {amount:g} RUB ≈ {crypto_amount} {currency}\n"
            f"Адрес: {address}"
        )
    audit_log("miniapp_order_created", f"order_id={order_id} user_id={tg_id}")

    # Дублируем заявку в личку клиенту с кнопками оплаты/статуса
    try:
        notify_telegram(tg_id, (
            f"🟣 <b>ObsidianExchange</b>\n"
            f"✅ Заявка #{order_id} создана!\n"
            f"⏳ Курс зафиксирован на 15 минут\n\n"
            f"Сумма: {amount:g} RUB\nВалюта: {currency}\n\n"
            f"<a href=\"{payment_url}\">Оплатить</a>"
        ), reply_markup={"inline_keyboard": [
            [{"text": "✅ Я оплатил", "callback_data": f"paid_{order_id}"}],
            [{"text": "🔍 Проверить статус", "callback_data": f"check_{order_id}"}],
        ]})
    except Exception as e:
        logger.error(f"miniapp notify user failed: {e}")

    return {"ok": True, "order_id": order_id, "payment_url": payment_url,
            "crypto_amount": crypto_amount, "currency": currency}

@app.get("/dashboard/orders", response_class=HTMLResponse)
async def dashboard_orders_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    orders = get_user_orders(web_user, limit=50)
    swaps = get_user_swaps(web_user, limit=50)
    sell_orders = get_user_sell_orders(web_user, limit=50)
    return templates.TemplateResponse(request, "dashboard_orders.html", site_context(
        request, active="orders", orders=orders, swaps=swaps, sell_orders=sell_orders,
    ))

# --- Личный кабинет: своп криптовалют (Trocador) ---

@app.get("/dashboard/swap", response_class=HTMLResponse)
async def dashboard_swap_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    q = request.query_params
    prefill = {}
    if q.get("repeat"):
        prefill = {"coin_from": q.get("coin_from","BTC"), "coin_to": q.get("coin_to","LTC"),
                   "amount": q.get("amount",""), "address": q.get("address","")}
    return templates.TemplateResponse(request, "dashboard_swap.html", site_context(
        request, active="swap", swap_coins=exchange_calc.SWAP_COINS, prefill=prefill,
    ))

@app.post("/dashboard/swap", response_class=HTMLResponse)
async def dashboard_swap_submit(
    request: Request,
    csrf_token: str = Form(...),
    coin_from: str = Form(...),
    coin_to: str = Form(...),
    amount: float = Form(...),
    address: str = Form(...),
):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")

    coin_from = coin_from.upper().strip()
    coin_to = coin_to.upper().strip()
    address = address.strip()
    error = None
    if coin_from not in exchange_calc.SWAP_COINS or coin_to not in exchange_calc.SWAP_COINS:
        error = "Неподдерживаемая пара валют."
    elif coin_from == coin_to:
        error = "Валюты пары должны отличаться."
    elif amount <= 0:
        error = "Сумма должна быть больше 0."
    elif not exchange_calc.validate_crypto_address(address, coin_to):
        error = "Некорректный адрес для выбранной валюты."

    if error:
        return templates.TemplateResponse(request, "dashboard_swap.html", site_context(
            request, active="swap", swap_coins=exchange_calc.SWAP_COINS, error=error,
            form={"coin_from": coin_from, "coin_to": coin_to, "amount": amount, "address": address},
        ), status_code=400)

    from utils.tokens import generate_session_token
    from providers.swapuz import SwapUzProvider

    token = generate_session_token()
    provider = SwapUzProvider()

    # Проверяем курс и лимиты
    rate_info = provider.get_rate(coin_from, coin_to, amount)
    if "error" in rate_info:
        return templates.TemplateResponse(request, "dashboard_swap.html", site_context(
            request, active="swap", swap_coins=exchange_calc.SWAP_COINS,
            error=f"Не удалось получить курс: {rate_info['error']}",
            form={"coin_from": coin_from, "coin_to": coin_to, "amount": amount, "address": address},
        ), status_code=400)

    result = provider.create_swap(
        coin_from=coin_from,
        coin_to=coin_to,
        amount=amount,
        address=address,
        order_uuid=token,
    )

    if "error" in result:
        return templates.TemplateResponse(request, "dashboard_swap.html", site_context(
            request, active="swap", swap_coins=exchange_calc.SWAP_COINS,
            error=f"Не удалось создать своп: {result['error']}. Попробуйте другую сумму или адрес.",
            form={"coin_from": coin_from, "coin_to": coin_to, "amount": amount, "address": address},
        ), status_code=400)

    user_id = web_user['telegram_id'] if web_user['telegram_id'] else -web_user['id']
    with db_conn(5) as conn:
        conn.execute(
            "INSERT INTO swap_sessions (session_token, user_id, coin_from, coin_to, amount_from, address_to, trocador_id, trocador_url, status, web_user_id, provider, deposit_address) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (token, user_id, coin_from, coin_to, amount, address, result['uid'], result['url'], 'waiting', web_user['id'], 'swapuz', result['deposit_address']),
        )
        conn.commit()
    audit_log("web_swap_created", f"token={token} web_user_id={web_user['id']} provider=swapuz")

    return RedirectResponse(f"/swap/{token}", status_code=302)

# --- Личный кабинет: рефералы и профиль ---

@app.get("/dashboard/referral", response_class=HTMLResponse)
async def dashboard_referral_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    ref_link = None
    stats = {"referrals": 0, "total_bonus_btc": 0}
    if web_user['telegram_id']:
        ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{web_user['telegram_id']}"
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*), SUM(total_bonus_btc) FROM referrals WHERE referrer_id=?", (web_user['telegram_id'],))
            row = c.fetchone()
        stats = {"referrals": row[0] or 0, "total_bonus_btc": row[1] or 0}
    return templates.TemplateResponse(request, "dashboard_referral.html", site_context(
        request, active="referral", ref_link=ref_link, stats=stats,
    ))

@app.get("/dashboard/profile", response_class=HTMLResponse)
async def dashboard_profile_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    ref_address = None
    if web_user['telegram_id']:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT address FROM referral_addresses WHERE user_id=? AND currency='BTC'", (web_user['telegram_id'],))
            row = c.fetchone()
        ref_address = row[0] if row else None
    return templates.TemplateResponse(request, "dashboard_profile.html", site_context(
        request, active="profile", ref_address=ref_address,
        error=request.query_params.get('error'), success=request.query_params.get('success'),
    ))

@app.post("/dashboard/profile/referral-address")
async def dashboard_profile_referral_address(request: Request, csrf_token: str = Form(...), address: str = Form(...)):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")
    if not web_user['telegram_id']:
        return RedirectResponse("/dashboard/profile?error=notelegram", status_code=302)
    address = address.strip()
    if not exchange_calc.validate_crypto_address(address, 'BTC'):
        return RedirectResponse("/dashboard/profile?error=address", status_code=302)
    with db_conn(5) as conn:
        conn.execute("INSERT OR REPLACE INTO referral_addresses (user_id, currency, address) VALUES (?, 'BTC', ?)", (web_user['telegram_id'], address))
        conn.commit()
    return RedirectResponse("/dashboard/profile?success=address", status_code=302)

@app.get("/dashboard/profile/2fa", response_class=HTMLResponse)
async def dashboard_2fa_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    user_full = auth.get_user_by_id(web_user['id'])
    new_secret = auth.generate_totp_secret()
    totp_uri = auth.get_totp_uri(new_secret, web_user['email'])
    return templates.TemplateResponse(request, "dashboard_2fa.html", site_context(
        request, active="profile",
        totp_enabled=user_full.get('totp_enabled', False),
        new_secret=new_secret,
        totp_uri=totp_uri,
        error=request.query_params.get('error'),
        success=request.query_params.get('success'),
    ))

@app.post("/dashboard/profile/2fa/enable")
async def dashboard_2fa_enable(
    request: Request, csrf_token: str = Form(...),
    totp_secret: str = Form(...), totp_code: str = Form(...),
):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")
    if not auth.verify_totp_code(totp_secret, totp_code):
        return RedirectResponse("/dashboard/profile/2fa?error=invalid_code", status_code=302)
    auth.enable_totp(web_user['id'], totp_secret)
    audit_log("web_2fa_enabled", f"user_id={web_user['id']}")
    return RedirectResponse("/dashboard/profile/2fa?success=enabled", status_code=302)

@app.post("/dashboard/profile/2fa/disable")
async def dashboard_2fa_disable(
    request: Request, csrf_token: str = Form(...), totp_code: str = Form(...),
):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")
    user_full = auth.get_user_by_id(web_user['id'])
    if not auth.verify_totp_code(user_full.get('totp_secret', ''), totp_code):
        return RedirectResponse("/dashboard/profile/2fa?error=invalid_code", status_code=302)
    auth.disable_totp(web_user['id'])
    audit_log("web_2fa_disabled", f"user_id={web_user['id']}")
    return RedirectResponse("/dashboard/profile/2fa?success=disabled", status_code=302)

@app.get("/dashboard/profile/password", response_class=HTMLResponse)
async def dashboard_password_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(request, "dashboard_password.html", site_context(
        request, active="profile",
        error=request.query_params.get('error'),
        success=request.query_params.get('success'),
    ))

@app.post("/dashboard/profile/password")
async def dashboard_password_submit(
    request: Request,
    csrf_token: str = Form(...),
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")
    user_full = auth.get_user_by_email(web_user['email'])
    if not auth.verify_password(current_password, user_full['password_hash']):
        return RedirectResponse("/dashboard/profile/password?error=wrong_current", status_code=302)
    if len(new_password) < 8:
        return RedirectResponse("/dashboard/profile/password?error=too_short", status_code=302)
    if new_password != new_password2:
        return RedirectResponse("/dashboard/profile/password?error=mismatch", status_code=302)
    with db_conn(5) as conn:
        conn.execute("UPDATE web_users SET password_hash=? WHERE id=?",
                     (auth.hash_password(new_password), web_user['id']))
        conn.commit()
    audit_log("web_password_changed", f"user_id={web_user['id']}")
    return RedirectResponse("/dashboard/profile/password?success=1", status_code=302)

@app.get("/dashboard/profile/2fa/qr.png")
async def dashboard_2fa_qr(request: Request, secret: str = None):
    web_user = auth.get_web_user(request)
    if not web_user:
        raise HTTPException(status_code=401)
    if not secret or len(secret) < 16:
        raise HTTPException(status_code=400)
    # Разрешаем только base32-символы
    if not re.match(r'^[A-Z2-7]{16,64}$', secret.upper()):
        raise HTTPException(status_code=400)
    totp_uri = auth.get_totp_uri(secret.upper(), web_user['email'])
    img = qrcode.make(totp_uri)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/png",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

@app.get("/auth/telegram/callback")
async def telegram_login_callback(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    data = auth.verify_telegram_login_widget(dict(request.query_params), BOT_TOKEN)
    if not data:
        return RedirectResponse("/dashboard/profile?error=telegram", status_code=302)
    telegram_id = int(data['id'])
    telegram_username = data.get('username')
    with db_conn(5) as conn:
        try:
            conn.execute("UPDATE web_users SET telegram_id=?, telegram_username=? WHERE id=?", (telegram_id, telegram_username, web_user['id']))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return RedirectResponse("/dashboard/profile?error=taken", status_code=302)
    audit_log("web_telegram_linked", f"web_user_id={web_user['id']} telegram_id={telegram_id}")
    return RedirectResponse("/dashboard/profile?success=telegram", status_code=302)

# --- Личный кабинет: поддержка (тикеты) ---

@app.get("/dashboard/support", response_class=HTMLResponse)
async def dashboard_support_page(request: Request):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT id, subject, status, created_at, updated_at FROM support_tickets WHERE web_user_id=? ORDER BY updated_at DESC", (web_user['id'],))
        tickets = [{"id": r[0], "subject": r[1], "status": r[2], "created_at": r[3], "updated_at": r[4]} for r in c.fetchall()]
    return templates.TemplateResponse(request, "dashboard_support.html", site_context(
        request, active="support", tickets=tickets,
    ))

@app.post("/dashboard/support")
async def dashboard_support_create(request: Request, csrf_token: str = Form(...), subject: str = Form(...), message: str = Form(...)):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")
    subject = subject.strip()
    message = message.strip()
    if not subject or not message:
        return RedirectResponse("/dashboard/support?error=empty", status_code=302)
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("INSERT INTO support_tickets (web_user_id, subject, status) VALUES (?,?,'open')", (web_user['id'], subject))
        ticket_id = c.lastrowid
        c.execute("INSERT INTO support_messages (ticket_id, sender, message) VALUES (?, 'user', ?)", (ticket_id, message))
        conn.commit()
    audit_log("web_support_ticket_created", f"ticket_id={ticket_id} web_user_id={web_user['id']}")
    if ADMIN_ID:
        notify_admins_tg( f"💬 Новое обращение #{ticket_id} от {web_user['email']}\nТема: {subject}")
    return RedirectResponse(f"/dashboard/support/{ticket_id}", status_code=302)

@app.get("/dashboard/support/{ticket_id}", response_class=HTMLResponse)
async def dashboard_support_ticket_page(request: Request, ticket_id: int):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT id, subject, status FROM support_tickets WHERE id=? AND web_user_id=?", (ticket_id, web_user['id']))
        ticket = c.fetchone()
        if not ticket:
            conn.close()
            raise HTTPException(status_code=404)
        c.execute("SELECT sender, message, created_at FROM support_messages WHERE ticket_id=? ORDER BY created_at ASC, id ASC", (ticket_id,))
        messages = [{"sender": r[0], "message": r[1], "created_at": r[2]} for r in c.fetchall()]
    return templates.TemplateResponse(request, "dashboard_support_ticket.html", site_context(
        request, active="support",
        ticket={"id": ticket[0], "subject": ticket[1], "status": ticket[2]}, messages=messages,
    ))

@app.post("/dashboard/support/{ticket_id}/reply")
async def dashboard_support_reply(request: Request, ticket_id: int, csrf_token: str = Form(...), message: str = Form(...)):
    web_user = auth.get_web_user(request)
    if not web_user:
        return RedirectResponse("/login", status_code=302)
    if not auth.verify_csrf(web_user, csrf_token):
        raise HTTPException(status_code=403, detail="invalid csrf")
    message = message.strip()
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT id, status FROM support_tickets WHERE id=? AND web_user_id=?", (ticket_id, web_user['id']))
        ticket = c.fetchone()
        if not ticket:
            conn.close()
            raise HTTPException(status_code=404)
        if message:
            c.execute("INSERT INTO support_messages (ticket_id, sender, message) VALUES (?, 'user', ?)", (ticket_id, message))
            c.execute("UPDATE support_tickets SET status='open', updated_at=datetime('now') WHERE id=?", (ticket_id,))
            conn.commit()
            if ADMIN_ID:
                notify_admins_tg( f"💬 Новое сообщение в обращении #{ticket_id} от {web_user['email']}")
    return RedirectResponse(f"/dashboard/support/{ticket_id}", status_code=302)

# --- Публичный сайт ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", site_context(request))

@app.get("/rates", response_class=HTMLResponse)
async def rates_page(request: Request):
    return templates.TemplateResponse(request, "rates.html", site_context(request))

@app.get("/how-it-works", response_class=HTMLResponse)
async def how_it_works_page(request: Request):
    return templates.TemplateResponse(request, "how_it_works.html", site_context(request))

@app.get("/faq", response_class=HTMLResponse)
async def faq_page(request: Request):
    return templates.TemplateResponse(request, "faq.html", site_context(request))

@app.get("/reviews", response_class=HTMLResponse)
async def reviews_page(request: Request):
    return templates.TemplateResponse(request, "reviews.html", site_context(request))

@app.get("/contacts", response_class=HTMLResponse)
async def contacts_page(request: Request):
    return templates.TemplateResponse(request, "contacts.html", site_context(request))

@app.get("/offer", response_class=HTMLResponse)
async def offer_page(request: Request):
    return templates.TemplateResponse(request, "offer.html", site_context(request))

@app.get("/widget", response_class=HTMLResponse)
async def widget_page():
    from utils import exchange_calc
    btc = exchange_calc.get_cached_rate("BTC") or 0
    ltc = exchange_calc.get_cached_rate("LTC") or 0
    usdt = exchange_calc.get_cached_rate("USDT") or 0
    comm = exchange_calc.get_commission_percent(10000)
    ex = 10000
    btc_out  = round(ex * (1 - comm / 100) / btc,  6) if btc  else 0
    ltc_out  = round(ex * (1 - comm / 100) / ltc,  4) if ltc  else 0
    usdt_out = round(ex * (1 - 0.02)       / usdt, 2) if usdt else 0
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ObsidianExchange · Курс</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');
  :root{{
    --bg:#07000f;
    --card:#100020;
    --border:#2a0055;
    --purple:#c040ff;
    --purple-dim:#7a1faa;
    --text:#e8d8ff;
    --muted:#7a6a99;
    --btc:#f7931a;
    --ltc:#a8a9ad;
    --usdt:#26a17b;
    --glow:rgba(192,64,255,.18);
  }}
  html,body{{width:100%;height:100%;background:transparent}}
  body{{font-family:'Inter',sans-serif;background:transparent;display:flex;align-items:center;justify-content:center}}
  .widget{{
    width:340px;
    background:var(--bg);
    border:1px solid var(--border);
    border-radius:14px;
    overflow:hidden;
    box-shadow:0 0 32px var(--glow),inset 0 0 60px rgba(100,0,180,.06);
    position:relative;
  }}
  .widget::before{{
    content:'';position:absolute;inset:0;
    background:linear-gradient(135deg,rgba(192,64,255,.07) 0%,transparent 60%);
    pointer-events:none;border-radius:14px;
  }}
  .header{{
    display:flex;align-items:center;justify-content:space-between;
    padding:10px 14px 8px;
    border-bottom:1px solid var(--border);
  }}
  .logo{{display:flex;align-items:center;gap:7px}}
  .logo-gem{{
    width:22px;height:22px;
    background:linear-gradient(135deg,var(--purple) 0%,#6600cc 100%);
    border-radius:5px;
    display:flex;align-items:center;justify-content:center;
    font-size:12px;box-shadow:0 0 10px var(--glow);
  }}
  .logo-text{{font-size:13px;font-weight:900;letter-spacing:.06em;color:var(--text);text-transform:uppercase}}
  .logo-text span{{color:var(--purple)}}
  .header-right{{text-align:right}}
  .header-label{{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}}
  .header-amount{{font-size:11px;font-weight:700;color:var(--purple);margin-top:1px}}
  .rows{{padding:6px 0 4px}}
  .row{{
    display:flex;align-items:center;gap:10px;
    padding:7px 14px;
    transition:background .2s;
  }}
  .row:hover{{background:rgba(192,64,255,.05)}}
  .coin-icon{{
    width:28px;height:28px;border-radius:50%;
    display:flex;align-items:center;justify-content:center;
    font-size:14px;font-weight:900;flex-shrink:0;
    box-shadow:0 0 8px rgba(0,0,0,.4);
  }}
  .coin-icon.btc{{background:radial-gradient(circle,#f7931a,#c45e00);color:#fff}}
  .coin-icon.ltc{{background:radial-gradient(circle,#c0c0c0,#7a7a7a);color:#fff}}
  .coin-icon.usdt{{background:radial-gradient(circle,#26a17b,#1a6e54);color:#fff}}
  .coin-info{{flex:1;min-width:0}}
  .coin-name{{font-size:10px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
  .coin-val{{
    font-size:15px;font-weight:700;color:var(--text);
    font-variant-numeric:tabular-nums;margin-top:1px;
  }}
  .coin-ticker{{font-size:11px;color:var(--purple);margin-left:4px;font-weight:600}}
  .divider{{height:1px;background:var(--border);margin:0 14px;opacity:.5}}
  .footer{{
    display:flex;align-items:center;justify-content:space-between;
    padding:7px 14px;
  }}
  .footer-link{{
    font-size:9px;color:var(--purple-dim);text-decoration:none;
    letter-spacing:.04em;text-transform:uppercase;
    transition:color .2s;
  }}
  .footer-link:hover{{color:var(--purple)}}
  .update-status{{
    font-size:9px;color:var(--muted);
    display:flex;align-items:center;gap:4px;
  }}
  .dot{{
    width:5px;height:5px;border-radius:50%;
    background:var(--purple);
    animation:pulse 2s infinite;
  }}
  @keyframes pulse{{
    0%,100%{{opacity:1;box-shadow:0 0 4px var(--purple)}}
    50%{{opacity:.3;box-shadow:none}}
  }}
  .dot.updating{{background:#ff9d00;animation:spin-dot 1s linear infinite}}
  @keyframes spin-dot{{to{{transform:rotate(360deg)}}}}
  .updating-label{{display:none;color:#ff9d00}}
  body.is-updating .updating-label{{display:inline}}
  body.is-updating .idle-label{{display:none}}
  body.is-updating .dot{{background:#ff9d00}}
  .val-skeleton{{
    display:inline-block;width:80px;height:14px;
    border-radius:4px;background:linear-gradient(90deg,#1a0035 25%,#2e0060 50%,#1a0035 75%);
    background-size:200% 100%;animation:shimmer 1.2s infinite;vertical-align:middle;
  }}
  @keyframes shimmer{{0%{{background-position:200% 0}}100%{{background-position:-200% 0}}}}
</style>
</head>
<body>
<div class="widget">
  <div class="header">
    <div class="logo">
      <div class="logo-gem">◆</div>
      <div class="logo-text"><span>Obsidian</span>Exchange</div>
    </div>
    <div class="header-right">
      <div class="header-label">За 10 000 ₽ вы получите</div>
      <div class="header-amount">комиссия {comm}% / USDT 2%</div>
    </div>
  </div>

  <div class="rows">
    <div class="row">
      <div class="coin-icon btc">₿</div>
      <div class="coin-info">
        <div class="coin-name">Bitcoin</div>
        <div class="coin-val" id="btc-val">{btc_out}<span class="coin-ticker">BTC</span></div>
      </div>
    </div>
    <div class="divider"></div>
    <div class="row">
      <div class="coin-icon ltc">Ł</div>
      <div class="coin-info">
        <div class="coin-name">Litecoin</div>
        <div class="coin-val" id="ltc-val">{ltc_out}<span class="coin-ticker">LTC</span></div>
      </div>
    </div>
    <div class="divider"></div>
    <div class="row">
      <div class="coin-icon usdt">₮</div>
      <div class="coin-info">
        <div class="coin-name">Tether TRC20</div>
        <div class="coin-val" id="usdt-val">{usdt_out}<span class="coin-ticker">USDT</span></div>
      </div>
    </div>
  </div>

  <div class="footer">
    <a class="footer-link" href="https://obsidian-exchange.org" target="_blank">obsidian-exchange.org</a>
    <div class="update-status">
      <div class="dot"></div>
      <span class="idle-label" id="upd-time">—</span>
      <span class="updating-label">обновляется…</span>
    </div>
  </div>
</div>

<script>
const MSK_OFFSET = 3 * 60;
function mskTime() {{
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const msk = new Date(utc + MSK_OFFSET * 60000);
  const p = n => String(n).padStart(2,'0');
  return p(msk.getHours()) + ':' + p(msk.getMinutes()) + ' МСК';
}}

function setVal(id, num, decimals) {{
  const el = document.getElementById(id);
  const ticker = el.querySelector('.coin-ticker');
  const text = typeof num === 'number' ? num.toFixed(decimals) : num;
  el.firstChild.textContent = text;
  // restore ticker after innerHTML reset
  el.appendChild(ticker);
}}

async function refresh() {{
  document.body.classList.add('is-updating');
  // Показываем скелетон
  ['btc-val','ltc-val','usdt-val'].forEach(id => {{
    const el = document.getElementById(id);
    const ticker = el.querySelector('.coin-ticker').cloneNode(true);
    el.innerHTML = '';
    const sk = document.createElement('span');
    sk.className = 'val-skeleton';
    el.appendChild(sk);
    el.appendChild(ticker);
  }});
  try {{
    const r = await fetch('/api/widget-rates');
    const d = await r.json();
    document.getElementById('btc-val').innerHTML  = d.btc  + '<span class="coin-ticker">BTC</span>';
    document.getElementById('ltc-val').innerHTML  = d.ltc  + '<span class="coin-ticker">LTC</span>';
    document.getElementById('usdt-val').innerHTML = d.usdt + '<span class="coin-ticker">USDT</span>';
    document.getElementById('upd-time').textContent = mskTime();
  }} catch(e) {{
    console.warn('widget update failed', e);
  }}
  document.body.classList.remove('is-updating');
}}

// Первое обновление + каждые 60 сек
document.getElementById('upd-time').textContent = mskTime();
setInterval(refresh, 60000);
setTimeout(refresh, 3000);  // небольшая задержка после загрузки
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/api/widget-rates")
async def api_widget_rates():
    from utils import exchange_calc
    btc  = exchange_calc.get_cached_rate("BTC")  or 0
    ltc  = exchange_calc.get_cached_rate("LTC")  or 0
    usdt = exchange_calc.get_cached_rate("USDT") or 0
    comm = exchange_calc.get_commission_percent(10000)
    ex   = 10000
    return {
        "btc":  round(ex * (1 - comm / 100) / btc,  6) if btc  else 0,
        "ltc":  round(ex * (1 - comm / 100) / ltc,  4) if ltc  else 0,
        "usdt": round(ex * (1 - 0.02)       / usdt, 2) if usdt else 0,
        "comm_pct": comm,
        "ts": int(__import__('time').time()),
    }


_rates_cache: dict = {"data": {}, "ts": 0.0}

@app.get("/api/rates")
async def api_rates():
    import time
    if time.time() - _rates_cache["ts"] < 60 and _rates_cache["data"]:
        return _rates_cache["data"]
    from utils import exchange_calc
    btc  = exchange_calc.get_cached_rate("BTC")  or 0
    ltc  = exchange_calc.get_cached_rate("LTC")  or 0
    usdt = exchange_calc.get_cached_rate("USDT") or 0
    result = {"BTC": btc, "LTC": ltc, "USDT": usdt, "ts": int(time.time())}
    _rates_cache["data"] = result
    _rates_cache["ts"] = time.time()
    return result

@app.get("/api/stats/public")
async def api_stats_public():
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='sent'", (datetime.now().strftime("%Y-%m-%d"),))
        sent_today = c.fetchone()[0]
    return {"exchanges_today": sent_today}

@app.get("/webapp", response_class=HTMLResponse)
async def webapp():
    try:
        with open('/root/relay/webapp.html', 'r') as f:
            return f.read()
    except:
        raise HTTPException(status_code=500)

# --- API эндпоинты ---
@app.get("/api/history")
async def api_history(user_id: int):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT o.order_id, o.rub_amount, o.currency, o.status, o.created_at,
                   ps.session_token
            FROM orders o
            LEFT JOIN payment_sessions ps ON ps.order_id = o.order_id
                AND ps.status NOT IN ('failed','expired')
            WHERE o.user_id=?
            ORDER BY o.created_at DESC LIMIT 30
        """, (user_id,))
        rows = c.fetchall()
    return [{"order_id": r[0], "amount": r[1], "currency": r[2], "status": r[3], "created": r[4], "session_token": r[5]} for r in rows]

@app.get("/api/referral_stats")
async def api_referral(user_id: int):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), SUM(total_bonus_btc) FROM referrals WHERE referrer_id=?", (user_id,))
        row = c.fetchone()
    return {"referrals": row[0] or 0, "total_bonus_btc": row[1] or 0}

@app.get("/api/order/{order_id}")
async def api_order(order_id: int, request: Request):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT status, paid_btc_tx, user_id FROM orders WHERE order_id=?", (order_id,))
        row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404)
    status, txid, owner_id = row[0], row[1], row[2]

    # Защита от IDOR/энумерации: статус заявки виден только владельцу.
    # Доказательство владения — подпись initData Mini App ИЛИ session_token заявки
    # (для web /pay). Иначе 404 (не раскрываем существование заявки).
    user = verify_init_data(request.headers.get('X-Telegram-Init-Data', ''))
    authorized = bool(user and owner_id is not None and int(user['id']) == int(owner_id))
    if not authorized:
        token = request.query_params.get('token', '')
        if token:
            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("SELECT 1 FROM payment_sessions WHERE order_id=? AND session_token=? LIMIT 1",
                          (order_id, token))
                authorized = c.fetchone() is not None
    if not authorized:
        raise HTTPException(status_code=404)

    # Если заявка ещё pending — проверяем Brabus напрямую на случай пропущенного вебхука
    if status == 'pending':
        try:
            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("""SELECT provider_invoice_id, provider FROM payment_sessions
                             WHERE order_id=? AND provider LIKE 'brabus%' AND provider_invoice_id IS NOT NULL
                             ORDER BY created_at DESC LIMIT 1""", (order_id,))
                sess = c.fetchone()
            if sess:
                inv_id, prov = sess
                variant = prov.split(':', 1)[1] if ':' in prov else 'tbank_deeplink'
                from providers.brabus import BrabusProvider
                brabus_status = BrabusProvider(variant=variant).get_status(inv_id)
                if brabus_status.get('status') == 'paid':
                    with db_conn(5) as conn:
                        c = conn.cursor()
                        c.execute("UPDATE orders SET status='paid', updated_at=datetime('now') WHERE order_id=? AND status='pending'", (order_id,))
                        conn.commit()
                    status = 'paid'
                    audit_log("brabus_polled_paid", f"order={order_id} inv={inv_id}")
                    logger.info(f"[brabus_poll] order {order_id} marked paid via polling")
        except Exception as e:
            logger.warning(f"[brabus_poll] order {order_id}: {e}")

    # Аналогично для Vertu (вебхуков нет — только опрос)
    if status == 'pending':
        try:
            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("""SELECT provider_invoice_id FROM payment_sessions
                             WHERE order_id=? AND provider='vertu' AND provider_invoice_id IS NOT NULL
                             ORDER BY created_at DESC LIMIT 1""", (order_id,))
                sess = c.fetchone()
            if sess:
                from providers.vertu import VertuProvider
                vertu_status = await asyncio.to_thread(VertuProvider().get_status, sess[0])
                if vertu_status.get('status') == 'paid':
                    with db_conn(5) as conn:
                        c = conn.cursor()
                        c.execute("UPDATE orders SET status='paid', updated_at=datetime('now') WHERE order_id=? AND status='pending'", (order_id,))
                        conn.commit()
                    status = 'paid'
                    audit_log("vertu_polled_paid", f"order={order_id} inv={sess[0]}")
                    logger.info(f"[vertu_poll] order {order_id} marked paid via /api/order")
        except Exception as e:
            logger.warning(f"[vertu_poll] order {order_id}: {e}")

    return {"status": status, "txid": txid}

# --- Админ-вкладка Mini App ---
@app.get("/api/admin/stats")
async def admin_stats_api(request: Request):
    require_admin(request)
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders WHERE status='sent'")
        sent = c.fetchone()[0]
        c.execute("SELECT SUM(rub_amount) FROM orders WHERE status='sent'")
        volume = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM orders WHERE status='pending'")
        pending = c.fetchone()[0]
    return {"total": total, "pending": pending, "sent": sent, "volume": volume}

@app.get("/api/admin/orders")
async def admin_orders_api(request: Request, limit: int = 20):
    require_admin(request)
    limit = max(1, min(limit, 100))
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT order_id, user_id, username, rub_amount, currency, status, created_at FROM orders ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = c.fetchall()
    return {"orders": [
        {"order_id": r[0], "user_id": r[1], "username": r[2], "rub_amount": r[3], "currency": r[4], "status": r[5], "created_at": r[6]}
        for r in rows
    ]}

@app.get("/api/admin/blocked")
async def admin_blocked_api(request: Request):
    require_admin(request)
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, reason, blocked_at FROM blocked_users ORDER BY blocked_at DESC LIMIT 50")
        rows = c.fetchall()
    return {"blocked": [{"user_id": r[0], "reason": r[1], "blocked_at": r[2]} for r in rows]}

@app.post("/api/admin/block")
async def admin_block_api(request: Request):
    require_admin(request)
    data = await request.json()
    user_id = int(data['user_id'])
    reason = (data.get('reason') or 'admin block').strip()
    with db_conn(10) as conn:
        conn.execute("INSERT OR IGNORE INTO blocked_users (user_id, reason) VALUES (?, ?)", (user_id, reason))
        conn.commit()
    audit_log("admin_block", f"user_id={user_id}")
    return {"ok": True}

@app.post("/api/admin/unblock")
async def admin_unblock_api(request: Request):
    require_admin(request)
    data = await request.json()
    user_id = int(data['user_id'])
    with db_conn(10) as conn:
        conn.execute("DELETE FROM blocked_users WHERE user_id=?", (user_id,))
        conn.commit()
    audit_log("admin_unblock", f"user_id={user_id}")
    return {"ok": True}

@app.post("/api/admin/force_payout")
async def admin_force_payout_api(request: Request):
    require_admin(request)
    data = await request.json()
    order_id = int(data['order_id'])
    fake_tx = f"manual_{int(time.time())}"
    with db_conn(10) as conn:
        conn.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (fake_tx, order_id))
        conn.commit()
    audit_log("admin_force_payout", f"order_id={order_id} tx={fake_tx}")
    return {"ok": True, "txid": fake_tx}

@app.post("/internal/admin/force_payout")
async def internal_force_payout(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    if not INTERNAL_ADMIN_SECRET or not hmac.compare_digest(secret, INTERNAL_ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="forbidden")
    data = await request.json()
    order_id = int(data['order_id'])
    fake_tx = f"manual_{int(time.time())}"
    with db_conn(10) as conn:
        conn.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (fake_tx, order_id))
        conn.commit()
    audit_log("admin_force_payout_laravel", f"order_id={order_id} tx={fake_tx}")
    return {"ok": True, "txid": fake_tx}

@app.post("/internal/admin/notify_support")
async def internal_notify_support(request: Request):
    secret = request.headers.get("X-Internal-Secret", "")
    if not INTERNAL_ADMIN_SECRET or not hmac.compare_digest(secret, INTERNAL_ADMIN_SECRET):
        raise HTTPException(status_code=403, detail="forbidden")
    data = await request.json()
    web_user_id = int(data['web_user_id'])
    text = data['text']
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM web_users WHERE id=?", (web_user_id,))
        row = c.fetchone()
    if row and row[0]:
        notify_telegram(row[0], text)
    return {"ok": True}

@app.get("/api/server-stats")
async def api_server_stats():
    import psutil
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return {
        "cpu": cpu,
        "memory_used": round(mem.used / (1024**3), 1),
        "memory_total": round(mem.total / (1024**3), 1),
        "disk_used": round(disk.used / (1024**3), 1),
        "disk_total": round(disk.total / (1024**3), 1)
    }

# --- Платёжный шлюз (старый формат /pay/{order_id}) ---
@app.get("/pay/{token}", response_class=HTMLResponse)
async def pay(token: str, request: Request):
    client_ip = request.client.host
    audit_log("payment_page_opened", f"token={token} ip={client_ip}")
    
    # Проверяем, является ли token числом (старый формат)
    if token.isdigit():
        order_id = int(token)
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT rub_amount, paid_btc_tx FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if not row:
            raise HTTPException(status_code=404)
        
        amount, platega_url = row
        if not platega_url:
            platega_url = "https://obsidian-exchange.org/error"
        
        qr = qrcode.make(platega_url)
        bio = BytesIO(); qr.save(bio, "PNG"); bio.seek(0)
        import base64
        qr_base64 = base64.b64encode(bio.read()).decode()
        
        # Старая вёрстка (зелёная) — позже заменим на киберпанк
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Оплата заказа #{order_id} | ObsidianExchange</title>
    <style>
        body {{ font-family: Arial, sans-serif; background: #0a0a0a; color: #e0e0e0; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .container {{ text-align: center; background: #141414; padding: 40px; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,0.6); max-width: 400px; width: 90%; }}
        h1 {{ color: #2a7d2a; font-size: 24px; }}
        .amount {{ font-size: 28px; font-weight: 700; color: #2a7d2a; margin: 20px 0; }}
        .qr {{ margin: 20px auto; }}
        .qr img {{ border-radius: 15px; }}
        .btn {{ display: inline-block; padding: 14px 30px; background: #2a7d2a; color: #fff; text-decoration: none; border-radius: 10px; font-size: 18px; margin-top: 20px; }}
        .btn:hover {{ background: #236923; }}
        p {{ color: #999; font-size: 14px; margin-top: 15px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚫ ObsidianExchange</h1>
        <p>Заказ #{order_id}</p>
        <div class="amount">{amount} RUB</div>
        <p>📲 Отсканируйте QR-код в приложении вашего банка для оплаты через СБП</p>
        <div class="qr"><img src="data:image/png;base64,{qr_base64}" width="250" alt="QR-код оплаты"></div>
        <a class="btn" href="{platega_url}" target="_blank">Открыть в приложении банка</a>
        <p>После оплаты нажмите «Я оплатил» в боте</p>
    </div>
</body>
</html>"""
        return html
    
    # Если token не число, пробуем найти сессию (новый формат)
    try:
        from services.payment_service import PaymentService
        payment_service = PaymentService()
        session = payment_service.get_session(token)
        if not session:
            raise HTTPException(status_code=404)
        amount = session['amount']
        order_id = session['order_id']
        platega_url = session.get('qr_payload', 'https://obsidian-exchange.org/error')
        
        qr = qrcode.make(platega_url)
        bio = BytesIO(); qr.save(bio, "PNG"); bio.seek(0)
        import base64
        qr_base64 = base64.b64encode(bio.read()).decode()
        
        # Здесь должен быть киберпанк-шаблон (позже заменим)
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secure Payment #{order_id} | ObsidianExchange</title>
    <style>
        :root {{ --bg: #050507; --card: #0f0f14; --input: #151520; --border: rgba(168,85,247,.18); --purple: #8b5cf6; --text: #f3f3f3; --radius: 22px; }}
        @keyframes matrixRain {{ 0% {{ transform: translateY(-100vh); opacity: 0; }} 20% {{ opacity: 1; }} 100% {{ transform: translateY(100vh); opacity: 0; }} }}
        @keyframes pulseGlow {{ 0%, 100% {{ box-shadow: 0 0 20px rgba(168,85,247,0.5); }} 50% {{ box-shadow: 0 0 40px rgba(168,85,247,0.9), 0 0 80px rgba(168,85,247,0.4); }} }}
        @keyframes scanLine {{ 0% {{ transform: translateY(-100%); }} 100% {{ transform: translateY(100%); }} }}
        @keyframes containerFloat {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-4px); }} }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: radial-gradient(circle at top, rgba(139,92,246,.25), transparent 45%), linear-gradient(180deg,#050507,#09090f); color: var(--text); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; position: relative; overflow: hidden; }}
        .matrix-bg {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; background-image: linear-gradient(rgba(168,85,247,.08) 1px, transparent 1px), linear-gradient(90deg, rgba(168,85,247,.05) 1px, transparent 1px); background-size: 40px 40px; animation: matrixRain 10s linear infinite; pointer-events: none; z-index: 0; }}
        .container {{ width: 100%; max-width: 420px; background: rgba(10,10,15,.88); backdrop-filter: blur(24px); border: 1px solid var(--border); border-radius: 34px; padding: 30px 20px; box-shadow: 0 0 80px rgba(168,85,247,.18), inset 0 0 0 1px rgba(255,255,255,.03); text-align: center; position: relative; z-index: 1; animation: containerFloat 6s ease-in-out infinite; }}
        h1 {{ font-size: 24px; font-weight: 800; background: linear-gradient(90deg,#fff,#c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }}
        .amount {{ font-size: 28px; font-weight: 700; color: #00ff9d; margin: 15px 0; }}
        .qr {{ margin: 20px auto; border-radius: 15px; padding: 10px; background: rgba(168,85,247,.05); border: 1px solid rgba(168,85,247,.2); display: inline-block; animation: pulseGlow 2s ease-in-out infinite; position: relative; }}
        .qr img {{ border-radius: 10px; }}
        .scan-overlay {{ position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: linear-gradient(to bottom, transparent, rgba(168,85,247,0.2), transparent); animation: scanLine 3s linear infinite; pointer-events: none; }}
        .bank-list {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 20px; }}
        .bank-btn {{ display: block; padding: 14px; border-radius: 18px; background: linear-gradient(180deg, rgba(168,85,247,.18), rgba(168,85,247,.08)); border: 1px solid rgba(168,85,247,.25); color: #fff; font-weight: 600; text-decoration: none; transition: all .3s; backdrop-filter: blur(5px); position: relative; overflow: hidden; }}
        .bank-btn:hover {{ background: linear-gradient(180deg, #7c3aed, #a855f7); box-shadow: 0 0 25px rgba(168,85,247,.5); transform: translateY(-2px); }}
        .bank-btn::before {{ content: ""; position: absolute; top: 0; left: -100%; width: 100%; height: 100%; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent); transition: left 0.5s; }}
        .bank-btn:hover::before {{ left: 100%; }}
        .info-text {{ color: #999; font-size: 14px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="matrix-bg"></div>
    <div class="container">
        <h1>⚫ ObsidianExchange</h1>
        <p>Заказ #{order_id}</p>
        <div class="amount">{amount} RUB</div>
        <p>📲 Отсканируйте QR-код для оплаты через СБП</p>
        <div class="qr"><img src="data:image/png;base64,{qr_base64}" width="220" alt="QR-код"><div class="scan-overlay"></div></div>
        <a class="bank-btn" href="{platega_url}">Оплатить через СБП</a>
        <p class="info-text">После оплаты нажмите «Я оплатил» в боте</p>
    </div>
</body>
</html>"""
        return html
    except Exception as e:
        logger.error(f"Error in /pay/{token}: {e}")
        raise HTTPException(status_code=500)

# --- Своп криптовалют через Trocador ---
@app.get("/swap/{token}", response_class=HTMLResponse)
async def swap_page(token: str, request: Request):
    audit_log("swap_page_opened", f"token={token} ip={request.client.host}")
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT coin_from, coin_to, amount_from, address_to, trocador_id, trocador_url, status, provider, deposit_address FROM swap_sessions WHERE session_token=?", (token,))
        row = c.fetchone()
    if not row:
        raise HTTPException(status_code=404)
    coin_from, coin_to, amount_from, address_to, ext_id, ext_url, status, provider_name, deposit_address = row
    provider_name = provider_name or 'trocador'

    try:
        if provider_name == 'swapuz':
            from providers.swapuz import SwapUzProvider
            info = SwapUzProvider().get_status(ext_id)
            new_status = info.get('status')
        else:
            from providers.trocador import TrocadorProvider
            info = TrocadorProvider().get_status(ext_id)
            new_status = info.get('Status')
        if new_status and new_status != status:
            status = new_status
            with db_conn(5) as conn:
                conn.execute("UPDATE swap_sessions SET status=?, updated_at=datetime('now') WHERE session_token=?", (status, token))
                conn.commit()
    except Exception as e:
        logger.error(f"Swap status fetch error: {e}")

    status_labels = {
        'anonpaynew': 'Ожидание оплаты',
        'waiting': 'Ожидание перевода ⏳',
        'confirming': 'Подтверждение в сети 🔄',
        'exchanging': 'Обмен 🔄',
        'sending': 'Отправка получателю 📤',
        'finished': 'Завершено ✅',
        'failed': 'Ошибка ❌',
        'expired': 'Истекло ⏰',
        'halted': 'Приостановлено',
        'refunded': 'Возврат средств',
    }
    status_label = status_labels.get(status, status or 'Ожидание')

    if provider_name == 'swapuz' and deposit_address:
        action_block = f"""
        <div class="deposit-block">
            <div class="deposit-label">Отправьте <b>{amount_from} {coin_from}</b> на адрес:</div>
            <div class="deposit-addr" id="depAddr">{deposit_address}</div>
            <button class="copy-btn" onclick="navigator.clipboard.writeText('{deposit_address}').then(()=>this.textContent='Скопировано ✅')">Скопировать адрес</button>
        </div>
        <p class="info-text">ObsidianExchange не получает доступ к вашим средствам — своп выполняется через SwapUZ.</p>"""
        extra_style = """.deposit-block{{margin:18px 0;padding:14px;border-radius:14px;background:rgba(0,255,157,.06);border:1px solid rgba(0,255,157,.2);text-align:center}}.deposit-label{{font-size:14px;color:#aaa;margin-bottom:8px}}.deposit-addr{{font-size:13px;font-family:monospace;color:#00ff9d;word-break:break-all;margin:8px 0;padding:10px;background:rgba(0,0,0,.3);border-radius:10px}}.copy-btn{{margin-top:8px;padding:10px 22px;border-radius:12px;border:none;background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;font-weight:600;cursor:pointer;font-size:14px}}"""
    else:
        action_block = f"""
        <a class="bank-btn" href="{ext_url}" target="_blank">Открыть страницу обмена</a>
        <p class="info-text">На странице появится адрес для отправки {coin_from} и QR-код.</p>"""
        extra_style = ""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Своп {coin_from} → {coin_to} | ObsidianExchange</title>
    <style>
        :root {{ --bg: #050507; --border: rgba(168,85,247,.18); --purple: #8b5cf6; --text: #f3f3f3; }}
        @keyframes pulseGlow {{ 0%, 100% {{ box-shadow: 0 0 20px rgba(168,85,247,0.5); }} 50% {{ box-shadow: 0 0 40px rgba(168,85,247,0.9); }} }}
        @keyframes containerFloat {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-4px); }} }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: radial-gradient(circle at top, rgba(139,92,246,.25), transparent 45%), linear-gradient(180deg,#050507,#09090f); color: var(--text); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }}
        .container {{ width: 100%; max-width: 420px; background: rgba(10,10,15,.88); backdrop-filter: blur(24px); border: 1px solid var(--border); border-radius: 34px; padding: 30px 20px; box-shadow: 0 0 80px rgba(168,85,247,.18); text-align: center; animation: containerFloat 6s ease-in-out infinite; }}
        h1 {{ font-size: 24px; font-weight: 800; background: linear-gradient(90deg,#fff,#c084fc); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }}
        .pair {{ font-size: 20px; font-weight: 700; color: #fff; margin: 10px 0; }}
        .amount {{ font-size: 26px; font-weight: 700; color: #00ff9d; margin: 10px 0; }}
        .row {{ display: flex; justify-content: space-between; gap: 10px; margin: 6px 0; font-size: 14px; color: #aaa; text-align: left; }}
        .row b {{ color: #f3f3f3; word-break: break-all; text-align: right; margin-left: 10px; }}
        .status-box {{ margin: 18px 0; padding: 12px; border-radius: 14px; background: rgba(168,85,247,.08); border: 1px solid var(--border); font-weight: 600; }}
        .bank-btn {{ display: block; padding: 14px; border-radius: 18px; background: linear-gradient(180deg, rgba(168,85,247,.18), rgba(168,85,247,.08)); border: 1px solid rgba(168,85,247,.25); color: #fff; font-weight: 600; text-decoration: none; margin-top: 16px; animation: pulseGlow 2.5s ease-in-out infinite; }}
        .info-text {{ color: #999; font-size: 13px; margin-top: 18px; }}
        {extra_style}
    </style>
</head>
<body>
    <div class="container">
        <h1>⚫ ObsidianExchange</h1>
        <div class="pair">🔄 {coin_from} → {coin_to}</div>
        <div class="amount">≈ {amount_from} {coin_from}</div>
        <div class="row"><span>Получите</span><b>{address_to}</b></div>
        <div class="status-box">Статус: {status_label}</div>
        {action_block}
    </div>
</body>
</html>"""
    return html

@app.post("/trocador/webhook")
async def trocador_webhook(request: Request, token: str = None):
    try:
        raw = await request.body()
        data = {}
        if raw:
            try:
                data = json.loads(raw)
            except Exception:
                data = {}
        if not data:
            data = dict(request.query_params)
        audit_log("trocador_webhook_received", f"token={token} data={data}")

        new_status = data.get('status') or data.get('Status')
        trocador_id = data.get('id') or data.get('ID')

        with db_conn(5) as conn:
            c = conn.cursor()
            if token:
                c.execute("SELECT session_token, user_id, coin_from, coin_to, amount_from, status FROM swap_sessions WHERE session_token=?", (token,))
            elif trocador_id:
                c.execute("SELECT session_token, user_id, coin_from, coin_to, amount_from, status FROM swap_sessions WHERE trocador_id=?", (trocador_id,))
            else:
                conn.close()
                return JSONResponse(status_code=400, content={})
            row = c.fetchone()
            if not row:
                conn.close()
                return JSONResponse(status_code=404, content={})
            session_token, user_id, coin_from, coin_to, amount_to, old_status = row

            if not new_status and trocador_id:
                from providers.trocador import TrocadorProvider
                info = TrocadorProvider().get_status(trocador_id)
                new_status = info.get('Status')
                data = info

            if new_status and new_status != old_status:
                c.execute("UPDATE swap_sessions SET status=?, updated_at=datetime('now') WHERE session_token=?", (new_status, session_token))
                conn.commit()
                if new_status == 'finished':
                    received = data.get('AmountReceived') or data.get('AmountTo') or amount_to
                    notify_telegram(user_id, f"✅ Своп {coin_from} → {coin_to} завершён!\nПолучено: {received} {coin_to}")
        return JSONResponse(status_code=200, content={})
    except Exception as e:
        logger.error(f"Trocador webhook error: {e}")
        return JSONResponse(status_code=200, content={})

# --- Gateway Endpoint (упрощённый) ---
@app.get("/gateway/{order_id}")
async def gateway(order_id: str, bank: str = "sber"):
    deep_links = {
        "sber": "https://sberbank.ru/pay/sbp?qrcode=...",
        "tbank": "https://www.tbank.ru/pay/qr/...",
        "alfa": "https://alfa.link/a/qr/...",
        "vtb": "https://vtb.ru/pay/sbp?...",
    }
    redirect_url = deep_links.get(bank, "https://obsidian-exchange.org/error")
    audit_log("gateway_redirect", f"order={order_id} bank={bank} url={redirect_url}")
    return RedirectResponse(url=redirect_url)

# --- Вебхуки ---
@app.post("/greenpay/webhook")
async def greenpay_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get('X-Signature', '')
    expected = hmac.new(GREENPAY_API_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401)
    data = json.loads(raw)
    audit_log("greenpay_webhook_received", str(data))
    external_id = data.get('external_id', '') or ''
    status = data.get('status')
    order_id = None
    if external_id.startswith('obsidian_'):
        order_id = external_id.split('_', 1)[1]
    if not order_id:
        order_id = (data.get('additional_info') or {}).get('order_id')
    if order_id and status == 'success':
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()
            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if row and row[0] and int(row[0]) > 0:
            notify_telegram(row[0], (
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Заявка <b>#{order_id}</b> принята — выплата будет произведена в ближайшее время."
            ))
    audit_log("greenpay_webhook_processed", f"order={order_id} status={status}")
    return JSONResponse(status_code=200, content={})

@app.post("/montera/webhook")
async def montera_webhook(request: Request):
    token = request.headers.get('Access-Token', '')
    if not hmac.compare_digest(token, MONTERA_API_TOKEN):
        raise HTTPException(status_code=401)
    data = await request.json()
    audit_log("montera_webhook_received", str(data))
    external_id = data.get('external_id', '') or ''
    status = data.get('status')
    requested_type = data.get('requested_type')  # 'video' или 'pdf-success'
    order_id = None
    if external_id.startswith('obsidian_'):
        order_id = external_id.split('_', 1)[1]

    if order_id and status == 'success':
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()

    if order_id and requested_type in ('video', 'pdf-success'):
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET verification_requested=? WHERE order_id=?", (requested_type, order_id))
            conn.commit()
            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if row and row[0] and row[0] > 0:
            user_id = row[0]
            deep_link = f"https://t.me/{BOT_USERNAME}?start=verify_{order_id}"
            if requested_type == 'video':
                text = (f"🎥 <b>Требуется видео-подтверждение — заявка #{order_id}</b>\n\n"
                        f"Для завершения обмена необходимо короткое видео (5–15 сек).\n\n"
                        f"Откройте PDF-чек из банковского приложения и запишите видео, "
                        f"показывая экран с чеком об операции. Детали платежа должны быть чётко видны.\n\n"
                        f"Нажмите кнопку ниже, откройте бот и отправьте видео.")
            else:
                text = (f"📄 <b>Требуется PDF-чек — заявка #{order_id}</b>\n\n"
                        f"Для завершения обмена отправьте PDF-чек из банковского приложения "
                        f"об успешном платеже.\n\n"
                        f"Нажмите кнопку ниже, откройте бот и отправьте файл.")
            markup = {"inline_keyboard": [[{"text": "📤 Открыть бот и отправить", "url": deep_link}]]}
            notify_telegram(user_id, text, reply_markup=markup)
            notify_admins_tg( f"🔍 Запрошена верификация <b>{requested_type}</b> для заявки #{order_id}")
        audit_log("montera_verification_requested", f"order={order_id} type={requested_type}")

    audit_log("montera_webhook_processed", f"order={order_id} status={status} requested={requested_type}")
    return JSONResponse(status_code=200, content={})

@app.post("/lava/webhook")
async def lava_webhook(request: Request):
    data = await request.json()
    audit_log("lava_webhook_received", str(data))

    # Верификация подписи через дополнительный ключ
    import sys, json as _json, hmac as _hmac, hashlib as _hashlib
    lava_add_key = os.getenv('LAVA_ADDITIONAL_KEY', '')
    received_sign = request.headers.get('Signature', '')
    if lava_add_key and received_sign:
        ordered = dict(sorted(data.items()))
        json_str = _json.dumps(ordered, ensure_ascii=False, separators=(',', ':'))
        expected = _hmac.new(lava_add_key.encode(), json_str.encode(), _hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(expected, received_sign):
            logger.warning(f"Lava webhook bad signature: expected={expected[:16]}... got={received_sign[:16]}...")
            raise HTTPException(status_code=401)

    order_ref  = data.get('orderId', '') or ''
    raw_status = data.get('status')
    order_id   = order_ref.replace('obsidian_', '') if order_ref.startswith('obsidian_') else None

    # Lava: status 1 = успешно оплачен, 2 = отменён
    if raw_status == 1 or raw_status == 'success':
        paid = True
    else:
        paid = False

    if order_id and paid:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()
            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if row and row[0] and int(row[0]) > 0:
            notify_telegram(row[0], (
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Заявка <b>#{order_id}</b> принята — выплата будет произведена в ближайшее время."
            ))
    audit_log("lava_webhook_processed", f"order={order_id} status={raw_status} paid={paid}")
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.post("/brabus/webhook")
async def brabus_webhook(request: Request):
    token = request.headers.get('X-Notification-Token', '')
    if BRABUS_NOTIFICATION_TOKEN and not hmac.compare_digest(token, BRABUS_NOTIFICATION_TOKEN):
        raise HTTPException(status_code=401)
    data = await request.json()
    audit_log("brabus_webhook_received", str(data))
    # Структура: {"notificationType": "invoice", "invoice": {"internalId": "...", "status": "paid", ...}}
    invoice = data.get('invoice') or data  # fallback на flat если вдруг старый формат
    internal_id = invoice.get('internalId', '') or ''
    status = invoice.get('status')
    order_id = None
    if internal_id.startswith('obsidian_'):
        order_id = internal_id.split('_', 1)[1]
    if order_id and status in ('paid',):
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()
            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if row and row[0] and int(row[0]) > 0:
            notify_telegram(row[0], (
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Заявка <b>#{order_id}</b> принята — выплата будет произведена в ближайшее время."
            ))
    elif order_id and status in ('canceled', 'expired'):
        audit_log("brabus_webhook_cancelled", f"order={order_id} status={status}")
    audit_log("brabus_webhook_processed", f"order={order_id} status={status}")
    return JSONResponse(status_code=200, content={})

@app.post("/stormtrade/webhook")
async def stormtrade_webhook(request: Request):
    # StormTrade — тот же Merchant Integration API, что Brabus:
    # токен в X-Notification-Token, тело {"notificationType": "invoice", "invoice": {...}}
    token = request.headers.get('X-Notification-Token', '')
    if STORMTRADE_NOTIFICATION_TOKEN and not hmac.compare_digest(token, STORMTRADE_NOTIFICATION_TOKEN):
        raise HTTPException(status_code=401)
    data = await request.json()
    audit_log("stormtrade_webhook_received", str(data))
    invoice = data.get('invoice') or data
    internal_id = invoice.get('internalId', '') or ''
    status = invoice.get('status')
    order_id = None
    if internal_id.startswith('obsidian_'):
        order_id = internal_id.split('_', 1)[1]
    if order_id and status in ('paid',):
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()
            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if row and row[0] and int(row[0]) > 0:
            notify_telegram(row[0], (
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Заявка <b>#{order_id}</b> принята — выплата будет произведена в ближайшее время."
            ))
    elif order_id and status in ('canceled', 'expired'):
        audit_log("stormtrade_webhook_cancelled", f"order={order_id} status={status}")
    audit_log("stormtrade_webhook_processed", f"order={order_id} status={status}")
    return JSONResponse(status_code=200, content={})

@app.post("/xpay/webhook")
async def xpay_webhook(request: Request):
    # XPayConnect шлёт вебхук только при success; подпись в x-api-key —
    # SHA-256 от '<API_KEY>|<сырое тело>' (docs.xpayconnect.io/concepts/webhooks.md)
    body_bytes = await request.body()
    received = request.headers.get('x-api-key', '')
    if XPAY_API_KEY:
        expected = hashlib.sha256(XPAY_API_KEY.encode() + b'|' + body_bytes).hexdigest()
        if not hmac.compare_digest(expected, received):
            logger.warning(f"XPay webhook bad signature: got={received[:16]}...")
            raise HTTPException(status_code=401)
    try:
        data = json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400)
    audit_log("xpay_webhook_received", str(data))
    # order_id = наш external_id формата obsidian_{order_id}_{ts}
    external = data.get('order_id', '') or ''
    status = data.get('status')
    order_id = None
    if external.startswith('obsidian_'):
        order_id = external.split('_')[1]
    if order_id and status == 'success':
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
            conn.commit()
            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if row and row[0] and int(row[0]) > 0:
            notify_telegram(row[0], (
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"Заявка <b>#{order_id}</b> принята — выплата будет произведена в ближайшее время."
            ))
    audit_log("xpay_webhook_processed", f"order={order_id} status={status}")
    return JSONResponse(status_code=200, content={})

@app.post("/payment/callback")
async def payment_callback(request: Request):
    from urllib.parse import parse_qs
    body = (await request.body()).decode()
    data = parse_qs(body)
    order_id = data.get('order_id', [None])[0]
    key = data.get('key', [''])[0]
    if key != SECRET_KEY:
        raise HTTPException(status_code=403)
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
        conn.commit()
    return JSONResponse(status_code=200, content={})

@app.post("/api/ai-ask")
async def api_ai_ask(request: Request):
    if not AI_ENABLED:
        return {"answer": "AI-ассистент недоступен."}
    try:
        body = await request.json()
        q = str(body.get("question", ""))[:500]
        if not q:
            return {"answer": "Задайте вопрос."}

        async def stream_gen():
            gen = await _ask_ai(q, stream=True)
            async for chunk in gen:
                yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream_gen(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    except Exception as e:
        return {"answer": f"Ошибка: {e}"}

@app.get("/admin/analytics/data")
async def analytics_data(request: Request):
    """Real-time analytics data for admin dashboard."""
    import sqlite3 as _sq

    def qry(sql, params=()):
        with _sq.connect(DB_PATH, timeout=5) as c:
            c.row_factory = _sq.Row
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    daily = qry("""
        SELECT strftime('%m-%d', created_at) as day,
               COUNT(*) as orders,
               SUM(rub_amount) as volume,
               SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END) as paid
        FROM orders WHERE created_at > date('now','-14 days')
        GROUP BY day ORDER BY day
    """)
    hourly = qry("""
        SELECT CAST(strftime('%H', created_at) AS INTEGER) as hour, COUNT(*) as cnt
        FROM orders GROUP BY hour ORDER BY hour
    """)
    by_currency = qry(
        "SELECT currency, COUNT(*) as cnt, SUM(rub_amount) as vol FROM orders GROUP BY currency"
    )
    by_status = qry("SELECT status, COUNT(*) as cnt FROM orders GROUP BY status")
    by_provider = qry(
        "SELECT provider, is_healthy, failed_count, avg_response_time FROM provider_health"
    )
    recent = qry("""
        SELECT o.order_id, o.currency, o.rub_amount, o.status, o.created_at, o.username,
               (SELECT ps.provider FROM payment_sessions ps WHERE ps.order_id=o.order_id ORDER BY ps.session_id DESC LIMIT 1) as provider
        FROM orders o ORDER BY o.order_id DESC LIMIT 20
    """)
    totals_row = qry("""
        SELECT COUNT(*) as total_orders,
               SUM(rub_amount) as total_volume,
               SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END) as paid_orders,
               SUM(CASE WHEN status IN ('paid','sent') THEN rub_amount ELSE 0 END) as paid_volume
        FROM orders
    """)

    try:
        from services.payment_service import PaymentService
        smart_router_status = PaymentService().get_provider_status()
    except Exception as e:
        smart_router_status = {"error": str(e)}

    return {
        "daily": daily,
        "hourly": hourly,
        "by_currency": by_currency,
        "by_status": by_status,
        "providers": by_provider,
        "recent": recent,
        "totals": totals_row[0] if totals_row else {},
        "smart_router": smart_router_status,
    }


@app.get("/admin/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    """Admin analytics dashboard — protected by web session + ADMIN_ID match."""
    from auth import get_web_user
    web_user = get_web_user(request)
    if not web_user:
        return RedirectResponse(url="/login?next=/admin/analytics", status_code=302)
    # Check admin: telegram_id must match ADMIN_ID or email contains 'admin'
    tg_id = web_user.get("telegram_id")
    email = web_user.get("email", "")
    if str(tg_id) not in {str(a) for a in ADMIN_IDS} and "admin" not in email:
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return templates.TemplateResponse(request, "admin_analytics.html")


# ── Фоновые задачи ──

async def cleanup_expired_orders():
    """
    Каждые 10 минут: помечает pending-заявки старше 2 часов как 'expired'.
    Не трогает paid/sent.
    """
    while True:
        try:
            with db_conn(5) as conn:
                c = conn.cursor()
                result = c.execute("""
                    UPDATE orders SET status='expired', updated_at=datetime('now')
                    WHERE status='pending'
                    AND datetime(created_at) < datetime('now', '-2 hours')
                    AND order_id NOT IN (
                        SELECT DISTINCT order_id FROM payment_sessions
                        WHERE status='invoice_created'
                        AND datetime(expires_at) > datetime('now')
                    )
                """)
                expired = result.rowcount
                conn.commit()
                if expired > 0:
                    logger.info(f"[cleanup] Expired {expired} abandoned pending orders")
                    # Отменяем Brabus-инвойсы для истёкших заявок (защита от зависших сделок)
                    try:
                        with db_conn(5) as conn2:
                            c2 = conn2.cursor()
                            c2.execute("""
                                SELECT ps.provider_invoice_id, ps.provider
                                FROM payment_sessions ps
                                JOIN orders o ON o.order_id = ps.order_id
                                WHERE o.status='expired'
                                  AND ps.provider LIKE 'brabus%'
                                  AND ps.provider_invoice_id IS NOT NULL
                                  AND datetime(o.updated_at) > datetime('now', '-15 minutes')
                            """)
                            brabus_to_cancel = c2.fetchall()
                        for inv_id, prov in brabus_to_cancel:
                            variant = prov.split(':', 1)[1] if ':' in prov else None
                            try:
                                from providers.brabus import BrabusProvider
                                if variant:
                                    ok = BrabusProvider(variant=variant).cancel_order(inv_id)
                                else:
                                    ok = BrabusProvider.cancel_any(inv_id)
                                if ok:
                                    logger.info(f"[cleanup] Brabus cancelled {inv_id}")
                            except Exception as ce:
                                logger.warning(f"[cleanup] Brabus cancel {inv_id}: {ce}")
                    except Exception as e:
                        logger.error(f"[cleanup] Brabus cancel loop error: {e}")
        except Exception as e:
            logger.error(f"[cleanup] Error: {e}")
        await asyncio.sleep(600)  # каждые 10 минут


async def vertu_poll_task():
    """
    Каждые 30 секунд: опрашивает статусы pending-заявок Vertu.
    У Vertu нет вебхуков (по OpenAPI-спеке) — единственный способ узнать
    об оплате это GET /v1/deals/{platform_id}/.
    """
    if not os.getenv('VERTU_LOGIN', ''):
        logger.info("[vertu_poll] VERTU_LOGIN не задан — опрос не запускается")
        return
    while True:
        try:
            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT ps.session_token, ps.provider_invoice_id, ps.order_id
                    FROM payment_sessions ps
                    JOIN orders o ON o.order_id = ps.order_id
                    WHERE ps.provider='vertu'
                      AND ps.status='invoice_created'
                      AND ps.provider_invoice_id IS NOT NULL
                      AND o.status='pending'
                      AND datetime(ps.created_at) > datetime('now', '-2 hours')
                """)
                rows = c.fetchall()
            if rows:
                from providers.vertu import VertuProvider
                provider = VertuProvider()
                for token, inv_id, order_id in rows:
                    try:
                        info = await asyncio.to_thread(provider.get_status, inv_id)
                    except Exception as e:
                        logger.warning(f"[vertu_poll] {inv_id}: {e}")
                        continue
                    status = info.get('status')
                    if status == 'paid':
                        with db_conn(5) as conn:
                            c = conn.cursor()
                            c.execute("UPDATE orders SET status='paid', updated_at=datetime('now') "
                                      "WHERE order_id=? AND status='pending'", (order_id,))
                            c.execute("UPDATE payment_sessions SET status='paid', updated_at=datetime('now') "
                                      "WHERE session_token=?", (token,))
                            conn.commit()
                            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
                            row = c.fetchone()
                        audit_log("vertu_polled_paid", f"order={order_id} inv={inv_id}")
                        logger.info(f"[vertu_poll] order {order_id} marked paid")
                        if row and row[0] and int(row[0]) > 0:
                            notify_telegram(row[0], (
                                f"✅ <b>Оплата подтверждена!</b>\n\n"
                                f"Заявка <b>#{order_id}</b> принята — выплата будет произведена в ближайшее время."
                            ))
                    elif status == 'failed':
                        with db_conn(5) as conn:
                            conn.execute("UPDATE payment_sessions SET status='failed', updated_at=datetime('now') "
                                         "WHERE session_token=?", (token,))
                            conn.commit()
                        audit_log("vertu_polled_failed", f"order={order_id} inv={inv_id}")
        except Exception as e:
            logger.error(f"[vertu_poll] Error: {e}")
        await asyncio.sleep(30)


async def health_check_task():
    """
    Каждые 5 минут: проверяет здоровье провайдеров и пишет в лог.
    Если все провайдеры нездоровы — шлёт алерт в Telegram.
    """
    import httpx
    bot_token = BOT_TOKEN
    admin_id = str(ADMIN_ID)  # для условия ниже; рассылка идёт всем ADMIN_IDS

    last_alert_time = 0.0

    while True:
        try:
            from services.smart_router import get_health_scores
            scores = get_health_scores()
            healthy = [p for p, s in scores.items() if s.get("is_healthy")]
            if scores and not healthy and bot_token and admin_id and admin_id != "0":
                now = asyncio.get_event_loop().time()
                if now - last_alert_time > 1800:  # не чаще раза в 30 мин
                    last_alert_time = now
                    msg = "🚨 <b>Все провайдеры недоступны!</b>\n\nНи один провайдер не прошёл health check. Новые заявки не могут быть созданы."
                    async with httpx.AsyncClient(timeout=10) as client:
                        for _aid in ADMIN_IDS:
                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": _aid, "text": msg, "parse_mode": "HTML"}
                            )
            logger.info(f"[health] Healthy providers: {healthy or ['none']}")
        except Exception as e:
            logger.error(f"[health_check] Error: {e}")
        await asyncio.sleep(300)  # каждые 5 минут


@app.get("/api/system-status")
async def system_status():
    """Публичный endpoint: статус системы для мониторинга."""
    try:
        from services.smart_router import get_health_scores
        scores = get_health_scores()
        healthy_count = sum(1 for s in scores.values() if s.get("is_healthy"))
    except Exception:
        scores = {}
        healthy_count = 0

    with db_conn(5) as conn:
        c = conn.cursor()
        stats = c.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status='expired' THEN 1 ELSE 0 END) as expired
            FROM orders WHERE date(created_at) = date('now')
        """).fetchone()

    return {
        "status": "operational" if healthy_count > 0 else "degraded",
        "providers_healthy": healthy_count,
        "today": {
            "total": stats[0], "pending": stats[1],
            "completed": stats[2], "expired": stats[3]
        }
    }


# --- Обработчики ошибок ---
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(request, "404.html", status_code=404)

@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return templates.TemplateResponse(request, "500.html", status_code=500)


# --- Запуск ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5001)
