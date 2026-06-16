from contextlib import contextmanager
import asyncio, sqlite3, random, requests, os, sys, re, logging, time, csv, hmac, hashlib, aiohttp
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO, StringIO
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
                           CallbackQuery, FSInputFile, ContentType)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import qrcode
from bitcoinlib.wallets import Wallet, wallet_delete
from tronpy import Tron
from tronpy.keys import PrivateKey

# ---------- ЛОГИРОВАНИЕ ----------
log_handler = RotatingFileHandler('/root/bot/bot.log', maxBytes=10*1024*1024, backupCount=5)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[log_handler, logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

# ---------- ЗАГРУЗКА .env ----------
def load_env():
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
load_env()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
RELAY_SITE = os.getenv('RELAY_SITE', 'http://127.0.0.1:5000')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')
MIN_AMOUNT = float(os.getenv('MIN_AMOUNT', 1000))
MAX_AMOUNT = float(os.getenv('MAX_AMOUNT', 500000))
HIGH_AMOUNT = float(os.getenv('HIGH_AMOUNT', 100000))
DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')

@contextmanager
def db_conn(timeout=5):
    _conn = sqlite3.connect(DB_PATH, timeout=timeout)
    try:
        yield _conn
    finally:
        _conn.close()

RELAY_SECRET = os.getenv('RELAY_SECRET', '')
COMMISSION_PERCENT = float(os.getenv('COMMISSION_PERCENT', 12))
REFERRAL_BONUS_PERCENT = float(os.getenv('REFERRAL_BONUS_PERCENT', 10))
REFERRAL_DUST_BTC = 0.00002
REVIEWS_CHANNEL_ID = os.getenv('REVIEWS_CHANNEL_ID', '@ObsidianReviews')
SELL_BTC_ADDRESS = os.getenv('SELL_BTC_ADDRESS', '')
SELL_LTC_ADDRESS = os.getenv('SELL_LTC_ADDRESS', '')
SELL_USDT_ADDRESS = os.getenv('SELL_USDT_ADDRESS', '')

# ---------- ИЗОБРАЖЕНИЯ ДЛЯ ШАГОВ ОБМЕНА ----------
IMAGES_DIR = Path(__file__).parent / 'images'
IMG_CURRENCIES = IMAGES_DIR / 'exchange_currencies.png'
IMG_15MIN = IMAGES_DIR / 'exchange_15min.png'
IMG_ORDERS_HISTORY = IMAGES_DIR / 'orders_history.png'
IMG_REFERRAL = IMAGES_DIR / 'referral_program.png'
IMG_SUCCESS = IMAGES_DIR / 'success.png'
IMG_SECURITY = IMAGES_DIR / 'security.png'

if not BOT_TOKEN or not ADMIN_ID:
    logger.error("BOT_TOKEN или ADMIN_ID не заданы")
    sys.exit(1)

# ---------- PID ----------
PID_FILE = '/var/run/exchange-bot.pid'
def check_single_instance():
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            pid = f.read().strip()
        try:
            os.kill(int(pid), 0)
        except OSError:
            os.remove(PID_FILE)
        else:
            logger.error(f"Бот уже запущен (PID {pid}). Выход.")
            sys.exit(1)
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
def remove_pid():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
check_single_instance()
import atexit; atexit.register(remove_pid)

# ---------- ИНИЦИАЛИЗАЦИЯ ----------
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ---------- FSM ----------
class Exchange(StatesGroup):
    currency = State()
    amount = State()
    crypto_amount = State()
    captcha = State()
    address = State()
    payment_method = State()

class Review(StatesGroup):
    comment = State()

class Swap(StatesGroup):
    amount = State()
    address = State()

class Sell(StatesGroup):
    currency = State()
    amount = State()
    phone = State()

# ---------- БАЗА ДАННЫХ ----------
def init_db():
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("PRAGMA journal_mode=WAL")
        c.execute('''CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            username TEXT, currency TEXT NOT NULL DEFAULT 'BTC',
            rub_amount REAL NOT NULL, crypto_address TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            paid_btc_tx TEXT, updated_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS referrals (
            referrer_id INTEGER, referred_id INTEGER, bonus_paid INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, total_bonus_btc REAL DEFAULT 0,
            PRIMARY KEY (referrer_id, referred_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS blocked_users (
            user_id INTEGER PRIMARY KEY, reason TEXT, blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admin_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL,
            action TEXT NOT NULL, target_id INTEGER, details TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, rating INTEGER, comment TEXT,
            status TEXT NOT NULL DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS swap_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_token TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            coin_from TEXT, coin_to TEXT,
            amount_from REAL,
            address_to TEXT,
            trocador_id TEXT,
            trocador_url TEXT,
            status TEXT DEFAULT 'created',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')))''')
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_order ON reviews(order_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_swap_token ON swap_sessions(session_token)")
        conn.commit()
init_db()

# ---------- КЭШ КУРСА ----------
_btc_cache = {"rate": 0, "ts": 0}
_ltc_cache = {"rate": 0, "ts": 0}
_usdt_cache = {"rate": 0, "ts": 0}


# ---------- ПРОГРЕССИВНАЯ КОМИССИЯ ----------
VIP_TIERS = [
    (300_000, 'Platinum', -10),
    (100_000, 'Gold',     -6),
    (30_000,  'Silver',   -3),
    (0,       'Standard',  0),
]

def get_user_vip(user_id: int) -> tuple:
    """Возвращает (tier_name, discount_pct) для пользователя."""
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT total_rub FROM user_vip_volume WHERE user_id=?", (user_id,))
            row = c.fetchone()
        total = row[0] if row else 0
    except Exception:
        total = 0
    for threshold, name, disc in VIP_TIERS:
        if total >= threshold:
            return name, disc
    return 'Standard', 0

def update_user_vip_volume(user_id: int, rub_amount: float):
    """Прибавляет объём к накопительному VIP-счётчику."""
    try:
        with db_conn(5) as conn:
            conn.execute("""INSERT INTO user_vip_volume (user_id, total_rub, updated_at)
                VALUES (?,?,datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    total_rub=total_rub+excluded.total_rub,
                    updated_at=datetime('now')""", (user_id, rub_amount))
            conn.commit()
    except Exception as e:
        logger.error(f"VIP volume update error: {e}")

def get_commission_percent(amount_rub, user_id: int = None):
    base = 27 if amount_rub < 5000 else (23 if amount_rub < 15000 else 19)
    if user_id:
        _, disc = get_user_vip(user_id)
        base = max(2, base + disc)
    return base
def get_cached_rate(coin):
    import time, requests
    _btc_cache = {"rate": 0, "ts": 0}
    _ltc_cache = {"rate": 0, "ts": 0}
    _usdt_cache = {"rate": 0, "ts": 0}
    cache = _btc_cache if coin == "BTC" else (_ltc_cache if coin == "LTC" else _usdt_cache)
    now = time.time()
    if cache["rate"] and (now - cache["ts"]) < 600:
        return cache["rate"]
    try:
        if coin == "BTC":
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=rub", timeout=8)
            rate = r.json()["bitcoin"]["rub"]
        elif coin == "LTC":
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=rub", timeout=8)
            rate = r.json()["litecoin"]["rub"]
        else:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub", timeout=8)
            rate = r.json()["tether"]["rub"]
    except:
        try:
            if coin == "BTC":
                r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB")
                rate = float(r1.json()["price"]) * float(r2.json()["price"])
            elif coin == "LTC":
                r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=LTCUSDT")
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB")
                rate = float(r1.json()["price"]) * float(r2.json()["price"])
            else:
                r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB")
                rate = float(r.json()["price"])
        except:
            if coin == "BTC": return cache.get("rate", 6500000)
            elif coin == "LTC": return cache.get("rate", 4000)
            else: return cache.get("rate", 85)
    cache["rate"] = rate
    cache["ts"] = now
    return rate

def get_rate_with_markup(coin, amount=None):
    if amount is None:
        commission = 23
    else:
        if coin == 'USDT':
            commission = float(os.getenv('USDT_COMMISSION_PERCENT', 2))
        else:
            commission = get_commission_percent(amount)
    return get_cached_rate(coin) / (1 - commission / 100)

# ---------- ВАЛИДАЦИЯ АДРЕСОВ ----------
def validate_crypto_address(addr, currency):
    if currency == 'BTC':
        return any(re.match(p, addr) for p in [r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', r'^bc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == 'LTC':
        return any(re.match(p, addr) for p in [r'^[LM][1-9A-HJ-NP-Za-km-z]{26,33}$', r'^ltc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == 'USDT':
        return re.match(r'^T[A-Za-z1-9]{33}$', addr) is not None
    return False

# ---------- ФОРМАТИРОВАНИЕ РЕКВИЗИТОВ GREENPAY ----------
def format_requisites(raw):
    """Пытается собрать читаемые реквизиты из ответа GreenPay /requisites/request/."""
    if not isinstance(raw, dict):
        return f"Реквизиты: {raw}"
    requisites = raw.get('requisites') or raw
    lines = []
    field_labels = [
        ('card_number', '💳 Карта'),
        ('phone', '📱 Телефон'),
        ('bank_name', '🏦 Банк'),
        ('bank', '🏦 Банк'),
        ('recipient', '👤 Получатель'),
        ('holder_name', '👤 Получатель'),
        ('payment_link', '🔗 Ссылка'),
        ('qr_data', '📲 QR-данные'),
    ]
    for key, label in field_labels:
        value = requisites.get(key)
        if value:
            lines.append(f"{label}: <code>{value}</code>")
    if lines:
        return "\n".join(lines)
    logger.warning(f"Не удалось распознать реквизиты GreenPay, сырой ответ: {raw}")
    return f"Реквизиты: <code>{raw}</code>"

# ---------- УВЕДОМЛЕНИЯ ----------
async def notify_admin(order_id, user_id, rub_amount, address, currency):
    rate = get_rate_with_markup(currency, rub_amount)
    crypto_amount = round(rub_amount / rate, 8) if rate else 0
    text = (f"🆕 Новая заявка #{order_id}\nПользователь: {user_id}\n"
            f"Сумма: {rub_amount} RUB ≈ {crypto_amount} {currency}\nАдрес: {address}")
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_{order_id}")]])
        await bot.send_message(ADMIN_ID, text, reply_markup=kb, disable_notification=False)
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")
    if rub_amount >= HIGH_AMOUNT:
        await bot.send_message(ADMIN_ID, f"⚠️ Крупная заявка #{order_id} на {rub_amount:,.0f} RUB")

# ---------- /start ----------
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    # Реферальная диплинк-регистрация: /start ref_<id>
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith('ref_'):
            try:
                ref_id = int(parts[1][4:])
                if ref_id != message.from_user.id:
                    with db_conn(10) as conn_ref:
                        c_ref = conn_ref.cursor()
                        c_ref.execute("SELECT 1 FROM referrals WHERE referred_id=?", (message.from_user.id,))
                        if not c_ref.fetchone():
                            c_ref.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                                           (ref_id, message.from_user.id))
                        conn_ref.commit()
            except (ValueError, IndexError):
                pass
    btc_rate = get_cached_rate('BTC')
    ltc_rate = get_cached_rate('LTC')
    usdt_rate = get_cached_rate('USDT')
    btc_markup = round(btc_rate / (1 - COMMISSION_PERCENT/100), 2)
    ltc_markup = round(ltc_rate / (1 - COMMISSION_PERCENT/100), 2)
    usdt_markup = round(usdt_rate / (1 - COMMISSION_PERCENT/100), 2)
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='sent'", (datetime.now().strftime("%Y-%m-%d"),))
        sent_today = c.fetchone()[0]
    vip_name_s, _ = get_user_vip(message.from_user.id)
    vip_badge_s = {'Platinum': '💎 Platinum', 'Gold': '🥇 Gold', 'Silver': '🥈 Silver'}.get(vip_name_s, '')
    welcome_text = (
        f"🟣 ObsidianExchange{(' — ' + vip_badge_s) if vip_badge_s else ''}\n"
        f"├ 💱 Купить: RUB → BTC | LTC | USDT\n"
        f"├ 💰 Продать: BTC | LTC | USDT → RUB\n"
        f"├ 🔄 Своп: BTC ↔ LTC ↔ USDT (~1%)\n"
        f"├ BTC: {btc_markup:,} RUB\n"
        f"├ LTC: {ltc_markup:,} RUB\n"
        f"├ USDT: {usdt_markup:,} RUB\n"
        f"├ 🔒 Non‑KYC · без верификации\n"
        f"├ ⚡ Автовыплаты · курс 15 мин\n"
        f"└ 🛡️ Некастодиальный своп\n\n"
        f"📊 Сегодня выполнено: {sent_today} обменов\n\n"
        f"👇 Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Купить крипту (RUB→)", callback_data="menu_exchange"),
         InlineKeyboardButton(text="💰 Продать крипту (→RUB)", callback_data="menu_sell")],
        [InlineKeyboardButton(text="🔄 Своп криптовалют", callback_data="menu_swap")],
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="menu_orders"), InlineKeyboardButton(text="👥 Рефералка", callback_data="menu_ref")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"), InlineKeyboardButton(text="🆘 Поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="⭐ Отзывы", callback_data="menu_reviews"), InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu_about")],
        [InlineKeyboardButton(text="🌐 WebApp", url=f"{PUBLIC_RELAY}/webapp")]
    ])
    await message.answer(welcome_text, reply_markup=kb)

