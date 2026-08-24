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
RELAY_SECRET = os.getenv('RELAY_SECRET', '')
COMMISSION_PERCENT = float(os.getenv('COMMISSION_PERCENT', 12))

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
    captcha = State()
    address = State()

# ---------- БАЗА ДАННЫХ ----------
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
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
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")
    conn.commit()
    conn.close()
init_db()

# ---------- КЭШ КУРСА ----------
_btc_cache = {"rate": 0, "ts": 0}
_ltc_cache = {"rate": 0, "ts": 0}
_usdt_cache = {"rate": 0, "ts": 0}


# ---------- ПРОГРЕССИВНАЯ КОМИССИЯ ----------
def get_commission_percent(amount_rub):
    if amount_rub < 2000:
        return 27
    elif amount_rub <= 10000:
        return 23
    else:
        return 21
def get_cached_rate(coin):
    cache = _btc_cache if coin == 'BTC' else (_ltc_cache if coin == 'LTC' else _usdt_cache)
    now = time.time()
    if cache["rate"] and (now - cache["ts"]) < 600:  # кэш 10 минут
        return cache["rate"]
    try:
        # Основной источник – CoinGecko
        if coin == 'BTC':
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=rub", timeout=8)
            rate = r.json()["bitcoin"]["rub"]
        elif coin == 'LTC':
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=litecoin&vs_currencies=rub", timeout=8)
            rate = r.json()["litecoin"]["rub"]
        else:
            r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=rub", timeout=8)
            rate = r.json()["tether"]["rub"]
    except:
        # Резервный источник – Binance
        try:
            if coin == 'BTC':
                r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB")
                rate = float(r1.json()["price"]) * float(r2.json()["price"])
            elif coin == 'LTC':
                r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=LTCUSDT")
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB")
                rate = float(r1.json()["price"]) * float(r2.json()["price"])
            else:
                r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB")
                rate = float(r.json()["price"])
        except:
            if coin == 'BTC': return cache.get("rate", 6500000)
            elif coin == 'LTC': return cache.get("rate", 4000)
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
    return get_cached_rate(coin) * (1 - commission / 100)

# ---------- ВАЛИДАЦИЯ АДРЕСОВ ----------
def validate_crypto_address(addr, currency):
    if currency == 'BTC':
        return any(re.match(p, addr) for p in [r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', r'^bc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == 'LTC':
        return any(re.match(p, addr) for p in [r'^[LM][1-9A-HJ-NP-Za-km-z]{26,33}$', r'^ltc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == 'USDT':
        return re.match(r'^T[A-Za-z1-9]{33}$', addr) is not None
    return False

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
    btc_rate = get_cached_rate('BTC')
    ltc_rate = get_cached_rate('LTC')
    usdt_rate = get_cached_rate('USDT')
    btc_markup = round(btc_rate * (1 - COMMISSION_PERCENT/100), 2)
    ltc_markup = round(ltc_rate * (1 - COMMISSION_PERCENT/100), 2)
    usdt_markup = round(usdt_rate * (1 - COMMISSION_PERCENT/100), 2)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='sent'", (datetime.now().strftime("%Y-%m-%d"),))
    sent_today = c.fetchone()[0]
    conn.close()
    welcome_text = (
        f"⚫️ ObsidianExchange\n"
        f"├ 💎 RUB → BTC | LTC | USDT\n"
        f"├ BTC: {btc_markup:,} RUB\n"
        f"├ LTC: {ltc_markup:,} RUB\n"
        f"├ USDT: {usdt_markup:,} RUB\n"
        f"├ 🔒 Non‑KYC\n"
        f"├ ⚡ Автовыплаты\n"
        f"└ 🛡️ Гарант: сделка без риска\n\n"
        f"📊 Сегодня выполнено: {sent_today} обменов\n\n"
        f"📜 Правила:\n"
        f"• Мин. сумма: {MIN_AMOUNT:,.0f} RUB\n"
        f"• Комиссия: 27% (500-2000 RUB), 23% (2000-10000 RUB), 21% (более 10000 RUB)\n"
        f"• Курс фиксируется на 15 минут\n"
        f"• Non‑KYC, без верификации\n\n"
        f"👇 Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Обменять", callback_data="menu_exchange")],
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
    btc_markup = round(btc_rate * (1 - COMMISSION_PERCENT/100), 2)
    ltc_markup = round(ltc_rate * (1 - COMMISSION_PERCENT/100), 2)
    usdt_markup = round(usdt_rate * (1 - COMMISSION_PERCENT/100), 2)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='sent'", (datetime.now().strftime("%Y-%m-%d"),))
    sent_today = c.fetchone()[0]
    conn.close()
    welcome_text = (
        f"⚫️ ObsidianExchange\n"
        f"├ 💎 RUB → BTC | LTC | USDT\n"
        f"├ BTC: {btc_markup:,} RUB\n"
        f"├ LTC: {ltc_markup:,} RUB\n"
        f"├ USDT: {usdt_markup:,} RUB\n"
        f"├ 🔒 Non‑KYC\n"
        f"├ ⚡ Автовыплаты\n"
        f"└ 🛡️ Гарант: сделка без риска\n\n"
        f"📊 Сегодня выполнено: {sent_today} обменов\n\n"
        f"👇 Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Обменять", callback_data="menu_exchange")],
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
    await callback.message.answer("💎 Выберите валюту для обмена:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "menu_orders")
async def menu_orders(callback: CallbackQuery):
    await my_orders(callback.message)
    await callback.answer()

@router.callback_query(F.data == "menu_ref")
async def menu_ref(callback: CallbackQuery):
    username = (await bot.get_me()).username
    ref_link = f"https://t.me/{username}?start=ref_{callback.from_user.id}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться", switch_inline_query=ref_link)]
    ])
    await callback.message.answer(f"👥 Ваша реферальная ссылка:\n\n<code>{ref_link}</code>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery):
    await profile(callback.message)
    await callback.answer()

@router.callback_query(F.data == "menu_support")
async def menu_support(callback: CallbackQuery):
    await callback.message.answer("📞 @ObsidianSupBot")
    await callback.answer()

@router.callback_query(F.data == "menu_reviews")
async def menu_reviews(callback: CallbackQuery):
    await callback.message.answer("⭐ https://t.me/ObsidianReviews")
    await callback.answer()

@router.callback_query(F.data == "menu_about")
async def menu_about(callback: CallbackQuery):
    await callback.message.answer("⚫️ ObsidianExchange — тёмный обменник без KYC. Автовыплаты, поддержка BTC, LTC, USDT, двойная защита.")
    await callback.answer()

# ---------- ОБМЕН ----------
def generate_captcha():
    a = random.randint(5, 25)
    b = random.randint(5, 25)
    return a, b, a + b

def is_user_blocked(user_id):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT 1 FROM blocked_users WHERE user_id=?", (user_id,))
    if c.fetchone():
        conn.close()
        return True
    c.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count >= 30

@router.callback_query(F.data.startswith("cur_"))
async def process_currency(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[1]
    await state.update_data(currency=currency)
    min_amt = MIN_AMOUNT
    max_amt = MAX_AMOUNT
    await callback.message.answer(
        f"💵 Введите сумму в RUB\n🔹 Минимум: {min_amt} ₽\n🔹 Максимум: {max_amt} ₽",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Exchange.amount)
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
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute("UPDATE orders SET status='paid' WHERE order_id=? AND status='pending'", (order_id,))
        conn.commit()
        conn.close()
        await callback.message.edit_caption(caption=f"✅ Заявка #{order_id} оплачена! Ожидайте отправку.", parse_mode="HTML") if callback.message.photo else await callback.message.edit_text(f"✅ Заявка #{order_id} оплачена! Ожидайте отправку.", parse_mode="HTML")
        await callback.answer("Статус обновлён на 'оплачено'")
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT order_id, rub_amount, crypto_address, currency, status, created_at, paid_btc_tx FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (message.from_user.id,))
    orders = c.fetchall()
    conn.close()
    if not orders:
        await message.answer("У вас пока нет заявок.")
        return
    text = "📋 Ваши заявки:\n\n"
    for o in orders:
        oid, rub, addr, curr, status, created, tx = o
        emoji = {"pending": "⏳", "paid": "✅", "sent": "🚀"}.get(status, status)
        text += f"#{oid} {emoji} {rub} RUB → {curr}\nАдрес: {addr}\n"
        if tx: text += f"TX: {tx}\n"
        text += f"Дата: {created[:16]}\n\n"
    await message.answer(text)

# ---------- ПРОФИЛЬ ----------
async def profile(message: Message):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (message.from_user.id,))
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status IN ('sent','paid')", (message.from_user.id,))
    completed = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (message.from_user.id,))
    refs = c.fetchone()[0]
    conn.close()
    await message.answer(f"⚫️ Профиль ObsidianExchange\n\nВсего заявок: {total}\nЗавершённых выплат: {completed}\nПриглашённых рефералов: {refs}\nЛимит заявок: 30")

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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM orders")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE status = 'sent'")
    sent = c.fetchone()[0]
    c.execute("SELECT SUM(rub_amount) FROM orders WHERE status = 'sent'")
    volume = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
    pending = c.fetchone()[0]
    conn.close()
    text = f"📊 Статистика\nВсего заявок: {total}\nОжидают: {pending}\nУспешно: {sent}\nОборот: {volume:,.0f} RUB"
    await callback.message.edit_text(text)
    await callback.answer()