# ---------- ОБРАБОТЧИКИ МЕНЮ ----------
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    btc_rate = get_cached_rate('BTC')
    ltc_rate = get_cached_rate('LTC')
    usdt_rate = get_cached_rate('USDT')
    btc_markup = round(btc_rate / (1 - COMMISSION_PERCENT/100), 2)
    ltc_markup = round(ltc_rate / (1 - COMMISSION_PERCENT/100), 2)
    usdt_markup = round(usdt_rate / (1 - COMMISSION_PERCENT/100), 2)
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='sent'", (datetime.now().strftime("%Y-%m-%d"),))
        sent_today = c.fetchone()[0]
    vip_name, _ = get_user_vip(callback.from_user.id)
    vip_badge = {'Platinum': '💎 Platinum', 'Gold': '🥇 Gold', 'Silver': '🥈 Silver'}.get(vip_name, '')
    welcome_text = (
        f"🟣 ObsidianExchange{(' — ' + vip_badge) if vip_badge else ''}\n"
        f"├ 💱 Купить: RUB → BTC | LTC | USDT\n"
        f"├ 💰 Продать: BTC | LTC | USDT → RUB\n"
        f"├ 🔄 Своп: BTC ↔ LTC ↔ USDT (~1%)\n"
        f"├ BTC: {btc_markup:,} RUB\n"
        f"├ LTC: {ltc_markup:,} RUB\n"
        f"├ USDT: {usdt_markup:,} RUB\n"
        f"├ 🔒 Non‑KYC · без верификации\n"
        f"├ ⚡ Автовыплаты · курс 15 мин\n"
        f"└ 🛡️ Некастодиальный своп\n\n"
        f"📊 Сегодня выполнено: {sent_today} обменов\n\n"
        f"👇 Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Купить крипту (RUB→)", callback_data="menu_exchange"),
         InlineKeyboardButton(text="💰 Продать крипту (→RUB)", callback_data="menu_sell")],
        [InlineKeyboardButton(text="🔄 Своп криптовалют", callback_data="menu_swap")],
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="menu_orders"), InlineKeyboardButton(text="👥 Рефералка", callback_data="menu_ref")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"), InlineKeyboardButton(text="🆘 Поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="⭐ Отзывы", callback_data="menu_reviews"), InlineKeyboardButton(text="ℹ️ О нас", callback_data="menu_about")],
        [InlineKeyboardButton(text="🌐 WebApp", url=f"{PUBLIC_RELAY}/webapp")]
    ])
    await callback.message.answer(welcome_text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "menu_exchange")
async def menu_exchange(callback: CallbackQuery, state: FSMContext):
    if is_user_blocked(callback.from_user.id):
        await callback.answer("⛔ Вы превысили лимит заявок или заблокированы.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₿ BTC", callback_data="cur_BTC")],
        [InlineKeyboardButton(text="Ł LTC", callback_data="cur_LTC")],
        [InlineKeyboardButton(text="💵 USDT (TRC20)", callback_data="cur_USDT")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])
    if IMG_CURRENCIES.exists():
        await callback.message.answer_photo(FSInputFile(IMG_CURRENCIES), caption="🟣 💎 Выберите валюту для обмена:", reply_markup=kb)
    else:
        await callback.message.answer("🟣 💎 Выберите валюту для обмена:", reply_markup=kb)
    await callback.answer()

# ---------- СВОП КРИПТОВАЛЮТ (Trocador) ----------
SWAP_COINS = ["BTC", "LTC", "USDT"]
SWAP_NETWORKS = {"BTC": "Mainnet", "LTC": "Mainnet", "USDT": "TRC20"}

@router.callback_query(F.data == "menu_swap")
async def menu_swap(callback: CallbackQuery, state: FSMContext):
    if is_user_blocked(callback.from_user.id):
        await callback.answer("⛔ Вы превысили лимит заявок или заблокированы.", show_alert=True)
        return
    rows = []
    for coin_from in SWAP_COINS:
        for coin_to in SWAP_COINS:
            if coin_from != coin_to:
                rows.append([InlineKeyboardButton(text=f"{coin_from} → {coin_to}", callback_data=f"swap_pair_{coin_from}_{coin_to}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.answer(
        "🟣 🔄 Своп криптовалют\n\n"
        "Прямой обмен BTC, LTC и USDT (TRC20) — без рубля, без участия наших кошельков и без KYC.\n\n"
        "Вы отправляете монеты на указанный адрес, получаете результат сразу на свой кошелёк.\n\n"
        "💰 Комиссия: ~1% (включена в курс, скрытых сборов нет)\n\n"
        "Выберите пару:",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("swap_pair_"))
async def process_swap_pair(callback: CallbackQuery, state: FSMContext):
    _, _, coin_from, coin_to = callback.data.split("_")
    import sys
    sys.path.insert(0, '/root/relay')
    from providers.swapuz import SwapUzProvider
    rate_info = SwapUzProvider().get_rate(coin_from, coin_to, amount=1)
    min_amount = rate_info.get("min_amount")
    min_hint = f"\nМинимум: {min_amount} {coin_from}" if min_amount else ""
    await state.update_data(coin_from=coin_from, coin_to=coin_to)
    await callback.message.answer(
        f"🟣 🔄 {coin_from} → {coin_to}\n\n"
        f"Введите сумму {coin_from}, которую хотите отправить:{min_hint}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Swap.amount)
    await callback.answer()

@router.message(Swap.amount)
async def process_swap_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.').strip())
    except ValueError:
        await message.answer("Введите сумму цифрами.")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return
    data = await state.get_data()
    coin_from = data['coin_from']
    coin_to = data['coin_to']

    import sys
    sys.path.insert(0, '/root/relay')
    from providers.swapuz import SwapUzProvider
    rate_info = SwapUzProvider().get_rate(coin_from, coin_to, amount)
    if "error" in rate_info:
        await message.answer(f"❌ {rate_info['error']}\nПроверьте сумму и попробуйте ещё раз.")
        return

    estimated = rate_info.get("estimated_receive")
    await state.update_data(amount_from=amount, estimated_receive=estimated)
    await message.answer(
        f"📊 Курс: {amount} {coin_from} → ≈ {estimated} {coin_to}\n\n"
        f"📥 Введите адрес {coin_to}, на который придут монеты:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Swap.address)

@router.message(Swap.address)
async def process_swap_address(message: Message, state: FSMContext):
    address = message.text.strip()
    data = await state.get_data()
    coin_from = data['coin_from']
    coin_to = data['coin_to']
    amount_from = data['amount_from']
    estimated = data.get('estimated_receive')
    if not validate_crypto_address(address, coin_to):
        await message.answer("❌ Некорректный адрес для выбранной валюты.")
        return

    import sys
    sys.path.insert(0, '/root/relay')
    from providers.swapuz import SwapUzProvider
    from utils.tokens import generate_session_token

    token = generate_session_token()
    result = SwapUzProvider().create_swap(
        coin_from=coin_from,
        coin_to=coin_to,
        amount=amount_from,
        address=address,
        order_uuid=token,
    )

    if "error" in result:
        await message.answer(f"❌ Не удалось создать своп: {result['error']}\nПопробуйте другую сумму или адрес.")
        await state.clear()
        return

    deposit_address = result['deposit_address']
    uid = result['uid']
    swap_link = f"{PUBLIC_RELAY}/swap/{token}"

    with db_conn(10) as conn:
        conn.execute(
            "INSERT INTO swap_sessions (session_token, user_id, coin_from, coin_to, amount_from, address_to, trocador_id, trocador_url, status, provider, deposit_address) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (token, message.from_user.id, coin_from, coin_to, amount_from, address, uid, swap_link, 'waiting', 'swapuz', deposit_address)
        )
        conn.commit()

    await message.answer(
        f"🟣 🔄 Своп {coin_from} → {coin_to} создан!\n\n"
        f"Отправьте: <b>{amount_from} {coin_from}</b>\n"
        f"На адрес:\n<code>{deposit_address}</code>\n\n"
        f"Ожидаем получения: ≈ {estimated} {coin_to}\n"
        f"Адрес зачисления: <code>{address}</code>\n\n"
        f"⏳ Статус обновится автоматически. Страница свопа:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Статус свопа", url=swap_link)]]),
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data == "menu_orders")
async def menu_orders(callback: CallbackQuery):
    await my_orders(callback.message)
    await callback.answer()

@router.callback_query(F.data == "menu_ref")
async def menu_ref(callback: CallbackQuery):
    username = (await bot.get_me()).username
    ref_link = f"https://t.me/{username}?start=ref_{callback.from_user.id}"
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(total_bonus_btc), 0) FROM referrals WHERE referrer_id=?", (callback.from_user.id,))
        ref_count, total_bonus = c.fetchone()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=ref_link)],
        [InlineKeyboardButton(text="💸 Вывести бонус", callback_data="ref_withdraw")]
    ])
    text = (
        f"🟣 👥 Ваша реферальная ссылка:\n\n<code>{ref_link}</code>\n\n"
        f"👤 Приглашено: {ref_count}\n"
        f"💰 Накоплено бонусов: {total_bonus:.8f} BTC"
    )
    if IMG_REFERRAL.exists():
        await callback.message.answer_photo(FSInputFile(IMG_REFERRAL), caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "ref_withdraw")