@router.callback_query(F.data == "admin_last_orders")
async def admin_last_orders(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT order_id, user_id, rub_amount, currency, status, created_at FROM orders ORDER BY created_at DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT * FROM (SELECT * FROM orders ORDER BY order_id DESC LIMIT 1000) ORDER BY order_id ASC")
    rows = c.fetchall()
    cols = [desc[0] for desc in c.description]
    conn.close()
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
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (fake_tx, order_id))
        conn.commit(); conn.close()
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
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("INSERT OR IGNORE INTO blocked_users (user_id, reason) VALUES (?, 'admin block')", (user_id,))
        conn.commit(); conn.close()
        await message.answer(f"✅ Пользователь {user_id} заблокирован.")
    except: await message.answer("/block USER_ID")

@router.message(Command("unblock"))
async def cmd_unblock(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("DELETE FROM blocked_users WHERE user_id = ?", (user_id,))
        conn.commit(); conn.close()
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) VALUES (?,?,?,?,?,'pending')",
                   (message.from_user.id, message.from_user.username, currency, amount, address))
    conn.commit()
    order_id = cursor.lastrowid

    # Получаем и сохраняем ссылку Platega (синхронно, чтобы редирект работал)
    import requests
    try:
        r = requests.post("http://5.206.224.157:5003/platega/invoice",
                         json={"order_id": order_id, "amount": str(amount)}, timeout=5)
        if r.status_code == 200:
            inv = r.json()
            redirect_url = inv.get("redirect") or inv.get("url") or inv.get("url") or inv.get("url") or inv.get("url")
            if redirect_url:
                cursor.execute("UPDATE orders SET paid_btc_tx = ? WHERE order_id = ?",
                               (redirect_url, order_id))
                conn.commit()
    except:
        pass

    conn.close()
    await notify_admin(order_id, message.from_user.id, amount, address, currency)

    # Отправляем клиенту кнопки и ссылку
    rate = get_rate_with_markup(currency, amount)
    crypto_amount = round(amount / rate, 8) if rate else 0
    payment_link = f"{PUBLIC_RELAY}/pay/{order_id}"
    caption = f"⚫️ ObsidianExchange\n✅ Заявка #{order_id} создана!\n⏳ Курс зафиксирован на 15 минут\n\nСумма: {amount} RUB\n≈ {crypto_amount} {currency} (комиссия {get_commission_percent(amount)}%)\n\n<a href='{payment_link}'>Оплатить</a>"
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{order_id}")],
        [InlineKeyboardButton(text="🔍 Проверить статус", callback_data=f"check_{order_id}")]
    ])
    await message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")
    await state.clear()
    # Отправляем клиенту кнопки и ссылку




# ---------- МОНИТОРИНГ БАЛАНСА ГОРЯЧЕГО КОШЕЛЬКА ----------
async def check_balance():
    # Проверка BTC
    try:
        wallet = Wallet('PayoutWallet')
        wallet.scan()
        balance = wallet.balance(network='bitcoin')
        if balance < 5000:
            await bot.send_message(ADMIN_ID, f"⚠️ Низкий баланс BTC: {balance} сатоши!\nПополните: {wallet.get_key().address}")
    except Exception as e:
        logger.error(f"Ошибка проверки баланса BTC: {e}")

    # Проверка LTC (через bitcoinlib, сеть litecoin)
    try:
        ltc_wallet = Wallet('PayoutLTC', network='litecoin')
        ltc_wallet.scan()
        ltc_balance = ltc_wallet.balance(network='litecoin')
        if ltc_balance < 500000:  # 0.005 LTC в сатоши
            await bot.send_message(ADMIN_ID, f"⚠️ Низкий баланс LTC: {ltc_balance} сатоши!\nПополните: {ltc_wallet.get_key().address}")
    except Exception as e:
        logger.error(f"Ошибка проверки баланса LTC: {e}")

    try:
        client = Tron()
        priv_key = PrivateKey(bytes.fromhex(os.getenv('USDT_PRIVATE_KEY')))
        addr = priv_key.public_key.to_base58check_address()
        contract = client.get_contract('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t')
        # balanceOf возвращает int с 6 decimals
        balance = contract.functions.balanceOf(addr)
        if balance < 1_000_000:  # меньше 1 USDT
            await bot.send_message(ADMIN_ID, f"⚠️ Низкий баланс USDT: {balance / 1e6:.2f} USDT\nПополните: {addr}")
    except Exception as e:
        logger.error(f"Ошибка проверки баланса USDT: {e}")