async def ref_withdraw(callback: CallbackQuery):
    await callback.answer()
    text = await withdraw_referral_bonus(callback.from_user.id)
    await callback.message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery):
    await profile(callback.message)
    await callback.answer()

@router.callback_query(F.data == "menu_support")
async def menu_support(callback: CallbackQuery):
    await callback.message.answer("🟣 📞 @ObsidianSupBot")
    await callback.answer()

@router.callback_query(F.data == "menu_reviews")
async def menu_reviews(callback: CallbackQuery):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), AVG(rating) FROM reviews WHERE status='published'")
        count, avg_rating = c.fetchone()
    text = "🟣 ⭐ https://t.me/ObsidianReviews"
    if count:
        text += f"\n\n📊 Средняя оценка: {avg_rating:.1f} на основе {count} отзывов"
    await callback.message.answer(text)
    await callback.answer()

@router.callback_query(F.data == "menu_about")
async def menu_about(callback: CallbackQuery):
    await callback.message.answer("🟣 ObsidianExchange — тёмный обменник без KYC. Автовыплаты, поддержка BTC, LTC, USDT, двойная защита.\n\n💳 Оплата: СБП или картой (по реквизитам).")
    await callback.answer()

# ---------- ПРОДАЖА КРИПТЫ (крипта → RUB) ----------
SELL_RECEIVE_ADDRESSES = {'BTC': SELL_BTC_ADDRESS, 'LTC': SELL_LTC_ADDRESS, 'USDT': SELL_USDT_ADDRESS}
SELL_COIN_LABELS = {'BTC': '₿ Bitcoin (BTC)', 'LTC': 'Ł Litecoin (LTC)', 'USDT': '💵 USDT (TRC20)'}
SELL_MIN_AMOUNTS = {'BTC': 0.0005, 'LTC': 0.5, 'USDT': 50}

@router.callback_query(F.data == "menu_sell")
async def menu_sell(callback: CallbackQuery, state: FSMContext):
    if is_user_blocked(callback.from_user.id):
        await callback.answer("⛔ Вы превысили лимит заявок или заблокированы.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₿ Bitcoin (BTC)", callback_data="sell_cur_BTC")],
        [InlineKeyboardButton(text="Ł Litecoin (LTC)", callback_data="sell_cur_LTC")],
        [InlineKeyboardButton(text="💵 USDT (TRC20)", callback_data="sell_cur_USDT")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])
    await callback.message.answer(
        "🟣 💰 <b>Продажа крипты → RUB</b>\n\n"
        "Отправьте нам монеты — мы переведём рубли по СБП на ваш номер телефона.\n\n"
        "Курс: рыночный за вычетом нашей комиссии (~19–27% для BTC/LTC, ~2% для USDT).\n\n"
        "Выберите валюту для продажи:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("sell_cur_"))
async def process_sell_currency(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[2]
    if currency not in SELL_RECEIVE_ADDRESSES:
        await callback.answer("❌ Неверная валюта", show_alert=True)
        return
    receive_addr = SELL_RECEIVE_ADDRESSES[currency]
    if not receive_addr:
        await callback.answer("❌ Продажа этой валюты временно недоступна.", show_alert=True)
        return

    btc_rate = get_cached_rate('BTC')
    ltc_rate = get_cached_rate('LTC')
    usdt_rate = get_cached_rate('USDT')
    rates = {'BTC': btc_rate, 'LTC': ltc_rate, 'USDT': usdt_rate}
    rate = rates.get(currency, 0)
    commission = get_commission_percent(50000, callback.from_user.id)
    sell_rate = round(rate * (1 - commission / 100), 2)

    min_amt = SELL_MIN_AMOUNTS.get(currency, 0.001)
    await state.update_data(sell_currency=currency, sell_rate=sell_rate, sell_receive_addr=receive_addr)
    await state.set_state(Sell.amount)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_sell")]
    ])
    await callback.message.answer(
        f"🟣 💰 <b>Продажа {SELL_COIN_LABELS[currency]}</b>\n\n"
        f"📬 Наш адрес для получения:\n<code>{receive_addr}</code>\n\n"
        f"💱 Курс покупки: <b>{sell_rate:,.2f} RUB</b> за 1 {currency}\n"
        f"(включает нашу комиссию)\n\n"
        f"Минимальная сумма: <b>{min_amt} {currency}</b>\n\n"
        f"💬 Введите <b>сколько {currency} вы отправите</b> нам (только число, например <code>{min_amt}</code>):",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(Sell.amount)
async def process_sell_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("❌ Введите число, например <code>0.01</code>", parse_mode="HTML")
        return
    data = await state.get_data()
    currency = data.get('sell_currency', 'BTC')
    min_amt = SELL_MIN_AMOUNTS.get(currency, 0.001)
    if amount < min_amt:
        await message.answer(f"❌ Минимальная сумма: {min_amt} {currency}")
        return
    sell_rate = data.get('sell_rate', 0)
    rub_amount = round(amount * sell_rate, 2)
    await state.update_data(sell_amount=amount, sell_rub_amount=rub_amount)
    await state.set_state(Sell.phone)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="menu_sell")]
    ])
    await message.answer(
        f"✅ Вы продаёте: <b>{amount} {currency}</b>\n"
        f"💰 Вы получите: <b>≈ {rub_amount:,.2f} RUB</b>\n\n"
        f"📱 Введите ваш <b>номер телефона для СБП</b> (куда перевести рубли):\n"
        f"Формат: <code>79001234567</code> или <code>+79001234567</code>",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.message(Sell.phone)
async def process_sell_phone(message: Message, state: FSMContext):
    phone_raw = message.text.strip().replace(' ', '').replace('-', '')
    if not re.match(r'^\+?7\d{10}$', phone_raw):
        await message.answer("❌ Неверный формат. Введите номер вида <code>79001234567</code>", parse_mode="HTML")
        return
    phone = phone_raw.lstrip('+')
    data = await state.get_data()
    currency = data.get('sell_currency', 'BTC')
    amount = data.get('sell_amount', 0)
    rub_amount = data.get('sell_rub_amount', 0)
    receive_addr = data.get('sell_receive_addr', '')

    try:
        with db_conn(10) as conn:
            c = conn.cursor()
            c.execute("""INSERT INTO sell_orders
                (user_id, currency, crypto_amount, rub_amount, sbp_phone, receive_address, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
                (message.from_user.id, currency, amount, rub_amount, phone, receive_addr, 'pending'))
            sell_id = c.lastrowid
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка создания sell_order: {e}")
        await message.answer("❌ Ошибка сервера. Попробуйте позже.")
        await state.clear()
        return

    await state.clear()

    await message.answer(
        f"✅ <b>Заявка на продажу #{sell_id} создана!</b>\n\n"
        f"📤 Отправьте <b>{amount} {currency}</b> на адрес:\n"
        f"<code>{receive_addr}</code>\n\n"
        f"💰 После подтверждения транзакции мы переведём <b>≈ {rub_amount:,.2f} RUB</b> на СБП <code>{phone}</code>\n\n"
        f"⏳ Обычно выплата проходит в течение 30–60 минут.\n"
        f"📞 Вопросы: @ObsidianSupBot",
        parse_mode="HTML"
    )

    try:
        kb_admin = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выплатить (подтвердить)", callback_data=f"sell_confirm_{sell_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"sell_reject_{sell_id}")]
        ])
        await bot.send_message(
            ADMIN_ID,
            f"💰 <b>Новая заявка на ПРОДАЖУ #{sell_id}</b>\n"
            f"👤 Пользователь: {message.from_user.id} (@{message.from_user.username or '-'})\n"
            f"💸 Продаёт: {amount} {currency}\n"
            f"📬 На наш адрес: <code>{receive_addr}</code>\n"
            f"💵 Выплатить: {rub_amount:,.2f} RUB\n"
            f"📱 СБП: {phone}\n\n"
            f"После получения монет нажмите «Выплатить».",
            reply_markup=kb_admin,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления админа о продаже: {e}")

@router.callback_query(F.data.startswith("sell_confirm_"))
async def sell_confirm(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет прав", show_alert=True)
        return
    sell_id = int(callback.data.split("_")[2])
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, currency, crypto_amount, rub_amount, sbp_phone, status FROM sell_orders WHERE id=?", (sell_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        user_id, currency, crypto_amount, rub_amount, sbp_phone, status = row
        if status == 'paid':
            conn.close()
            await callback.answer("✅ Уже выплачено", show_alert=True)
            return
        c.execute("UPDATE sell_orders SET status='paid', updated_at=datetime('now') WHERE id=?", (sell_id,))
        conn.commit()

    update_user_vip_volume(user_id, rub_amount)

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>Выплачено</b> {rub_amount:,.2f} RUB на {sbp_phone}",
        parse_mode="HTML"
    )
    await callback.answer("✅ Отмечено как выплачено")
    try:
        await bot.send_message(
            user_id,
            f"✅ <b>Заявка #{sell_id} выполнена!</b>\n"
            f"💰 {rub_amount:,.2f} RUB отправлены на СБП <code>{sbp_phone}</code>.",
            parse_mode="HTML"
        )
    except Exception:
        pass

@router.callback_query(F.data.startswith("sell_reject_"))
async def sell_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Нет прав", show_alert=True)
        return
    sell_id = int(callback.data.split("_")[2])
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, sbp_phone FROM sell_orders WHERE id=?", (sell_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        user_id = row[0]
        c.execute("UPDATE sell_orders SET status='rejected', updated_at=datetime('now') WHERE id=?", (sell_id,))
        conn.commit()
    await callback.message.edit_text(callback.message.text + "\n\n❌ <b>Отклонено</b>", parse_mode="HTML")
    await callback.answer("❌ Отклонено")
    try:
        await bot.send_message(
            user_id,
            f"❌ <b>Заявка на продажу #{sell_id} отклонена.</b>\n"
            f"Если у вас вопросы — напишите в поддержку @ObsidianSupBot.",
            parse_mode="HTML"
        )
    except Exception:
        pass

# ---------- ОТЗЫВЫ ----------
@router.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery, state: FSMContext):
    try:
        _, order_id_s, rating_s = callback.data.split("_")
        order_id, rating = int(order_id_s), int(rating_s)
    except (ValueError, IndexError):
        await callback.answer()
        return

    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
        row = c.fetchone()
        if not row or row[0] != callback.from_user.id:
            conn.close()
            await callback.answer("❌ Эта заявка не найдена.", show_alert=True)
            return
        c.execute("SELECT status FROM reviews WHERE order_id=?", (order_id,))
        rev = c.fetchone()
        if not rev or rev[0] != 'pending_rating':
            conn.close()
            await callback.answer("✅ Вы уже оценили эту заявку.", show_alert=True)
            return
        c.execute("UPDATE reviews SET rating=?, status='pending_comment' WHERE order_id=?", (rating, order_id))
        conn.commit()

    await state.update_data(review_order_id=order_id)
    await state.set_state(Review.comment)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Спасибо за оценку {'⭐' * rating}!\nХотите оставить комментарий?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Пропустить", callback_data=f"revskip_{order_id}")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("revskip_"))
async def skip_review_comment(callback: CallbackQuery, state: FSMContext):
    try:
        order_id = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await finalize_review(order_id)
    await callback.answer()


@router.message(Review.comment)
async def process_review_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("review_order_id")
    await state.clear()
    if order_id is None:
        return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("UPDATE reviews SET comment=? WHERE order_id=?", (message.text.strip()[:500], order_id))
        conn.commit()
    await finalize_review(order_id)
    await message.answer("Спасибо за отзыв! 🙏")


async def finalize_review(order_id):
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, rating, comment FROM reviews WHERE order_id=?", (order_id,))
        row = c.fetchone()
        if not row:
            return
        user_id, rating, comment = row
        if rating and rating >= 4:
            c.execute("UPDATE reviews SET status='published' WHERE order_id=?", (order_id,))
            conn.commit()
            comment_text = comment.strip() if comment and comment.strip() else "Без комментария"
        else:
            c.execute("UPDATE reviews SET status='admin_review' WHERE order_id=?", (order_id,))
            conn.commit()
            comment_text = comment.strip() if comment and comment.strip() else "(без комментария)"

    if rating and rating >= 4:
        text = f"{'⭐' * rating}\n\n{comment_text}\n\n— Клиент ObsidianExchange"
        try:
            await bot.send_message(REVIEWS_CHANNEL_ID, text)
        except Exception as e:
            logger.error(f"Не удалось опубликовать отзыв #{order_id} в {REVIEWS_CHANNEL_ID}: {e}")
    else:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"⚠️ Низкая оценка по заявке #{order_id}\n"
                f"👤 user_id: {user_id}\n"
                f"⭐ Оценка: {rating}\n"
                f"💬 Комментарий: {comment_text}"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить админа об отзыве #{order_id}: {e}")

# ---------- ОБМЕН ----------
def generate_captcha():
    a = random.randint(5, 25)
    b = random.randint(5, 25)
    return a, b, a + b

def is_user_blocked(user_id):
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM blocked_users WHERE user_id=?", (user_id,))
            row = c.fetchone()
        return row is not None
    except Exception:
        return False
@router.callback_query(F.data.startswith("cur_"))
async def process_currency(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[1]
    await state.update_data(currency=currency)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Указать сумму в RUB", callback_data="amtmode_rub")],
        [InlineKeyboardButton(text=f"💱 Указать сумму в {currency}", callback_data="amtmode_crypto")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await callback.message.answer("🟣 Как удобнее указать сумму обмена?", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "amtmode_rub")
async def amtmode_rub(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        f"🟣 💵 Введите сумму в RUB\n🔹 Минимум: {MIN_AMOUNT} ₽\n🔹 Максимум: {MAX_AMOUNT} ₽",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Exchange.amount)
    await callback.answer()

@router.callback_query(F.data == "amtmode_crypto")
async def amtmode_crypto(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    currency = data['currency']
    await callback.message.answer(
        f"🟣 💱 Введите сумму в {currency}, которую хотите получить\n"
        f"Бот рассчитает сумму к оплате в RUB с учётом комиссии.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Exchange.crypto_amount)
    await callback.answer()

@router.message(Exchange.amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.').strip())
    except ValueError:
        await message.answer("Введите сумму цифрами.")
        return
    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        await message.answer(f"❌ Сумма должна быть от {MIN_AMOUNT} до {MAX_AMOUNT} RUB.")
        return
    await state.update_data(amount=amount)
    a, b, correct = generate_captcha()
    await state.update_data(captcha_correct=correct)
    await message.answer(
        f"🛡️ Проверка на робота\nСколько будет {a} + {b}?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Exchange.captcha)

@router.message(Exchange.crypto_amount)
async def process_crypto_amount(message: Message, state: FSMContext):
    try:
        crypto_amt = float(message.text.replace(',', '.').strip())
    except ValueError:
        await message.answer("Введите сумму цифрами.")
        return
    if crypto_amt <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    data = await state.get_data()
    currency = data['currency']
    base_rate = get_cached_rate(currency)
    if not base_rate:
        await message.answer("⚠️ Не удалось получить курс. Попробуйте позже.")
        return

    # Прогрессивная комиссия зависит от суммы в RUB, поэтому считаем в несколько проходов
    rub_amount = crypto_amt * base_rate
    for _ in range(3):
        rate = get_rate_with_markup(currency, rub_amount)
        rub_amount = crypto_amt * rate
    rub_amount = round(rub_amount, 2)

    if rub_amount < MIN_AMOUNT or rub_amount > MAX_AMOUNT:
        await message.answer(
            f"❌ Сумма к оплате составит {rub_amount:,.2f} ₽, что выходит за пределы лимитов "
            f"({MIN_AMOUNT:,.0f}–{MAX_AMOUNT:,.0f} ₽).\nВведите другую сумму в {currency}."
        )
        return

    await state.update_data(amount=rub_amount)
    await message.answer(
        f"🟣 💱 Чтобы получить {crypto_amt} {currency}, нужно оплатить:\n"
        f"💵 {rub_amount:,.2f} ₽ (комиссия {get_commission_percent(rub_amount)}%)"
    )
    a, b, correct = generate_captcha()
    await state.update_data(captcha_correct=correct)
    await message.answer(
        f"🛡️ Проверка на робота\nСколько будет {a} + {b}?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Exchange.captcha)

@router.message(Exchange.captcha)
async def process_captcha(message: Message, state: FSMContext):
    try:
        answer = int(message.text.strip())
    except ValueError:
        await message.answer("Введите число.")
        return
    data = await state.get_data()
    if answer != data.get("captcha_correct"):
        await message.answer("❌ Капча неверная.")
        await state.clear()
        return
    curr = data['currency']
    await message.answer(
        f"📥 Введите ваш адрес ({curr}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Exchange.address)


# ---------- ПРОВЕРКА ОПЛАТЫ ----------

@router.callback_query(F.data.startswith("paid_"))
async def inline_paid(callback: CallbackQuery):
    try:
        order_id = int(callback.data.split("_")[1])
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id, rub_amount, crypto_address, currency, status FROM orders WHERE order_id=?", (order_id,))
            row = c.fetchone()
        if not row:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        order_user_id, rub_amount, address, currency, status = row
        if status != 'pending':
            await callback.answer("Заявка уже обработана", show_alert=True)
            return
        text = (f"💰 Пользователь сообщает, что оплатил заявку #{order_id}\n"
                f"Пользователь: {order_user_id}\nСумма: {rub_amount} RUB, {currency}\nАдрес: {address}\n\n"
                f"Проверьте поступление оплаты перед подтверждением.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_{order_id}")]])
        await bot.send_message(ADMIN_ID, text, reply_markup=kb, disable_notification=False)
        msg_text = f"✅ Информация об оплате заявки #{order_id} отправлена администратору на проверку. Ожидайте подтверждения."
        await callback.message.edit_caption(caption=msg_text, parse_mode="HTML") if callback.message.photo else await callback.message.edit_text(msg_text, parse_mode="HTML")
        await callback.answer("Отправлено на проверку")
    except Exception as e:
        logger.exception("Ошибка в inline_paid")
        await callback.answer("Ошибка при обновлении статуса", show_alert=True)

@router.callback_query(F.data.startswith("check_"))
async def inline_check_payment(callback: CallbackQuery):
    try:
        order_id = int(callback.data.split("_")[1])
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{RELAY_SITE}/api/order/{order_id}",
                                   params={"key": RELAY_SECRET}) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get('status')
                    tx = data.get('txid')
                else:
                    status = "pending"
                    tx = None
        if status == "sent" and tx:
            text = f"🚀 Заявка #{order_id} полностью выполнена!\n████████████ 100%\nTXID: <code>{tx}</code>"
        elif status == "paid":
            text = f"✅ Заявка #{order_id} оплачена!\n████████░░░░ 50%\nОжидайте отправку..."
        else:
            text = f"⏳ Заявка #{order_id} ожидает оплаты.\n████░░░░░░░░ 0%"
        if callback.message.photo:
            await callback.message.edit_caption(caption=text, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, parse_mode="HTML")
        await callback.answer("Статус обновлён ✅")
    except Exception as e:
        logger.exception("Ошибка в inline_check_payment")
        await callback.answer("Ошибка при проверке.", show_alert=True)

# ---------- 2FA ----------
pending_admin_action = {}
pending_large_payouts = {}  # {order_id: {code, amount, address, currency, timestamp}}

@router.callback_query(F.data.startswith("admin_confirm_"))
async def admin_confirm_2fa(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав.", show_alert=True)
        return
    import random
    code = str(random.randint(1000, 9999))
    order_id = int(callback.data.split("_")[-1])
    pending_admin_action[callback.from_user.id] = {"order_id": order_id, "code": code, "timestamp": time.time()}
    await callback.message.answer(f"🔐 Ваш код подтверждения: <b>{code}</b>\nДействителен 5 минут.", parse_mode="HTML")
    await callback.answer("Код отправлен")

@router.message(Command("confirm"))
async def confirm_payout(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        code = message.text.split()[1]
        action = pending_admin_action.get(message.from_user.id)
        if not action: await message.answer("Нет активных действий."); return
        if time.time() - action["timestamp"] > 300: await message.answer("Код истёк."); del pending_admin_action[message.from_user.id]; return
        if code != action["code"]: await message.answer("Неверный код."); return
        order_id = action["order_id"]
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{RELAY_SITE}/payment/callback", data={"order_id": order_id, "key": RELAY_SECRET}) as resp:
                if resp.status == 200:
                    await message.answer(f"✅ Платёж по заявке #{order_id} подтверждён.")
                else:
                    await message.answer("Ошибка подтверждения.")
        del pending_admin_action[message.from_user.id]
    except: await message.answer("Использование: /confirm КОД")

# ---------- МОИ ЗАЯВКИ ----------
async def my_orders(message: Message):
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT order_id, rub_amount, crypto_address, currency, status, created_at, paid_btc_tx FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (message.from_user.id,))
        orders = c.fetchall()
    if not orders:
        await message.answer("У вас пока нет заявок.")
        return
    text = "🟣 📋 Ваши заявки:\n\n"
    for o in orders:
        oid, rub, addr, curr, status, created, tx = o
        emoji = {"pending": "⏳", "paid": "✅", "sent": "🚀"}.get(status, status)
        text += f"#{oid} {emoji} {rub} RUB → {curr}\nАдрес: {addr}\n"
        if tx: text += f"TX: {tx}\n"
        text += f"Дата: {created[:16]}\n\n"
    if IMG_ORDERS_HISTORY.exists() and len(text) <= 1024:
        await message.answer_photo(FSInputFile(IMG_ORDERS_HISTORY), caption=text)
    elif IMG_ORDERS_HISTORY.exists():
        await message.answer_photo(FSInputFile(IMG_ORDERS_HISTORY), caption="🟣 📋 История ваших операций")
        await message.answer(text)
    else:
        await message.answer(text)

# ---------- ПРОФИЛЬ ----------
async def profile(message: Message):
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (message.from_user.id,))
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status IN ('sent','paid')", (message.from_user.id,))
        completed = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (message.from_user.id,))
        refs = c.fetchone()[0]
    await message.answer(f"🟣 Профиль ObsidianExchange\n\nВсего заявок: {total}\nЗавершённых выплат: {completed}\nПриглашённых рефералов: {refs}\nЛимит заявок: 30")

# ---------- АДМИН-ПАНЕЛЬ ----------
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID: return await message.answer("❌ Доступ запрещён.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📋 Последние заявки", callback_data="admin_last_orders")],
        [InlineKeyboardButton(text="📥 Экспорт CSV", callback_data="admin_export_csv")],
        [InlineKeyboardButton(text="🔄 Ручная выплата", callback_data="admin_payout_menu")],
        [InlineKeyboardButton(text="⛔ Заблокировать", callback_data="admin_block_menu"),
         InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unblock_menu")]
    ])
    await message.answer("🛠 Админ-панель", reply_markup=kb)

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders WHERE status = 'sent'")
        sent = c.fetchone()[0]
        c.execute("SELECT SUM(rub_amount) FROM orders WHERE status = 'sent'")
        volume = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
        pending = c.fetchone()[0]
    text = f"📊 Статистика\nВсего заявок: {total}\nОжидают: {pending}\nУспешно: {sent}\nОборот: {volume:,.0f} RUB"
    await callback.message.edit_text(text)
    await callback.answer()

@router.callback_query(F.data == "admin_last_orders")
async def admin_last_orders(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT order_id, user_id, rub_amount, currency, status, created_at FROM orders ORDER BY created_at DESC LIMIT 10")
        rows = c.fetchall()
    if not rows:
        await callback.message.edit_text("Нет заявок.")
    else:
        text = "📋 Последние 10 заявок:\n\n"
        for r in rows: text += f"#{r[0]} 👤{r[1]} 💰{r[2]} {r[3]} 📅{r[5][:16]} 📌{r[4]}\n"
        await callback.message.edit_text(text)
    await callback.answer()

@router.callback_query(F.data == "admin_export_csv")
async def admin_export_csv(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM (SELECT * FROM orders ORDER BY order_id DESC LIMIT 1000) ORDER BY order_id ASC")
        rows = c.fetchall()
        cols = [desc[0] for desc in c.description]
    buf = StringIO(); writer = csv.writer(buf); writer.writerow(cols); writer.writerows(rows); buf.seek(0)
    await bot.send_document(callback.from_user.id, BufferedInputFile(buf.getvalue().encode(), filename="orders.csv"), caption="Экспорт последних 1000 заявок")
    await callback.answer("Файл отправлен")

@router.callback_query(F.data == "admin_payout_menu")
async def admin_payout_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("Введите команду /force_payout ORDER_ID")
    await callback.answer()

@router.message(Command("force_payout"))
async def force_payout(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        order_id = int(message.text.split()[1])
        fake_tx = f"manual_{int(time.time())}"
        with db_conn(10) as conn:
            conn.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (fake_tx, order_id))
            conn.commit()
        await message.answer(f"Ручная выплата по заявке #{order_id} выполнена, txid: {fake_tx}")
    except: await message.answer("Использование: /force_payout ORDER_ID")

@router.callback_query(F.data == "admin_block_menu")
async def admin_block_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("Введите команду /block USER_ID")
    await callback.answer()

@router.callback_query(F.data == "admin_unblock_menu")
async def admin_unblock_menu(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.edit_text("Введите команду /unblock USER_ID")
    await callback.answer()

@router.message(Command("block"))
async def cmd_block(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        with db_conn(10) as conn:
            conn.execute("INSERT OR IGNORE INTO blocked_users (user_id, reason) VALUES (?, 'admin block')", (user_id,))
            conn.commit()
        await message.answer(f"✅ Пользователь {user_id} заблокирован.")
    except: await message.answer("/block USER_ID")

@router.message(Command("unblock"))
async def cmd_unblock(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        with db_conn(10) as conn:
            conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
            conn.commit()
        await message.answer(f"✅ Пользователь {user_id} разблокирован.")
    except: await message.answer("/unblock USER_ID")

# ---------- ЗАПУСК ----------







@router.message(Exchange.address)
async def process_address(message: Message, state: FSMContext):
    address = message.text.strip()
    data = await state.get_data()
    currency = data['currency']
    if not validate_crypto_address(address, currency):
        await message.answer("❌ Некорректный адрес для выбранной валюты.")
        return
    amount = data.get("amount")
    with db_conn(10) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) VALUES (?,?,?,?,?,'pending')",
                       (message.from_user.id, message.from_user.username, currency, amount, address))
        conn.commit()
        order_id = cursor.lastrowid

    await notify_admin(order_id, message.from_user.id, amount, address, currency)

    await state.update_data(order_id=order_id, amount=amount, currency=currency, address=address)
    await state.set_state(Exchange.payment_method)

    rate = get_rate_with_markup(currency, amount)
    crypto_amount = round(amount / rate, 8) if rate else 0
    text = (f"🟣 ObsidianExchange\n✅ Заявка #{order_id} создана!\n⏳ Курс зафиксирован на 15 минут\n\n"
            f"Сумма: {amount} RUB\n≈ {crypto_amount} {currency} (комиссия {get_commission_percent(amount)}%)\n\n"
            f"Выберите способ оплаты:")
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏦 Оплата СБП", callback_data=f"pm_platega_{order_id}")],
        [InlineKeyboardButton(text="📱 СБП (способ 1)", callback_data=f"pm_montera_sbp_{order_id}")],
        [InlineKeyboardButton(text="📱 СБП (способ 2)", callback_data=f"pm_gp_sbp_{order_id}")],
        [InlineKeyboardButton(text="💳 Оплата по карте (реквизиты)", callback_data=f"pm_gp_card_{order_id}")],
    ])
    if IMG_15MIN.exists():
        await message.answer_photo(FSInputFile(IMG_15MIN), caption=text, reply_markup=inline_kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=inline_kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("pm_"), Exchange.payment_method)
async def process_payment_method(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    amount = data.get("amount")
    currency = data.get("currency")
    pm = callback.data

    import sys
    sys.path.insert(0, '/root/relay')

    if pm.startswith("pm_platega_"):
        rate = get_rate_with_markup(currency, amount)
        crypto_amount = round(amount / rate, 8) if rate else 0
        payment_link = f"{PUBLIC_RELAY}/pay/{order_id}"  # fallback
        try:
            from services.payment_service import PaymentService
            payment_service = PaymentService()
            session = payment_service.create_session(order_id, amount)
            if 'session_token' in session:
                payment_link = f"{PUBLIC_RELAY}/pay/{session['session_token']}"
        except Exception as e:
            logger.error(f"Не удалось создать payment session: {e}")
        caption = f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\nСумма: {amount} RUB\n≈ {crypto_amount} {currency}\n\n<a href='{payment_link}'>Оплатить через СБП</a>"

    elif pm.startswith("pm_montera_sbp_"):
        try:
            from services.payment_service import PaymentService
            from providers.montera import MonteraProvider
            payment_service = PaymentService(provider=MonteraProvider())
            session = payment_service.create_session(order_id, amount, payment_method="sbp")
            if 'error' in session:
                await callback.message.answer("❌ Не удалось получить реквизиты для оплаты. Попробуйте другой способ оплаты или повторите позже.")
                await callback.answer()
                return
            requisites_text = format_requisites(session.get('raw') or {})
        except Exception as e:
            logger.error(f"Ошибка создания сессии Montera SBP: {e}")
            await callback.message.answer("❌ Не удалось получить реквизиты для оплаты. Попробуйте другой способ оплаты или повторите позже.")
            await callback.answer()
            return

        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: {amount} RUB\n\n"
                   f"Переведите указанную сумму на СБП:\n{requisites_text}")

    elif pm.startswith("pm_gp_sbp_"):
        try:
            from services.payment_service import PaymentService
            from providers.greenpay import GreenPayProvider
            payment_service = PaymentService(provider=GreenPayProvider())
            session = payment_service.create_session(order_id, amount, payment_method="sbp")
            if 'error' in session:
                await callback.message.answer("❌ Не удалось получить реквизиты для оплаты. Попробуйте другой способ оплаты или повторите позже.")
                await callback.answer()
                return
            requisites_text = format_requisites(session.get('raw') or {})
        except Exception as e:
            logger.error(f"Ошибка создания сессии GreenPay: {e}")
            await callback.message.answer("❌ Не удалось получить реквизиты для оплаты. Попробуйте другой способ оплаты или повторите позже.")
            await callback.answer()
            return

        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: {amount} RUB\n\n"
                   f"Переведите указанную сумму на СБП:\n{requisites_text}")

    elif pm.startswith("pm_gp_card_"):
        try:
            from services.payment_service import PaymentService
            from providers.montera import MonteraProvider
            payment_service = PaymentService(provider=MonteraProvider())
            session = payment_service.create_session(order_id, amount, payment_method="card")
            if 'error' in session:
                await callback.message.answer("❌ Не удалось получить реквизиты для оплаты. Попробуйте другой способ оплаты или повторите позже.")
                await callback.answer()
                return
            requisites_text = format_requisites(session.get('raw') or {})
        except Exception as e:
            logger.error(f"Ошибка создания сессии Montera: {e}")
            await callback.message.answer("❌ Не удалось получить реквизиты для оплаты. Попробуйте другой способ оплаты или повторите позже.")
            await callback.answer()
            return

        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: {amount} RUB\n\n"
                   f"Переведите указанную сумму на карту:\n{requisites_text}")
    else:
        await callback.answer()
        return

    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{order_id}")],
        [InlineKeyboardButton(text="🔍 Проверить статус", callback_data=f"check_{order_id}")]
    ])
    if IMG_SECURITY.exists() and len(caption) <= 1024:
        await callback.message.answer_photo(FSInputFile(IMG_SECURITY), caption=caption, reply_markup=inline_kb, parse_mode="HTML")
    else:
        await callback.message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")
    await callback.answer()
    await state.clear()


# ---------- АДМИН-КОМАНДЫ УПРАВЛЕНИЯ ----------
@router.message(Command("setrate"))
async def cmd_setrate(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("Формат: /setrate BTC 6500000")
            return
        coin = parts[1].upper()
        new_rate = float(parts[2])
        if coin == 'BTC':
            _btc_cache["rate"] = new_rate
            _btc_cache["ts"] = time.time()
        elif coin == 'LTC':
            _ltc_cache["rate"] = new_rate
            _ltc_cache["ts"] = time.time()
        elif coin == 'USDT':
            _usdt_cache["rate"] = new_rate
            _usdt_cache["ts"] = time.time()
        else:
            await message.answer("Допустимые валюты: BTC, LTC, USDT")
            return
        await message.answer(f"✅ Курс {coin} установлен: {new_rate:,.2f} RUB")
    except Exception as e:
        await message.answer("Ошибка. Формат: /setrate BTC 6500000")

@router.message(Command("limits"))
async def cmd_limits(message: Message):
    if message.from_user.id != ADMIN_ID: return
    await message.answer(
        f"Текущие лимиты:\n"
        f"Мин: {MIN_AMOUNT:,.0f} RUB\n"
        f"Макс: {MAX_AMOUNT:,.0f} RUB\n"
        f"Крупная заявка: {HIGH_AMOUNT:,.0f} RUB\n"
        f"Комиссия: 27% (до 5000 RUB), 23% (5000-15000 RUB), 19% (от 15000 RUB) для BTC/LTC; 2% для USDT"
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    with db_conn(10) as conn:
        c = conn.cursor()
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        month_start = now.strftime("%Y-%m-01")

        # Сегодня
        c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)=? AND status='sent'", (today,))
        cnt_today, vol_today = c.fetchone()
        # Вчера
        c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)=? AND status='sent'", (yesterday,))
        cnt_yest, vol_yest = c.fetchone()
        # Неделя
        c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)>=? AND status='sent'", (week_start,))
        cnt_week, vol_week = c.fetchone()
        # Месяц
        c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)>=? AND status='sent'", (month_start,))
        cnt_month, vol_month = c.fetchone()

    await message.answer(
        f"📊 Статистика\n"
        f"Сегодня: {cnt_today or 0} обменов, {vol_today or 0:,.0f} RUB\n"
        f"Вчера: {cnt_yest or 0} обменов, {vol_yest or 0:,.0f} RUB\n"
        f"Неделя: {cnt_week or 0} обменов, {vol_week or 0:,.0f} RUB\n"
        f"Месяц: {cnt_month or 0} обменов, {vol_month or 0:,.0f} RUB"
    )


# ---------- УЛУЧШЕННЫЙ МОНИТОРИНГ ----------
async def daily_report():
    while True:
        now = datetime.now()
        if now.hour == 9 and now.minute == 0:
            with db_conn(10) as conn:
                c = conn.cursor()
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)=? AND status='sent'", (yesterday,))
                cnt, vol = c.fetchone()
            text = f"📅 Ежедневный отчёт за {yesterday}\n"
            text += f"• Успешных обменов: {cnt or 0}\n"
            text += f"• Оборот: {vol or 0:,.0f} RUB\n"
            try:
                wallet = Wallet('PayoutWallet')
                wallet.scan()
                balance_btc = wallet.balance(network='bitcoin') / 1e8
                text += f"• Баланс кошелька: {balance_btc:.8f} BTC"
            except:
                pass
            await bot.send_message(ADMIN_ID, text)
            await asyncio.sleep(24 * 3600)
        else:
            await asyncio.sleep(30)

async def platega_healthcheck():
    while True:
        try:
            r = requests.post("http://5.206.224.157:5003/platega/invoice",
                             json={"order_id": 0, "amount": 100}, timeout=5)
            if r.status_code != 200:
                await bot.send_message(ADMIN_ID, f"⚠️ Platega прокси не отвечает (status {r.status_code}).")
        except Exception:
            await bot.send_message(ADMIN_ID, "❌ Platega прокси недоступен!")
        await asyncio.sleep(3600)

async def check_stuck_orders():
    while True:
        with db_conn(10) as conn:
            c = conn.cursor()
            threshold = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT order_id FROM orders WHERE status='pending' AND created_at < ?", (threshold,))
            stuck = c.fetchall()
            if stuck:
                ids = ", ".join([str(row[0]) for row in stuck])
                await bot.send_message(ADMIN_ID, f"🕒 Зависшие заявки (>30 мин): {ids}")
        await asyncio.sleep(900)


# ---------- МОНИТОРИНГ САЙТА ----------
async def website_healthcheck():
    last_state = True  # True = сайт был доступен
    while True:
        try:
            r = requests.get("https://obsidian-exchange.org/webapp", timeout=10)
            current_state = (r.status_code == 200)
        except Exception:
            current_state = False

        if current_state != last_state:
            if current_state:
                await bot.send_message(ADMIN_ID, "✅ Сайт снова доступен.")
            else:
                await bot.send_message(ADMIN_ID, f"❌ Сайт недоступен!")
            last_state = current_state
        await asyncio.sleep(300)

@router.message(Command("setrefaddr"))
async def cmd_set_ref_addr(message: Message):
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("Формат: /setrefaddr BTC_ADDRESS")
            return
        address = parts[1]
        if not validate_crypto_address(address, 'BTC'):
            await message.answer("Некорректный BTC-адрес.")
            return
        with db_conn(10) as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO referral_addresses (user_id, currency, address) VALUES (?, 'BTC', ?)",
                      (message.from_user.id, address))
            conn.commit()
        await message.answer("✅ Ваш BTC-адрес для реферальных бонусов сохранён.")
    except Exception as e:
        await message.answer("Ошибка. Формат: /setrefaddr ВАШ_BTC_АДРЕС")

# ---------- МОНИТОРИНГ ДИСКА ----------
async def disk_healthcheck():
    while True:
        stat = os.statvfs('/')
        free_gb = (stat.f_bavail * stat.f_frsize) / 1024**3
        if free_gb < 5:
            await bot.send_message(ADMIN_ID, f"⚠️ Осталось {free_gb:.1f} ГБ свободного места на диске!")
        await asyncio.sleep(3600)


# ---------- ДИНАМИЧЕСКАЯ КОМИССИЯ ----------
_fee_cache = {"btc": None, "ltc": None, "ts": 0}

async def update_fees():
    global _fee_cache
    while True:
        try:
            r = requests.get("https://mempool.space/api/v1/fees/recommended", timeout=10)
            data = r.json()
            _fee_cache["btc"] = data.get("fastestFee", 20)  # sat/vB
            _fee_cache["ltc"] = None  # для LTC можно использовать фиксированную
            _fee_cache["ts"] = time.time()
        except Exception as e:
            logger.error(f"Не удалось обновить комиссии: {e}")
        await asyncio.sleep(600)  # каждые 10 минут


# ---------- АВТОМАТИЧЕСКАЯ ПРОВЕРКА ПЛАТЕЖЕЙ ----------
async def auto_check_payments():
    while True:
        with db_conn(10) as conn:
            c = conn.cursor()
            c.execute("SELECT order_id, user_id, rub_amount, crypto_address, currency FROM orders WHERE status='paid'")
            paid_orders = c.fetchall()
            for order_id, user_id, rub_amount, address, currency in paid_orders:
                # Запускаем выплату (как в confirm_payout)
                try:
                    payout_id = await process_payout_async(order_id, rub_amount, address, currency)
                    if payout_id:
                        c.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                                  (payout_id, order_id))
                        conn.commit()
                        # Уведомление клиента о статусе 'sent' отправляет exchange-notifier (status_notifier.py)
                        await bot.send_message(ADMIN_ID, f"✅ Авто-выплата #{order_id}: {rub_amount} RUB → {currency}\nTXID: <code>{payout_id}</code>", parse_mode="HTML")
                        await credit_referral_bonus(order_id, user_id, rub_amount)
                        update_user_vip_volume(user_id, rub_amount)
                except Exception as e:
                    logger.error(f"Ошибка авто-выплаты #{order_id}: {e}")
                    try:
                        await bot.send_message(user_id, "⚠️ Возникла временная задержка при отправке средств. Наша команда уже работает над решением. Пожалуйста, ожидайте.")
                    except Exception:
                        pass
        await asyncio.sleep(30)  # проверка каждые 30 секунд


# ---------- АВТОПРОВЕРКА USDT (TRC-20) ----------
async def auto_check_usdt():
    if not os.getenv('USDT_PRIVATE_KEY'):
        logger.warning("USDT_PRIVATE_KEY не задан — авто-проверка входящих USDT отключена")
        return
    while True:
        # Запрашиваем последние транзакции USDT на нашем адресе
        try:
            client = Tron()
            priv_key = PrivateKey(bytes.fromhex(os.getenv('USDT_PRIVATE_KEY')))
            addr = priv_key.public_key.to_base58check_address()
            txs = client.get_usdt_transactions(addr, limit=10)
            for tx in txs:
                # Проверяем, есть ли заказ с такой суммой и адресом отправителя, ожидающий оплаты
                amount_usdt = tx['value'] / 1e6
                from_addr = tx['from']
                with db_conn(10) as conn:
                    c = conn.cursor()
                    c.execute("SELECT order_id, user_id, rub_amount, crypto_address, currency FROM orders WHERE status='pending' AND currency='USDT' AND crypto_address=? AND rub_amount BETWEEN ? AND ?",
                              (from_addr, amount_usdt * 0.9, amount_usdt * 1.1))
                    order = c.fetchone()
                    if order:
                        order_id, user_id, rub_amount, address, currency = order
                        c.execute("UPDATE orders SET status='paid' WHERE order_id=?", (order_id,))
                        conn.commit()
                        # Запускаем выплату
                        payout_id = await process_payout_async(order_id, rub_amount, address, currency)
                        if payout_id:
                            c.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                                      (payout_id, order_id))
                            conn.commit()
                            try:
                                await bot.send_message(user_id, f"✅ Выплата USDT #{order_id} выполнена!\nTXID: <code>{payout_id}</code>", parse_mode="HTML")
                            except:
                                pass
        except Exception as e:
            logger.error(f"Ошибка проверки USDT: {e}")
        await asyncio.sleep(60)


# ---------- АВТОПРОВЕРКА СВОПОВ ----------
async def swap_status_monitor():
    import sys
    sys.path.insert(0, '/root/relay')
    from providers.trocador import TrocadorProvider
    from providers.swapuz import SwapUzProvider
    trocador = TrocadorProvider()
    swapuz = SwapUzProvider()
    final_statuses = ('finished', 'failed', 'expired', 'paid partially', 'refunded')
    while True:
        try:
            with db_conn(10) as conn:
                c = conn.cursor()
                c.execute(
                    "SELECT session_token, user_id, trocador_id, coin_from, coin_to, status, provider, amount_from "
                    "FROM swap_sessions WHERE status NOT IN (?,?,?,?,?)",
                    final_statuses
                )
                rows = c.fetchall()
                for token, user_id, ext_id, coin_from, coin_to, old_status, provider_name, amount_from in rows:
                    if not ext_id:
                        continue
                    provider_name = provider_name or 'trocador'
                    new_status = None

                    if provider_name == 'swapuz':
                        info = swapuz.get_status(ext_id)
                        new_status = info.get('status')
                        amount_received = info.get('raw', {}).get('amountResult')
                    else:
                        info = trocador.get_status(ext_id)
                        new_status = info.get('Status')
                        amount_received = info.get('AmountReceived') or info.get('AmountTo')

                    if not new_status or new_status == old_status:
                        continue
                    c.execute("UPDATE swap_sessions SET status=?, updated_at=datetime('now') WHERE session_token=?", (new_status, token))
                    conn.commit()
                    if new_status == 'finished':
                        try:
                            await bot.send_message(
                                user_id,
                                f"✅ Своп {coin_from} → {coin_to} завершён!\n"
                                f"Получено: {amount_received} {coin_to}",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
                        # реферальный бонус за своп: 1% от суммы swap в BTC-эквиваленте
                        try:
                            from_rate = get_cached_rate(coin_from.upper().replace('USDT', 'USDT'))
                            btc_rate = get_cached_rate('BTC')
                            if amount_from and from_rate and btc_rate:
                                swap_rub = amount_from * from_rate
                                await credit_referral_bonus(f"swap_{token}", user_id, swap_rub)
                        except Exception as e:
                            logger.debug(f"Referral swap bonus error: {e}")
                    elif new_status in ('failed', 'expired', 'halted', 'refunded'):
                        try:
                            await bot.send_message(
                                user_id,
                                f"⚠️ Своп {coin_from} → {coin_to}: статус «{new_status}».\n"
                                f"Подробности — на странице свопа."
                            )
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Ошибка проверки статусов свопов: {e}")
        await asyncio.sleep(30)


@router.message(Command("history"))
async def cmd_history(message: Message):
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT order_id, rub_amount, currency, status, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (message.from_user.id,))
        rows = c.fetchall()
    if not rows:
        await message.answer("У вас пока нет заявок.")
        return
    text = "🟣 📋 Ваши последние заявки:\n\n"
    for row in rows:
        emoji = {"pending": "⏳", "paid": "✅", "sent": "🚀"}.get(row[3], row[3])
        text += f"#{row[0]} {emoji} {row[1]} RUB → {row[2]} ({row[4][:16]})\n"
    await message.answer(text)


# ---------- ПРОВЕРКА БЭКАПОВ ----------
async def verify_backups():
    while True:
        await asyncio.sleep(3600)  # проверка раз в час
        try:
            import glob, os
            files = glob.glob('/root/backups/*.tar.gz')
            if not files:
                await bot.send_message(ADMIN_ID, "❌ Бэкапы отсутствуют!")
                continue
            latest = max(files, key=os.path.getmtime)
            age_hours = (time.time() - os.path.getmtime(latest)) / 3600
            if age_hours > 2:
                await bot.send_message(ADMIN_ID, f"⚠️ Последний бэкап старше 2 часов ({age_hours:.1f} ч).")
            elif os.path.getsize(latest) < 1000:
                await bot.send_message(ADMIN_ID, "❌ Последний бэкап слишком маленький (возможно, повреждён).")
        except Exception as e:
            logger.error(f"Ошибка проверки бэкапов: {e}")


# ---------- МОНИТОРИНГ SSL ----------
async def ssl_healthcheck():
    import subprocess, datetime
    while True:
        try:
            result = subprocess.run(['openssl', 's_client', '-connect', 'obsidian-exchange.org:443', '-servername', 'obsidian-exchange.org'], capture_output=True, input=b'', timeout=10)
            output = result.stderr.decode()
            # Ищем дату истечения
            import re
            match = re.search(r'notAfter=([A-Za-z]{3} \d{1,2} \d{2}:\d{2}:\d{2} \d{4} GMT)', output)
            if match:
                expire_str = match.group(1)
                expire_date = datetime.datetime.strptime(expire_str, '%b %d %H:%M:%S %Y %Z')
                now = datetime.datetime.utcnow()
                days_left = (expire_date - now).days
                if days_left < 7:
                    await bot.send_message(ADMIN_ID, f"⚠️ SSL-сертификат истекает через {days_left} дней!")
        except Exception as e:
            logger.error(f"Ошибка проверки SSL: {e}")
        await asyncio.sleep(86400)  # раз в сутки


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    text = message.text.partition(' ')[2]
    if not text:
        await message.answer("Использование: /broadcast Текст для рассылки")
        return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT user_id FROM orders")
        users = c.fetchall()
    sent = 0
    for user in users:
        try:
            await bot.send_message(user[0], text)
            sent += 1
            await asyncio.sleep(0.05)  # чтобы не упереться в лимиты Telegram
        except Exception:
            pass
    await message.answer(f"Рассылка завершена. Сообщение отправлено {sent} пользователям.")


@router.message(Command("approve"))
async def cmd_approve(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("Использование: /approve ORDER_ID CODE")
            return
        order_id = int(parts[1])
        code = parts[2]
        action = pending_large_payouts.get(order_id)
        if not action:
            await message.answer("Нет ожидающей выплаты с таким ID.")
            return
        if time.time() - action['timestamp'] > 300:
            await message.answer("Код истёк.")
            del pending_large_payouts[order_id]
            return
        if code != action['code']:
            await message.answer("Неверный код.")
            return
        # Выполняем выплату
        payout_id = await process_payout_async(order_id, action['amount'], action['address'], action['currency'])
        if payout_id:
            # Обновляем статус в БД
            with db_conn(10) as conn:
                c = conn.cursor()
                c.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (payout_id, order_id))
                conn.commit()
                c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
                user_id = c.fetchone()
            if user_id:
                try:
                    await bot.send_message(user_id[0], f"✅ Выплата #{order_id} выполнена после подтверждения!\nTXID: <code>{payout_id}</code>", parse_mode="HTML")
                except: pass
            await message.answer(f"✅ Крупная выплата #{order_id} одобрена. TXID: <code>{payout_id}</code>", parse_mode="HTML")
        else:
            await message.answer(f"❌ Ошибка выполнения выплаты #{order_id}")
        del pending_large_payouts[order_id]
    except Exception as e:
        await message.answer("Ошибка. Проверьте формат.")

@router.message(F.content_type == ContentType.WEB_APP_DATA)
async def handle_webapp(message: Message, state: FSMContext):
    import json
    try:
        data = json.loads(message.web_app_data.data)
        # Обработка сохранения реферального адреса
        if data.get('action') == 'save_ref_address':
            address = data.get('address', '').strip()
            if not validate_crypto_address(address, 'BTC'):
                await message.answer("❌ Некорректный BTC-адрес.")
                return
            with db_conn(10) as conn:
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO referral_addresses (user_id, currency, address) VALUES (?, 'BTC', ?)",
                          (message.from_user.id, address))
                conn.commit()
            await message.answer("✅ Ваш BTC-адрес для реферальных бонусов сохранён!")
            return

        # Вывод реферального бонуса
        if data.get('action') == 'withdraw_ref_bonus':
            text = await withdraw_referral_bonus(message.from_user.id)
            await message.answer(text, parse_mode="HTML")
            return

        # Создание заявки
        currency = data.get('currency', 'BTC')
        amount = float(data.get('amount', 0))
        address = data.get('address', '').strip()
    except:
        await message.answer("❌ Некорректные данные из Mini App.")
        return

    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        await message.answer(f"❌ Сумма должна быть от {MIN_AMOUNT} до {MAX_AMOUNT} RUB.")
        return

    if not validate_crypto_address(address, currency):
        await message.answer(f"❌ Некорректный адрес для {currency}.")
        return

    with db_conn(10) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) VALUES (?,?,?,?,?,'pending')",
                       (message.from_user.id, message.from_user.username, currency, amount, address))
        conn.commit()
        order_id = cursor.lastrowid

    await notify_admin(order_id, message.from_user.id, amount, address, currency)


    import sys
    sys.path.insert(0, '/root/relay')
    payment_link = f"{PUBLIC_RELAY}/pay/{order_id}"  # fallback
    try:
        from services.payment_service import PaymentService
        payment_service = PaymentService()
        session = payment_service.create_session(order_id, amount)
        if 'session_token' in session:
            payment_link = f"{PUBLIC_RELAY}/pay/{session['session_token']}"
    except Exception as e:
        logger.error(f"Не удалось создать payment session (webapp): {e}")
    caption = (
        f"🟣 ObsidianExchange\n"
        f"✅ Заявка #{order_id} создана!\n"
        f"⏳ Курс зафиксирован на 15 минут\n\n"
        f"Сумма: {amount} RUB\n"
        f"Валюта: {currency}\n\n"
        f"<a href='{payment_link}'>Оплатить</a>"
    )
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{order_id}")],
        [InlineKeyboardButton(text="🔍 Проверить статус", callback_data=f"check_{order_id}")]
    ])
    await message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")


@router.message(Command("history"))
async def cmd_history(message: Message, page: int = 1):
    try:
        if len(message.text.split()) > 1:
            page = int(message.text.split()[1])
    except:
        page = 1
    limit = 10
    offset = (page - 1) * limit
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT order_id, rub_amount, currency, status, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                  (message.from_user.id, limit, offset))
        rows = c.fetchall()
    if not rows:
        await message.answer("Нет заявок на этой странице.")
        return
    text = f"🟣 📋 История (стр. {page}):\n\n"
    for r in rows:
        emoji = {"pending":"⏳","paid":"✅","sent":"🚀"}.get(r[3], r[3])
        text += f"#{r[0]} {emoji} {r[1]} RUB → {r[2]} ({r[4][:16]})\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if page > 1:
        kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Пред.", callback_data=f"hist_{page-1}")])
    if len(rows) == limit:
        kb.inline_keyboard.append([InlineKeyboardButton(text="След. ➡️", callback_data=f"hist_{page+1}")])
    await message.answer(text, reply_markup=kb)

@router.callback_query(F.data.startswith("hist_"))
async def pagination(callback: CallbackQuery):
    page = int(callback.data.split("_")[1])
    await callback.message.delete()
    await cmd_history(callback.message, page=page)
    await callback.answer()


@router.message(Command("order"))
async def cmd_order(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        order_id = int(message.text.split()[1])
    except:
        await message.answer("Использование: /order ID")
        return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
        row = c.fetchone()
    if not row:
        await message.answer("Заказ не найден.")
        return
    (oid, uid, username, currency, rub_amount, crypto_address, status, created, tx, updated) = row
    text = (
        f"🆔 Заказ #{oid}\n"
        f"👤 Пользователь: {uid} (@{username})\n"
        f"💰 Сумма: {rub_amount} RUB\n"
        f"🪙 Валюта: {currency}\n"
        f"📥 Адрес: {crypto_address}\n"
        f"📌 Статус: {status}\n"
        f"🔗 TX/ID выплаты: {tx or 'нет'}\n"
        f"📅 Создан: {created}\n"
        f"🕒 Обновлён: {updated}"
    )
    await message.answer(text)


PAYOUT_WALLETS = {'BTC': 'PayoutWallet', 'LTC': 'PayoutLTC'}

def send_crypto(currency, address, amount):
    """Отправляет amount монет currency на address из горячего кошелька. Возвращает txid."""
    wallet = Wallet(PAYOUT_WALLETS[currency.upper()])
    t = wallet.send_to(address, amount, unit=currency.lower(), fee='auto')
    return t.txid

def process_payout(order_id, rub_amount, client_address, currency='BTC'):
    currency = currency.upper()
    if currency not in PAYOUT_WALLETS:
        logger.warning(f"Автовыплата пока не поддерживает {currency}. Заказ #{order_id}")
        return None
    rate = get_rate_with_markup(currency, rub_amount)
    amount = round(rub_amount / rate, 8)
    if amount <= 0:
        logger.error(f"Нулевая сумма выплаты для заказа #{order_id}")
        return None
    try:
        txid = send_crypto(currency, client_address, amount)
        logger.info(f"Выплата #{order_id} выполнена: {amount} {currency} -> {client_address}, txid={txid}")
        return txid
    except Exception as e:
        logger.exception(f"Ошибка выплаты #{order_id}: {e}")
        return None

async def process_payout_async(order_id, rub_amount, client_address, currency='BTC'):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, process_payout, order_id, rub_amount, client_address, currency)


async def credit_referral_bonus(order_id, user_id, rub_amount):
    """Начисляет рефереру REFERRAL_BONUS_PERCENT% от комиссии обменника (в BTC) за выполненную заявку приглашённого."""
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT referrer_id FROM referrals WHERE referred_id=?", (user_id,))
        row = c.fetchone()
        if not row:
            conn.close()
            return
        referrer_id = row[0]
        btc_rate = get_cached_rate('BTC')
        if not btc_rate:
            conn.close()
            return
        commission_rub = rub_amount * get_commission_percent(rub_amount) / 100
        bonus_btc = round(commission_rub * REFERRAL_BONUS_PERCENT / 100 / btc_rate, 8)
        if bonus_btc <= 0:
            conn.close()
            return
        c.execute("UPDATE referrals SET total_bonus_btc = total_bonus_btc + ?, bonus_paid=0 WHERE referrer_id=? AND referred_id=?",
                  (bonus_btc, referrer_id, user_id))
        conn.commit()
    try:
        await bot.send_message(referrer_id,
            f"🎉 Ваш реферал совершил обмен!\nНачислен бонус: {bonus_btc} BTC\n"
            f"Вывести можно в разделе «👥 Рефералка».")
    except Exception:
        pass


async def withdraw_referral_bonus(user_id):
    """Выводит накопленный реферальный бонус на сохранённый BTC-адрес пользователя. Возвращает текст ответа."""
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT COALESCE(SUM(total_bonus_btc), 0) FROM referrals WHERE referrer_id=?", (user_id,))
        total = c.fetchone()[0] or 0
        if total < REFERRAL_DUST_BTC:
            conn.close()
            return f"💸 Накоплено: {total:.8f} BTC.\nМинимальная сумма для вывода: {REFERRAL_DUST_BTC} BTC."
        c.execute("SELECT address FROM referral_addresses WHERE user_id=? AND currency='BTC'", (user_id,))
        addr_row = c.fetchone()
        if not addr_row:
            conn.close()
            return "❌ Сначала укажите BTC-адрес для вывода бонусов:\n/setrefaddr ВАШ_BTC_АДРЕС"
        address = addr_row[0]
        try:
            loop = asyncio.get_running_loop()
            txid = await loop.run_in_executor(None, send_crypto, 'BTC', address, total)
        except Exception as e:
            logger.exception(f"Ошибка вывода реф. бонуса для {user_id}: {e}")
            return "⚠️ Не удалось выполнить вывод. Попробуйте позже или обратитесь в поддержку."
        c.execute("UPDATE referrals SET total_bonus_btc=0, bonus_paid=1 WHERE referrer_id=?", (user_id,))
        conn.commit()
    try:
        await bot.send_message(ADMIN_ID,
            f"💸 Выплата реф. бонуса пользователю {user_id}: {total:.8f} BTC\nTXID: <code>{txid}</code>",
            parse_mode="HTML")
    except Exception:
        pass
    return f"✅ Бонус выведен!\nСумма: {total:.8f} BTC\nTXID: <code>{txid}</code>"


async def check_balance():
    """Проверяет балансы BTC, LTC, USDT и уведомляет админа при низком уровне."""
    # BTC
    try:
        wallet = Wallet('PayoutWallet')
        wallet.scan()
        balance = wallet.balance(network='bitcoin')
        if balance < 5000:
            await bot.send_message(ADMIN_ID, f"⚠️ Низкий баланс BTC: {balance} сатоши!\nПополните: {wallet.get_key().address}")
    except Exception as e:
        logger.error(f"Ошибка проверки баланса BTC: {e}")

    # LTC
    try:
        ltc_wallet = Wallet('PayoutLTC')
        ltc_wallet.scan()
        ltc_balance = ltc_wallet.balance(network='litecoin')
        if ltc_balance < 500000:  # 0.005 LTC в сатоши
            await bot.send_message(ADMIN_ID, f"⚠️ Низкий баланс LTC: {ltc_balance} сатоши!\nПополните: {ltc_wallet.get_key().address}")
    except Exception as e:
        logger.error(f"Ошибка проверки баланса LTC: {e}")

    # USDT (TRC-20)
    if os.getenv('USDT_PRIVATE_KEY'):
        try:
            client = Tron()
            priv_key = PrivateKey(bytes.fromhex(os.getenv('USDT_PRIVATE_KEY')))
            addr = priv_key.public_key.to_base58check_address()
            contract = client.get_contract('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t')
            balance = contract.functions.balanceOf(addr)
            usdt_balance = balance / 1e6
            if usdt_balance < 10:
                await bot.send_message(ADMIN_ID, f"⚠️ Низкий баланс USDT: {usdt_balance:.2f} USDT\nПополните: {addr}")
        except Exception as e:
            logger.error(f"Ошибка проверки баланса USDT: {e}")

async def balance_monitor():
    while True:
        await check_balance()
        await asyncio.sleep(6 * 3600)  # раз в 6 часов


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    """Показывает текущие балансы и адреса горячих кошельков (BTC/LTC/USDT)."""
    if message.from_user.id != ADMIN_ID:
        return
    text = "💰 <b>Балансы горячих кошельков</b>\n\n"

    try:
        wallet = Wallet('PayoutWallet')
        wallet.scan()
        btc_balance = wallet.balance(network='bitcoin')
        text += f"₿ BTC: <code>{btc_balance / 1e8:.8f}</code> BTC ({btc_balance} сатоши)\nАдрес: <code>{wallet.get_key().address}</code>\n\n"
    except Exception as e:
        text += f"₿ BTC: ошибка получения баланса ({e})\n\n"

    try:
        ltc_wallet = Wallet('PayoutLTC')
        ltc_wallet.scan()
        ltc_balance = ltc_wallet.balance(network='litecoin')
        text += f"Ł LTC: <code>{ltc_balance / 1e8:.8f}</code> LTC ({ltc_balance} сатоши)\nАдрес: <code>{ltc_wallet.get_key().address}</code>\n\n"
    except Exception as e:
        text += f"Ł LTC: ошибка получения баланса ({e})\n\n"

    if os.getenv('USDT_PRIVATE_KEY'):
        try:
            client = Tron()
            priv_key = PrivateKey(bytes.fromhex(os.getenv('USDT_PRIVATE_KEY')))
            addr = priv_key.public_key.to_base58check_address()
            contract = client.get_contract('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t')
            usdt_balance = contract.functions.balanceOf(addr) / 1e6
            text += f"💵 USDT: <code>{usdt_balance:.2f}</code> USDT\nАдрес: <code>{addr}</code>\n"
        except Exception as e:
            text += f"💵 USDT: ошибка получения баланса ({e})\n"
    else:
        text += "💵 USDT: кошелёк не настроен (нет USDT_PRIVATE_KEY)\n"

    await message.answer(text, parse_mode="HTML")


@router.message(Command("fullstats"))
async def cmd_fullstats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    with db_conn(10) as conn:
        c = conn.cursor()
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        month_start = now.strftime("%Y-%m-01")

        text = "📊 <b>Расширенная статистика</b>\n\n"
        for name, start_date in {"Сегодня": today, "Вчера": yesterday, "Неделя": week_start, "Месяц": month_start}.items():
            c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)>=? AND status='sent'", (start_date,))
            cnt, vol = c.fetchone()
            text += f"<b>{name}</b>: {cnt or 0} обменов, {vol or 0:,.0f} RUB\n"

        text += "\n<b>По валютам (за месяц):</b>\n"
        for cur in ['BTC', 'LTC', 'USDT']:
            c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)>=? AND currency=? AND status='sent'", (month_start, cur))
            cnt, vol = c.fetchone()
            text += f"• {cur}: {cnt or 0} обменов, {vol or 0:,.0f} RUB\n"

        text += "\n<b>По статусам (за месяц):</b>\n"
        for status in ['pending', 'paid', 'sent']:
            c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)>=? AND status=?", (month_start, status))
            cnt = c.fetchone()[0]
            text += f"• {status}: {cnt or 0}\n"

    await message.answer(text, parse_mode="HTML")


# ---------- УМНЫЙ МОНИТОРИНГ И АЛЕРТЫ ----------
_smart_alert_state = {"btc": 0, "ltc": 0, "usdt": 0, "proxy": True, "relay": True}

async def smart_monitor():
    global _smart_alert_state
    while True:
        try:
            # Проверка балансов (пороги можно настроить)
            wallet = Wallet('PayoutWallet')
            wallet.scan()
            btc_balance = wallet.balance(network='bitcoin')
            if btc_balance < 10000 and _smart_alert_state["btc"] != 1:
                await bot.send_message(ADMIN_ID, f"🔴 КРИТИЧЕСКИ НИЗКИЙ БАЛАНС BTC: {btc_balance} сатоши!")
                _smart_alert_state["btc"] = 1
            elif btc_balance >= 10000 and _smart_alert_state["btc"] == 1:
                _smart_alert_state["btc"] = 0

            # Проверка доступности Platega API
            try:
                r = requests.get("https://app.platega.io/", timeout=5)
                if r.status_code >= 500 and _smart_alert_state["proxy"]:
                    await bot.send_message(ADMIN_ID, f"⚠️ Platega API недоступен (status {r.status_code})!")
                    _smart_alert_state["proxy"] = False
                elif r.status_code < 500 and not _smart_alert_state["proxy"]:
                    _smart_alert_state["proxy"] = True
            except:
                if _smart_alert_state["proxy"]:
                    await bot.send_message(ADMIN_ID, "❌ Ошибка подключения к Platega API!")
                    _smart_alert_state["proxy"] = False

            # Проверка доступности Relay
            try:
                r = requests.get("http://127.0.0.1:5000/", timeout=5)
                if r.status_code != 200 and _smart_alert_state["relay"]:
                    await bot.send_message(ADMIN_ID, "⚠️ Relay недоступен!")
                    _smart_alert_state["relay"] = False
                elif r.status_code == 200 and not _smart_alert_state["relay"]:
                    _smart_alert_state["relay"] = True
            except:
                if _smart_alert_state["relay"]:
                    await bot.send_message(ADMIN_ID, "❌ Ошибка подключения к Relay!")
                    _smart_alert_state["relay"] = False

        except Exception as e:
            logger.error(f"Ошибка в smart_monitor: {e}")

        await asyncio.sleep(120)  # Проверка каждые 2 минуты

async def main():
    asyncio.create_task(balance_monitor())
    asyncio.create_task(smart_monitor())
    asyncio.create_task(verify_backups())
    asyncio.create_task(ssl_healthcheck())
    asyncio.create_task(update_fees())
    # Авто-выплата готова (BTC/LTC), но отключена: PayoutWallet/PayoutLTC пусты.
    # Перед включением — пополнить горячие кошельки и проверить баланс через /balance,
    # затем раскомментировать строку ниже и перезапустить сервис.
    # asyncio.create_task(auto_check_payments())
    asyncio.create_task(auto_check_usdt())
    asyncio.create_task(swap_status_monitor())
    # # asyncio.create_task(daily_report())
    # # asyncio.create_task(platega_healthcheck())
    # # asyncio.create_task(check_stuck_orders())
    # # asyncio.create_task(website_healthcheck())
    # # asyncio.create_task(disk_healthcheck())
    await check_balance()  # сразу при старте
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    finally:
        remove_pid()