async def balance_monitor():
    while True:
        await check_balance()
        await asyncio.sleep(6 * 3600)  # раз в 6 часов


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
        f"Комиссия: 27% (500-2000 RUB), 23% (2000-10000 RUB), 21% (>10000 RUB)"
    )

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH, timeout=10)
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

    conn.close()
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
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            c.execute("SELECT COUNT(*), SUM(rub_amount) FROM orders WHERE date(created_at)=? AND status='sent'", (yesterday,))
            cnt, vol = c.fetchone()
            conn.close()
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
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        threshold = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("SELECT order_id FROM orders WHERE status='pending' AND created_at < ?", (threshold,))
        stuck = c.fetchall()
        if stuck:
            ids = ", ".join([str(row[0]) for row in stuck])
            await bot.send_message(ADMIN_ID, f"🕒 Зависшие заявки (>30 мин): {ids}")
        conn.close()
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
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO referral_addresses (user_id, currency, address) VALUES (?, 'BTC', ?)",
                  (message.from_user.id, address))
        conn.commit()
        conn.close()
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
        conn = sqlite3.connect(DB_PATH, timeout=10)
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
                    try:
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="🔄 Обменять снова", callback_data="menu_exchange")]
                        ])
                        await bot.send_message(user_id,
                            f"✅ Выплата #{order_id} выполнена автоматически!\nСумма: {rub_amount} RUB → {currency}\nTXID: <code>{payout_id}</code>",
                            reply_markup=kb, parse_mode="HTML")
                    except:
                        pass
                    await bot.send_message(ADMIN_ID, f"✅ Авто-выплата #{order_id}: {rub_amount} RUB → {currency}\nTXID: <code>{payout_id}</code>", parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка авто-выплаты #{order_id}: {e}")
                try:
                    await bot.send_message(user_id, "⚠️ Возникла временная задержка при отправке средств. Наша команда уже работает над решением. Пожалуйста, ожидайте.")
                except Exception:
                    pass
        conn.close()
        await asyncio.sleep(30)  # проверка каждые 30 секунд


# ---------- АВТОПРОВЕРКА USDT (TRC-20) ----------
async def auto_check_usdt():
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
                conn = sqlite3.connect(DB_PATH, timeout=10)
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
                conn.close()
        except Exception as e:
            logger.error(f"Ошибка проверки USDT: {e}")
        await asyncio.sleep(60)


@router.message(Command("history"))
async def cmd_history(message: Message):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT order_id, rub_amount, currency, status, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (message.from_user.id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.answer("У вас пока нет заявок.")
        return
    text = "📋 Ваши последние заявки:\n\n"
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT DISTINCT user_id FROM orders")
    users = c.fetchall()
    conn.close()
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
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            c.execute("UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?", (payout_id, order_id))
            conn.commit()
            c.execute("SELECT user_id FROM orders WHERE order_id=?", (order_id,))
            user_id = c.fetchone()
            conn.close()
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
            conn = sqlite3.connect(DB_PATH, timeout=10)
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO referral_addresses (user_id, currency, address) VALUES (?, 'BTC', ?)",
                      (message.from_user.id, address))
            conn.commit()
            conn.close()
            await message.answer("✅ Ваш BTC-адрес для реферальных бонусов сохранён!")
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

    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) VALUES (?,?,?,?,?,'pending')",
                   (message.from_user.id, message.from_user.username, currency, amount, address))
    conn.commit()
    order_id = cursor.lastrowid
    conn.close()

    await notify_admin(order_id, message.from_user.id, amount, address, currency)


    import requests
    payment_url = None
    try:
        r = requests.post("http://5.206.224.157:5003/platega/invoice",
                         json={"order_id": order_id, "amount": str(amount)}, timeout=5)
        if r.status_code == 200:
            inv = r.json()
            if inv.get("redirect"):
                payment_url = inv["redirect"]
                conn2 = sqlite3.connect(DB_PATH, timeout=5)
                c2 = conn2.cursor()
                c2.execute("UPDATE orders SET paid_btc_tx = ? WHERE order_id = ?",
                           (payment_url, order_id))
                conn2.commit()
                conn2.close()
    except:
        pass

    payment_link = f"{PUBLIC_RELAY}/pay/{order_id}"
    caption = (
        f"⚫️ ObsidianExchange\n"
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


async def process_payout_async(order_id, rub_amount, client_address, currency='BTC'):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, process_payout, order_id, rub_amount, client_address, currency)


@router.message(Command("history"))
async def cmd_history(message: Message, page: int = 1):
    try:
        if len(message.text.split()) > 1:
            page = int(message.text.split()[1])
    except:
        page = 1
    limit = 10
    offset = (page - 1) * limit
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT order_id, rub_amount, currency, status, created_at FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
              (message.from_user.id, limit, offset))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await message.answer("Нет заявок на этой странице.")
        return
    text = f"📋 История (стр. {page}):\n\n"
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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
    row = c.fetchone()
    conn.close()
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


def process_payout(order_id, rub_amount, client_address, currency='BTC'):
    if currency != 'BTC':
        logger.warning(f"Лёгкий кошелёк поддерживает только BTC. Заказ #{order_id} требует {currency}")
        return None
    rate = get_rate_with_markup('BTC')
    amount_btc = round(rub_amount / rate, 8)
    if amount_btc <= 0:
        logger.error(f"Нулевая сумма выплаты для заказа #{order_id}")
        return None
    try:
        wallet = Wallet('PayoutWallet')
        t = wallet.send_to(client_address, amount_btc, unit='btc', fee='auto')
        txid = t.txid
        logger.info(f"Выплата #{order_id} выполнена: {amount_btc} BTC -> {client_address}, txid={txid}")
        return txid
    except Exception as e:
        logger.exception(f"Ошибка выплаты #{order_id}: {e}")
        return None

async def process_payout_async(order_id, rub_amount, client_address, currency='BTC'):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, process_payout, order_id, rub_amount, client_address, currency)

async def main():
    # # asyncio.create_task(balance_monitor())
    asyncio.create_task(verify_backups())
    asyncio.create_task(ssl_healthcheck())
    asyncio.create_task(update_fees())
    # # asyncio.create_task(auto_check_payments())
    asyncio.create_task(auto_check_usdt())
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
