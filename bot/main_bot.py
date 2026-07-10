from contextlib import contextmanager
import asyncio, sqlite3, random, requests, os, sys, re, logging, time, csv, hmac, hashlib, aiohttp
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from pathlib import Path
from io import BytesIO, StringIO
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
                           CallbackQuery, FSInputFile, ContentType, InputMediaPhoto, WebAppInfo)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
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
ADMIN_ID_2 = int(os.getenv('ADMIN_ID_2', 0))  # второй админ: полные права, кроме удаления (removeworker)
ADMIN_IDS = {a for a in (ADMIN_ID, ADMIN_ID_2) if a}

def is_admin(uid) -> bool:
    return uid in ADMIN_IDS
RELAY_SITE = os.getenv('RELAY_SITE', 'http://127.0.0.1:5001')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')
MIN_AMOUNT = float(os.getenv('MIN_AMOUNT', 1000))
MAX_AMOUNT = float(os.getenv('MAX_AMOUNT', 500000))
HIGH_AMOUNT        = float(os.getenv('HIGH_AMOUNT', 100000))
AUTO_PAYOUT_LIMIT  = float(os.getenv('AUTO_PAYOUT_LIMIT', 5000))
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

def get_active_workers() -> list[int]:
    """Возвращает список user_id всех активных работников из БД."""
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM workers WHERE is_active=1")
            return [row[0] for row in c.fetchall()]
    except Exception:
        return []

def is_worker(user_id: int) -> bool:
    return user_id in get_active_workers()

# ---------- ОПЕРАТОРЫ ----------
# Оператор — сотрудник поддержки/обработки заявок. Может: подтверждать оплату,
# отвечать в тикеты, смотреть заявки и карточки клиентов, писать клиентам,
# смотреть данные платёжной сессии для разбора с трейдерами провайдера.
# НЕ может: статистика/выручка, рассылки, промокоды, курсы, блокировки,
# управление работниками/операторами, force_payout.

def get_active_operators() -> list[int]:
    """Возвращает список user_id всех активных операторов из БД."""
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM operators WHERE is_active=1")
            return [row[0] for row in c.fetchall()]
    except Exception:
        return []

def is_operator(user_id: int) -> bool:
    return user_id in get_active_operators()

def is_staff(user_id: int) -> bool:
    """Админ или оператор — доступ к обработке заявок и поддержке."""
    return is_admin(user_id) or is_operator(user_id)

def staff_ids() -> set[int]:
    """ID всех, кто обрабатывает заявки/поддержку: админы + активные операторы."""
    return ADMIN_IDS | set(get_active_operators())

def log_staff_action(uid: int, action: str, target_id=None, details=None):
    """Аудит действий операторов/админов в admin_log; ошибки не роняют вызов."""
    try:
        with db_conn(5) as conn:
            conn.execute(
                "INSERT INTO admin_log (admin_id, action, target_id, details) VALUES (?,?,?,?)",
                (uid, action, target_id, details)
            )
            conn.commit()
    except Exception as e:
        logger.debug(f"log_staff_action: {e}")
REFERRAL_BONUS_PERCENT = float(os.getenv('REFERRAL_BONUS_PERCENT', 10))
REFERRAL_DUST_BTC = 0.00002
REVIEWS_CHANNEL_ID = os.getenv('REVIEWS_CHANNEL_ID', '@ObsidianReviews')
SUPPORT_BOT = os.getenv('SUPPORT_BOT', '@ObsidianSupBot')
CHANNEL_ID = os.getenv('CHANNEL_ID', '')          # Основной канал для ежедневных постов
DAILY_POST_GIF      = os.getenv('DAILY_POST_GIF', '')
POST_HEADER_FILE_ID = os.getenv('POST_HEADER_FILE_ID', '')  # склеенные стикеры OBSIDIAN+EXCHANGE
DAILY_POST_HOUR_UTC = int(os.getenv('DAILY_POST_HOUR_UTC', '7'))  # 07:00 UTC = 10:00 МСК
SELL_BTC_ADDRESS = os.getenv('SELL_BTC_ADDRESS', '')
SELL_LTC_ADDRESS = os.getenv('SELL_LTC_ADDRESS', '')
SELL_USDT_ADDRESS = os.getenv('SELL_USDT_ADDRESS', '')

# Фирменные анимированные стикеры (см. /root/bot/create_assets.py)
STICKER_SET_NAME = os.getenv('STICKER_SET_NAME', '')
STICKER_CRYSTAL  = os.getenv('STICKER_CRYSTAL', '')
STICKER_EXCHANGE = os.getenv('STICKER_EXCHANGE', '')
STICKER_SUCCESS  = os.getenv('STICKER_SUCCESS', '')
STICKER_VIP      = os.getenv('STICKER_VIP', '')
STICKER_WAIT     = os.getenv('STICKER_WAIT', '')
STICKER_REFERRAL = os.getenv('STICKER_REFERRAL', '')
# Новые стикеры (seamless слова)
STICKER_OE   = os.getenv('STICKER_OE',   STICKER_CRYSTAL)
STICKER_BTC  = os.getenv('STICKER_BTC',  '')
STICKER_USDT = os.getenv('STICKER_USDT', '')
STICKER_LTC  = os.getenv('STICKER_LTC',  '')
STICKER_OK   = os.getenv('STICKER_OK',   '')
STICKER_OBS1 = os.getenv('STICKER_OBS1', '')
STICKER_OBS2 = os.getenv('STICKER_OBS2', '')
STICKER_OBS3 = os.getenv('STICKER_OBS3', '')
STICKER_EXC1 = os.getenv('STICKER_EXC1', '')
STICKER_EXC2 = os.getenv('STICKER_EXC2', '')
STICKER_EXC3 = os.getenv('STICKER_EXC3', '')
STICKER_OBM1 = os.getenv('STICKER_OBM1', '')
STICKER_OBM2 = os.getenv('STICKER_OBM2', '')

def _glow_text(draw_img, text, xy, font, color_bright, color_glow, glow_radius=18):
    """Рисует текст с неоновым glow-эффектом на PIL Image."""
    from PIL import Image as _Img, ImageDraw as _Draw, ImageFilter as _Flt
    # Слой с текстом (RGBA)
    layer = _Img.new('RGBA', draw_img.size, (0, 0, 0, 0))
    _Draw.Draw(layer).text(xy, text, font=font, fill=(255, 255, 255, 255), anchor='rm')
    blurred = layer.filter(_Flt.GaussianBlur(glow_radius))
    # Раскрашиваем glow в фиолетовый
    r, g, b = color_glow
    for px_layer, col in [(blurred, color_glow), (blurred, color_glow)]:
        glow_layer = _Img.new('RGBA', draw_img.size, (r, g, b, 0))
        glow_layer.putalpha(px_layer.split()[3])
        draw_img.paste(_Img.alpha_composite(
            _Img.new('RGBA', draw_img.size, (0,0,0,0)), glow_layer), mask=glow_layer.split()[3])
    # Сам текст поверх
    draw_img.paste(layer, mask=layer.split()[3])


_CARD_FONTS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Bold.otf',
]
def _card_font(sz):
    from PIL import ImageFont
    for p in _CARD_FONTS:
        try: return ImageFont.truetype(p, sz)
        except: pass
    return ImageFont.load_default()


_service_status_cache = {'ts': 0.0, 'data': None}

def get_service_status() -> dict:
    """Живой статус сервиса из provider_health (кеш 60 сек).
       ok: 'ok' | 'degraded' | 'down'; chip — короткий текст для карточки;
       line — строка для caption. Если Montera жив, добавляет реальные диапазоны сумм."""
    now = time.time()
    if _service_status_cache['data'] and now - _service_status_cache['ts'] < 60:
        return _service_status_cache['data']
    data = {'ok': 'ok', 'chip': 'онлайн', 'line': '🟢 Сервис онлайн — платежи принимаются'}
    try:
        with db_conn(5) as conn:
            rows = conn.execute("SELECT provider, is_healthy FROM provider_health").fetchall()
        healthy = {r[0] for r in rows if r[1]}
        real = healthy - {'FallbackProvider', 'PlategaProvider'}
        if real:
            if 'MonteraProvider' in real:
                try:
                    if '/root/relay' not in sys.path:
                        sys.path.insert(0, '/root/relay')
                    from providers.montera import MonteraProvider
                    avail = MonteraProvider().check_availability(10_000, 'sbp')
                    mn, mx = avail.get('min_available'), avail.get('max_available')
                    if mn and mx:
                        data['line'] = (f'🟢 Сервис онлайн · доступны суммы '
                                        f'{mn:,}–{mx:,} ₽'.replace(',', ' '))
                except Exception:
                    pass
        elif 'FallbackProvider' in healthy:
            data = {'ok': 'degraded', 'chip': 'онлайн',
                    'line': '🟡 Повышенная нагрузка — заявки обрабатываются чуть дольше'}
        else:
            data = {'ok': 'down', 'chip': 'пауза',
                    'line': '🔴 Кратковременные технические работы — попробуйте чуть позже'}
    except Exception as e:
        logger.debug(f'service status failed: {e}')
    _service_status_cache.update(ts=now, data=data)
    return data


def generate_rates_card(btc_rate: float, ltc_rate: float, usdt_rate: float) -> BytesIO:
    """Карточка курсов для /start — тёмный градиент, монеты в ряд, живой статус-чип."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    from datetime import datetime, timezone, timedelta

    EXAMPLE   = 10_000
    comm_btc  = get_commission_percent(EXAMPLE)
    comm_usdt = 2
    ex_btc  = round(EXAMPLE * (1 - comm_btc  / 100) / btc_rate,  6) if btc_rate  else 0
    ex_ltc  = round(EXAMPLE * (1 - comm_btc  / 100) / ltc_rate,  4) if ltc_rate  else 0
    ex_usdt = round(EXAMPLE * (1 - comm_usdt / 100) / usdt_rate, 2) if usdt_rate else 0

    W, H = 1280, 640
    BG_TOP    = (10,  2, 20)
    BG_BOT    = (24,  6, 48)
    CARD_FILL = (18,  5, 38, 235)
    CARD_EDGE = (98, 40, 190)
    PURPLE    = (168, 85, 247)
    MUTED     = (148, 120, 190)
    WHITE     = (246, 240, 255)

    def fnt(sz, bold=True):
        fp = _CARD_FONTS[0] if bold else _CARD_FONTS[0].replace('-Bold', '')
        for p in ([fp] + _CARD_FONTS):
            try: return ImageFont.truetype(p, sz)
            except Exception: pass
        return ImageFont.load_default()

    # Фон: вертикальный градиент + мягкие glow-пятна
    img = Image.new('RGB', (W, H), BG_TOP)
    grad = Image.new('L', (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(255 * y / H))
    grad = grad.resize((W, H))
    img = Image.composite(Image.new('RGB', (W, H), BG_BOT), img, grad)

    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([(W-560, -300), (W+240, 260)], fill=(124, 58, 237, 70))
    gd.ellipse([(-260, H-320), (360, H+240)], fill=(168, 85, 247, 45))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.alpha_composite(img.convert('RGBA'), glow)
    draw = ImageDraw.Draw(img)

    # Шапка: логотип
    lx, ly, d = 56, 62, 16
    draw.polygon([(lx, ly-d), (lx+d, ly), (lx, ly+d), (lx-d, ly)], fill=PURPLE)
    draw.polygon([(lx, ly-d+6), (lx+d-6, ly), (lx, ly+d-6), (lx-d+6, ly)], fill=(40, 8, 80))
    draw.text((lx+32, ly-12), 'OBSIDIAN', fill=WHITE, font=fnt(28), anchor='lm')
    draw.text((lx+32, ly+14), 'EXCHANGE', fill=MUTED, font=fnt(15), anchor='lm')

    # Шапка: живой статус-чип
    status = get_service_status()
    chip_style = {
        'ok':       ((20, 40, 24), (50, 120, 70),  (74, 222, 128), (180, 240, 200)),
        'degraded': ((44, 36, 12), (140, 110, 40), (250, 200, 80), (240, 220, 160)),
        'down':     ((48, 16, 16), (150, 60, 60),  (248, 113, 113), (250, 190, 190)),
    }[status['ok']]
    msk = datetime.now(timezone.utc) + timedelta(hours=3)
    chip_txt = f"{status['chip']}  ·  {msk.strftime('%H:%M МСК')}"
    tw = draw.textlength(chip_txt, font=fnt(17, False))
    cx1, cx0 = W - 48, W - 48 - int(tw) - 58
    draw.rounded_rectangle([(cx0, ly-20), (cx1, ly+20)], radius=20,
                           fill=chip_style[0], outline=chip_style[1], width=2)
    draw.ellipse([(cx0+20, ly-6), (cx0+32, ly+6)], fill=chip_style[2])
    draw.text((cx0+44, ly), chip_txt, fill=chip_style[3], font=fnt(17, False), anchor='lm')

    # Подзаголовок
    draw.text((56, 128), f'За {EXAMPLE:,} ₽ вы получите'.replace(',', ' '),
              fill=WHITE, font=fnt(26), anchor='lm')
    draw.text((56, 160), f'комиссия BTC/LTC {comm_btc}%  ·  USDT {comm_usdt}%  ·  без верификации',
              fill=MUTED, font=fnt(16, False), anchor='lm')

    # Три карточки монет в ряд
    coins = [
        ('B', 'BTC',  'Bitcoin',  f'{ex_btc:.6f}'.rstrip('0').rstrip('.'), (247, 147, 26)),
        ('Ł', 'LTC',  'Litecoin', f'{ex_ltc:.4f}'.rstrip('0').rstrip('.'), (165, 169, 202)),
        ('₮', 'USDT', 'Tether',   f'{ex_usdt:.2f}',                        (38, 161, 123)),
    ]
    GAP = 28
    CW = (W - 56*2 - GAP*2) // 3
    CY0, CY1 = 200, 520
    for i, (sym, ticker, name, val, accent) in enumerate(coins):
        x0 = 56 + i * (CW + GAP)
        card = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(card).rounded_rectangle([(x0, CY0), (x0+CW, CY1)], radius=24,
                                               fill=CARD_FILL, outline=CARD_EDGE, width=2)
        img = Image.alpha_composite(img, card)
        draw = ImageDraw.Draw(img)

        ccx, icy = x0 + CW // 2, CY0 + 74
        draw.ellipse([(ccx-36, icy-36), (ccx+36, icy+36)],
                     fill=(30, 8, 62), outline=accent, width=3)
        draw.text((ccx, icy-2), sym, fill=accent, font=fnt(34), anchor='mm')
        draw.text((ccx, icy+66), ticker, fill=WHITE, font=fnt(30), anchor='mm')
        draw.text((ccx, icy+96), name, fill=MUTED, font=fnt(16, False), anchor='mm')

        vy = CY0 + 244
        vfont = fnt(34)
        while draw.textlength(val, font=vfont) > CW - 40 and vfont.size > 20:
            vfont = fnt(vfont.size - 2)
        layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((ccx, vy), val, fill=(*WHITE, 255), font=vfont, anchor='mm')
        blur = layer.filter(ImageFilter.GaussianBlur(10))
        gl = Image.new('RGBA', (W, H), (*PURPLE, 0))
        gl.putalpha(blur.split()[3].point(lambda p: int(p * 0.55)))
        img = Image.alpha_composite(img, gl)
        img = Image.alpha_composite(img, layer)
        draw = ImageDraw.Draw(img)
        draw.text((ccx, vy+34), ticker, fill=MUTED, font=fnt(15, False), anchor='mm')

    # Футер: чипы преимуществ
    chips = ['Non-KYC', 'выплата ~15 мин', 'своп BTC · LTC · USDT', 'от 2 000 ₽']
    fy = 578
    total = sum(draw.textlength(c, font=fnt(16, False)) + 48 for c in chips) + 20 * (len(chips)-1)
    fx = (W - total) / 2
    for c in chips:
        tw = draw.textlength(c, font=fnt(16, False))
        draw.rounded_rectangle([(fx, fy-19), (fx+tw+48, fy+19)], radius=19,
                               outline=(80, 40, 140), width=2)
        draw.text((fx+24+tw/2, fy), c, fill=MUTED, font=fnt(16, False), anchor='mm')
        fx += tw + 48 + 20

    buf = BytesIO()
    img.convert('RGB').save(buf, 'PNG')
    buf.seek(0)
    return buf
def build_welcome_caption(btc_rate: float, ltc_rate: float, usdt_rate: float, vip_badge=''):
    """Caption к карточке курсов — комиссии, своп, правила."""
    badge_line = f' — {vip_badge}' if vip_badge else ''

    def fmt_rate(r, decimals=0):
        if not r:
            return '—'
        return f"{r:,.{decimals}f}".replace(',', ' ')

    btc_str  = fmt_rate(btc_rate)
    ltc_str  = fmt_rate(ltc_rate)
    usdt_str = fmt_rate(usdt_rate, 2)

    status = get_service_status()
    return (
        f"🟣 <b>ObsidianExchange{badge_line}</b>\n"
        f"{status['line']}\n\n"
        f"<blockquote>"
        f"₿  1 BTC  ≈  <b>{btc_str} ₽</b>\n"
        f"Ł  1 LTC  ≈  <b>{ltc_str} ₽</b>\n"
        f"💵 1 USDT ≈  <b>{usdt_str} ₽</b>"
        f"</blockquote>\n\n"
        f"<blockquote expandable>"
        f"📈 Комиссия BTC / LTC:\n"
        f"2 000 – 5 000 ₽  →  27%\n"
        f"5 000 – 10 000 ₽  →  25%\n"
        f"10 000 – 20 000 ₽  →  23%\n"
        f"от 20 000 ₽  →  19%\n\n"
        f"💵 USDT TRC20  →  2%\n\n"
        f"🔒 Non-KYC · Без верификации\n"
        f"⚡ Мин. сумма 2 000 ₽"
        f"</blockquote>\n\n"
        f"Выберите действие 👇"
    )


async def send_sticker_safe(chat_id, sticker_id):
    """Отправляет стикер, тихо игнорируя ошибки (заблокирован бот, неверный file_id и т.п.)."""
    if not sticker_id:
        return
    try:
        await bot.send_sticker(chat_id, sticker_id)
    except Exception as e:
        logger.debug(f"Не удалось отправить стикер {sticker_id} в {chat_id}: {e}")

def _montera_limits_text(avail: dict) -> str:
    """Форматирует строку с доступными диапазонами сумм для Montera."""
    slots = avail.get("slots") or []
    if not slots:
        return ""
    ranges = sorted({(int(s["min_limit"]), int(s["max_limit"])) for s in slots})
    parts = [f"{mn:,}–{mx:,} ₽".replace(",", " ") for mn, mx in ranges]
    return "Доступные диапазоны сумм прямо сейчас: " + ", ".join(parts)


async def montera_precheck(callback, amount, payment_method=None, order_id=None):
    """
    Предпроверка доступности Montera для данной суммы.
    Возвращает True если можно продолжать, False если уже ответили пользователю.
    """
    import sys
    sys.path.insert(0, '/root/relay')
    try:
        from providers.montera import MonteraProvider
        avail = MonteraProvider().check_availability(amount, payment_method)
    except Exception:
        return True  # при ошибке проверки — не блокируем, пробуем invoice

    if avail.get("available"):
        return True

    slots = avail.get("slots") or []
    mn = avail.get("min_available")
    mx = avail.get("max_available")
    method_label = "СБП" if payment_method == "sbp" else "карте"

    if not slots:
        # Вообще нет активных трейдеров
        detail = f"По {method_label} сейчас нет свободных реквизитов — трейдеры временно недоступны."
    else:
        # Трейдеры есть, но не под нашу сумму
        ranges_str = _montera_limits_text(avail)
        detail = (
            f"Ваша сумма <b>{int(amount):,} ₽</b> не входит ни в один доступный диапазон.\n"
            f"{ranges_str}".replace(",", " ")
        )

    await reply_no_requisites(callback, order_id, detail)
    return False


def user_success_count(user_id: int) -> int:
    """Число успешно проведённых (оплаченных/завершённых) заявок пользователя.
    Совпадает с определением 'success' в рейтинге, который шлём Montera."""
    if not user_id or user_id < 0:
        return 0
    try:
        with db_conn(3) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id=? "
                "AND status IN ('paid','sent','completed')",
                (user_id,)
            ).fetchone()
        return int(row[0] or 0)
    except Exception as e:
        logger.warning(f"user_success_count({user_id}): {e}")
        return 0


async def build_payment_methods_kb(order_id: int, amount: float, user_id: int = None) -> InlineKeyboardMarkup:
    """Клавиатура способов оплаты — показывает только методы, реально доступные для данной суммы."""
    import sys
    sys.path.insert(0, '/root/relay')
    rows = []
    amt = float(amount)

    # Montera показываем ТОЛЬКО клиентам с ≥1 успешно оплаченной сделкой —
    # требование трейдеров Montera (доверенные/повторные клиенты). Новичкам
    # Montera недоступна, для них работают Vertu / Storm QR / VietQR.
    montera_allowed = user_success_count(user_id) >= 1
    if montera_allowed:
        # Montera СБП — API сам определяет наличие трейдера
        rows.append([InlineKeyboardButton(
            text="📱 СБП — по номеру телефона",
            callback_data=f"pm_montera_sbp_{order_id}"
        )])
        # Montera Карта
        rows.append([InlineKeyboardButton(
            text="💳 Карта — реквизиты на экране",
            callback_data=f"pm_gp_card_{order_id}"
        )])

    # Vertu — СБП / Карта, подтверждение автоматическое (без чека)
    if os.getenv('VERTU_LOGIN', ''):
        rows.append([InlineKeyboardButton(
            text="⚡ СБП — авто-подтверждение",
            callback_data=f"pm_vertu_sbp_{order_id}"
        )])
        rows.append([InlineKeyboardButton(
            text="⚡ Карта — авто-подтверждение",
            callback_data=f"pm_vertu_card_{order_id}"
        )])

    # XPayConnect — СБП / Карта, подтверждение автоматическое вебхуком (без чека).
    # XPAY_BUTTONS=1 ставить только когда XPay включит методы мерчанту
    # (на 09.07.2026 allowed=[] — любой createOrder отдаёт 403)
    if os.getenv('XPAY_API_KEY', '') and os.getenv('XPAY_BUTTONS', '') == '1':
        rows.append([InlineKeyboardButton(
            text="🚀 СБП — мгновенное подтверждение",
            callback_data=f"pm_xpay_sbp_{order_id}"
        )])
        rows.append([InlineKeyboardButton(
            text="🚀 Карта — мгновенное подтверждение",
            callback_data=f"pm_xpay_card_{order_id}"
        )])

    # Brabus VietQR — QR-код для оплаты через Сбер/ВТБ, от 1 000 ₽
    if amt >= 1000:
        rows.append([InlineKeyboardButton(
            text="📷 QR-код (Сбер / ВТБ)",
            callback_data=f"pm_brabus_vietqr_{order_id}"
        )])

    # Lava — СБП / Карта через страницу оплаты (все банки)
    lava_shop = os.getenv('LAVA_SHOP_ID', '')
    if lava_shop:
        rows.append([InlineKeyboardButton(
            text="🌋 Все банки — СБП / Карта (Lava)",
            callback_data=f"pm_lava_{order_id}"
        )])

    # StormTrade — только методы, которых нет у остальных провайдеров.
    # По СБП/карте StormTrade НЕ показываем (худшая ставка) — он подключается
    # автоматически внутри PaymentService, если другие не выдали реквизиты.
    # «Перевод по номеру счёта» (TO_ACCOUNT) убран 08.07.2026 по требованию
    # StormTrade — направлять только СБП / перевод на карту.
    if os.getenv('STORMTRADE_API_KEY', ''):
        rows.append([InlineKeyboardButton(
            text="🔳 QR СБП — оплата по QR-коду",
            callback_data=f"pm_storm_sbpqr_{order_id}"
        )])

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def reply_no_requisites(message_or_callback, order_id=None, detail: str = ""):
    """Отправляет сообщение об ошибке выдачи реквизитов с контактом оператора."""
    order_part = f"(Заявка #{order_id}) " if order_id else ""
    extra = f"\n\n{detail}" if detail else ""
    text = (
        f"⚠️ {order_part}Автоматическая выдача реквизитов временно недоступна.{extra}\n\n"
        f"Попробуйте другой способ оплаты или немного позже.\n\n"
        f"💬 <b>Обмен также можно провести через оператора</b> — напишите нам, "
        f"и мы обработаем вашу заявку вручную в течение нескольких минут:\n"
        f"👤 {SUPPORT_BOT}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать оператору", url=f"https://t.me/{SUPPORT_BOT.lstrip('@')}")]
    ])
    target = message_or_callback.message if hasattr(message_or_callback, 'message') else message_or_callback
    await target.answer(text, reply_markup=kb, parse_mode="HTML")

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

async def notify_admins(text, **kwargs):
    """Отправляет сообщение всем админам из ADMIN_IDS; ошибки доставки не роняют вызов."""
    for _aid in ADMIN_IDS:
        try:
            await bot.send_message(_aid, text, **kwargs)
        except Exception as _e:
            logger.debug(f"notify_admins: не доставлено {_aid}: {_e}")

async def notify_staff(text, **kwargs):
    """Отправляет сообщение всем админам и активным операторам; ошибки не роняют вызов."""
    for _sid in staff_ids():
        try:
            await bot.send_message(_sid, text, **kwargs)
        except Exception as _e:
            logger.debug(f"notify_staff: не доставлено {_sid}: {_e}")
try:
    _redis = Redis(host='localhost', port=6379, db=1, decode_responses=False)
    storage = RedisStorage(_redis)
    logger.info("FSM storage: Redis (состояния сохраняются между перезапусками)")
except Exception as _e:
    storage = MemoryStorage()
    logger.warning(f"FSM storage: MemoryStorage (Redis недоступен: {_e})")
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
    receipt_upload = State()
    verification_upload = State()

class Review(StatesGroup):
    comment = State()

class Swap(StatesGroup):
    amount = State()
    address = State()

class Sell(StatesGroup):
    currency = State()
    amount = State()
    phone = State()

class LimitOrder(StatesGroup):
    currency   = State()
    direction  = State()
    rate       = State()
    amount     = State()
    address    = State()

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
        c.execute('''CREATE TABLE IF NOT EXISTS bot_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            first_seen TEXT DEFAULT (datetime('now')),
            last_seen TEXT DEFAULT (datetime('now')),
            broadcast_enabled INTEGER DEFAULT 1
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS operators (
            user_id INTEGER PRIMARY KEY, username TEXT, added_by INTEGER,
            added_at TEXT DEFAULT (datetime('now')), is_active INTEGER DEFAULT 1)''')
        c.execute('''CREATE TABLE IF NOT EXISTS rate_subscriptions (
            user_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            last_notified REAL DEFAULT 0,
            last_btc REAL DEFAULT 0,
            last_ltc REAL DEFAULT 0,
            last_usdt REAL DEFAULT 0
        )''')
        conn.commit()
        # Заполняем bot_users из истории заявок (для существующих пользователей)
        c.execute("""
            INSERT OR IGNORE INTO bot_users (user_id, username)
            SELECT DISTINCT user_id, username FROM orders WHERE user_id > 0
        """)
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

async def update_user_vip_volume(user_id: int, rub_amount: float):
    """Прибавляет объём к накопительному VIP-счётчику и уведомляет о повышении тира."""
    old_tier, _ = get_user_vip(user_id)
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
        return
    new_tier, new_disc = get_user_vip(user_id)
    if new_tier != old_tier and new_tier != 'Standard':
        badge = {'Platinum': '💎 Platinum', 'Gold': '🥇 Gold', 'Silver': '🥈 Silver'}.get(new_tier, new_tier)
        await send_sticker_safe(user_id, STICKER_VIP)
        try:
            await bot.send_message(
                user_id,
                f"🎉 <b>Поздравляем!</b> Вы достигли VIP-уровня {badge}!\n"
                f"Теперь скидка <b>{abs(new_disc)}%</b> применяется ко всем вашим обменам автоматически.",
                parse_mode="HTML"
            )
        except Exception:
            pass

def get_commission_percent(amount_rub, user_id: int = None):
    if amount_rub < 5000:
        base = 27
    elif amount_rub < 10000:
        base = 25
    elif amount_rub < 20000:
        base = 23
    else:
        base = 19
    if user_id:
        _, disc = get_user_vip(user_id)
        base = max(2, base + disc)
        # Применяем скидку активного промокода
        promo = _active_promos.get(user_id)
        if promo:
            base = max(1, base - promo[1])
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
        fmt_ok = any(re.match(p, addr) for p in [r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', r'^bc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == 'LTC':
        fmt_ok = any(re.match(p, addr) for p in [r'^[LM][1-9A-HJ-NP-Za-km-z]{26,33}$', r'^ltc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == 'USDT':
        fmt_ok = re.match(r'^T[A-Za-z1-9]{33}$', addr) is not None
    else:
        return False
    if not fmt_ok:
        return False
    # Проверка по черному списку адресов
    try:
        with db_conn(3) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM blocked_addresses WHERE address=?", (addr,))
            if c.fetchone():
                return False
    except Exception:
        pass
    return True

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
        ('account', '🏦 Счёт'),
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
    rub_fmt = f"{int(rub_amount):,}".replace(",", " ")
    text = (f"🆕 <b>Новая заявка #{order_id}</b>\n\n"
            f"<blockquote>"
            f"👤 Пользователь: <code>{user_id}</code>\n"
            f"💸 Сумма: <b>{rub_fmt} ₽</b> → <b>{crypto_amount} {currency}</b>\n"
            f"📬 Адрес: <code>{address}</code>"
            f"</blockquote>")
    try:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_{order_id}")]])
        await notify_staff( text, reply_markup=kb, disable_notification=False, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка уведомления админа: {e}")
    if rub_amount >= HIGH_AMOUNT:
        await notify_admins( f"⚠️ Крупная заявка #{order_id} на {rub_amount:,.0f} RUB")

async def notify_workers_paid(order_id, rub_amount, address, currency):
    """Уведомляет всех работников о заявке, ожидающей ручной отправки."""
    rate = get_rate_with_markup(currency, rub_amount)
    crypto_amount = round(rub_amount / rate, 8) if rate else 0
    text = (f"💳 <b>Заявка #{order_id} — оплачена</b>\n\n"
            f"Сумма: <b>{rub_amount:,.0f} RUB</b> → <code>{crypto_amount} {currency}</code>\n"
            f"Адрес: <code>{address}</code>\n\n"
            f"Необходима ручная отправка.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Отправить и указать TX", callback_data=f"worker_send_{order_id}")]
    ])
    workers = get_active_workers()
    if workers:
        for wid in workers:
            try:
                await bot.send_message(wid, text, reply_markup=kb, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Ошибка уведомления работника {wid}: {e}")
    else:
        # Нет активных воркеров — заявка не должна зависнуть: уведомляем админов,
        # они могут отправить крипту и отметить командой /force_payout ORDER_ID TXID
        admin_text = (text + f"\n\n⚠️ <b>Нет активных воркеров.</b>\n"
                      f"Отправьте крипту вручную и отметьте:\n"
                      f"<code>/force_payout {order_id} TXID</code>")
        await notify_admins(admin_text, parse_mode="HTML")

# ---------- /start ----------
def build_main_menu_kb() -> InlineKeyboardMarkup:
    """Главное меню — компактное: 5 рядов. Редкие функции в подменю «⚙️ Ещё»."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Купить", callback_data="menu_exchange"),
         InlineKeyboardButton(text="💰 Продать", callback_data="menu_sell")],
        [InlineKeyboardButton(text="🔄 Своп", callback_data="menu_swap"),
         InlineKeyboardButton(text="📋 Мои заявки", callback_data="menu_orders")],
        [InlineKeyboardButton(text="👥 Пригласить и заработать", callback_data="menu_ref")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu_profile"),
         InlineKeyboardButton(text="💬 Поддержка", callback_data="menu_support")],
        [InlineKeyboardButton(text="⚙️ Ещё", callback_data="menu_tools"),
         InlineKeyboardButton(text="🌐 Личный кабинет", web_app=WebAppInfo(url=f"{PUBLIC_RELAY}/webapp"))]
    ])


def build_tools_kb() -> InlineKeyboardMarkup:
    """Подменю «⚙️ Ещё» — инструменты и информация."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Лимитная заявка", callback_data="menu_limit"),
         InlineKeyboardButton(text="📅 DCA-автопокупка", callback_data="menu_dca")],
        [InlineKeyboardButton(text="🔒 Фиксация курса", callback_data="menu_ratelock"),
         InlineKeyboardButton(text="🎁 Подарить крипту", callback_data="menu_gift")],
        [InlineKeyboardButton(text="⭐ Отзывы", callback_data="menu_reviews"),
         InlineKeyboardButton(text="ℹ️ О сервисе", callback_data="menu_about")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_tools_back")]
    ])


@router.callback_query(F.data == "menu_tools")
async def menu_tools(callback: CallbackQuery):
    """Разворачивает подменю на месте — клавиатура меняется без нового сообщения."""
    try:
        await callback.message.edit_reply_markup(reply_markup=build_tools_kb())
    except Exception:
        await callback.message.answer("⚙️ Дополнительные инструменты:",
                                      reply_markup=build_tools_kb())
    await callback.answer()


@router.callback_query(F.data == "menu_tools_back")
async def menu_tools_back(callback: CallbackQuery):
    try:
        await callback.message.edit_reply_markup(reply_markup=build_main_menu_kb())
    except Exception:
        pass
    await callback.answer()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    # Верификация по запросу Montera: /start verify_<order_id>
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith('verify_'):
            try:
                verify_order_id = int(parts[1][7:])
                with db_conn(5) as conn_v:
                    c_v = conn_v.cursor()
                    c_v.execute(
                        "SELECT verification_requested FROM orders WHERE order_id=? AND user_id=?",
                        (verify_order_id, message.from_user.id)
                    )
                    vrow = c_v.fetchone()
                    # Получаем Montera order_id из payment_sessions
                    c_v.execute(
                        "SELECT provider_invoice_id FROM payment_sessions WHERE order_id=? AND provider='montera' ORDER BY id DESC LIMIT 1",
                        (verify_order_id,)
                    )
                    psrow = c_v.fetchone()
                if vrow and vrow[0]:
                    vtype = vrow[0]
                    montera_invoice_id = psrow[0] if psrow else None
                    await state.set_state(Exchange.verification_upload)
                    await state.update_data(
                        verify_order_id=verify_order_id,
                        verify_type=vtype,
                        montera_invoice_id=montera_invoice_id,
                    )
                    if vtype == 'video':
                        await message.answer(
                            f"🎥 <b>Подтверждение оплаты — заявка #{verify_order_id}</b>\n\n"
                            f"Для подтверждения перевода необходимо короткое видео (5–15 сек).\n\n"
                            f"Откройте PDF-чек из банковского приложения и запишите видео, "
                            f"показывая экран с чеком об операции. Детали платежа должны быть чётко видны.",
                            parse_mode="HTML"
                        )
                    else:
                        await message.answer(
                            f"📄 <b>Подтверждение оплаты — заявка #{verify_order_id}</b>\n\n"
                            f"Отправьте <b>PDF-файл</b> с чеком об операции из банковского приложения.",
                            parse_mode="HTML"
                        )
                    return
            except (ValueError, IndexError):
                pass

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
    # Регистрируем / обновляем пользователя
    try:
        with db_conn(5) as conn:
            conn.execute("""
                INSERT INTO bot_users (user_id, username, first_name, last_name, last_seen)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name,
                    last_seen=datetime('now')
            """, (message.from_user.id,
                  message.from_user.username,
                  message.from_user.first_name,
                  message.from_user.last_name))
            conn.commit()
    except Exception:
        pass
    btc_rate  = get_cached_rate('BTC')  or 0
    ltc_rate  = get_cached_rate('LTC')  or 0
    usdt_rate = get_cached_rate('USDT') or 0
    vip_name_s, _ = get_user_vip(message.from_user.id)
    vip_badge_s = {'Platinum': '💎 Platinum', 'Gold': '🥇 Gold', 'Silver': '🥈 Silver'}.get(vip_name_s, '')
    kb = build_main_menu_kb()
    try:
        card    = generate_rates_card(btc_rate, ltc_rate, usdt_rate)
        caption = build_welcome_caption(btc_rate, ltc_rate, usdt_rate, vip_badge_s)
        await message.answer_photo(BufferedInputFile(card.read(), filename='rates.png'),
                                   caption=caption, parse_mode='HTML', reply_markup=kb)
    except Exception as e:
        logger.warning(f'rates card failed: {e}')
        await message.answer(build_welcome_caption(btc_rate, ltc_rate, usdt_rate, vip_badge_s),
                             parse_mode='HTML', reply_markup=kb)

# ---------- ОБРАБОТЧИКИ МЕНЮ ----------
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    btc_rate = get_cached_rate('BTC')
    ltc_rate = get_cached_rate('LTC')
    usdt_rate = get_cached_rate('USDT')
    vip_name, _ = get_user_vip(callback.from_user.id)
    vip_badge = {'Platinum': '💎 Platinum', 'Gold': '🥇 Gold', 'Silver': '🥈 Silver'}.get(vip_name, '')
    kb = build_main_menu_kb()
    try:
        card    = generate_rates_card(btc_rate, ltc_rate, usdt_rate)
        caption = build_welcome_caption(btc_rate, ltc_rate, usdt_rate, vip_badge)
        await callback.message.answer_photo(BufferedInputFile(card.read(), filename='rates.png'),
                                            caption=caption, parse_mode='HTML', reply_markup=kb)
    except Exception as e:
        logger.warning(f'rates card failed: {e}')
        await callback.message.answer(build_welcome_caption(btc_rate, ltc_rate, usdt_rate, vip_badge),
                                      parse_mode='HTML', reply_markup=kb)
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
        await callback.message.answer_photo(FSInputFile(IMG_CURRENCIES), caption="🟣 <b>Купить криптовалюту</b>\n\nВыберите монету, которую хотите получить:", reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.answer("🟣 <b>Купить криптовалюту</b>\n\nВыберите монету, которую хотите получить:", reply_markup=kb, parse_mode="HTML")
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
        "🔄 <b>Своп криптовалют</b>\n\n"
        "<blockquote expandable>Прямой обмен BTC, LTC и USDT (TRC20) без рублей — вы отправляете монеты на указанный адрес и сразу получаете выбранную монету на свой кошелёк.\n\n💰 Комиссия ~1% включена в курс, скрытых сборов нет\n🔒 Без регистрации и KYC</blockquote>\n\n"
        "Выберите пару обмена:",
        reply_markup=kb,
        parse_mode="HTML"
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
    min_hint = f"\nМин. сумма: <b>{min_amount} {coin_from}</b>" if min_amount else ""
    await state.update_data(coin_from=coin_from, coin_to=coin_to)
    await callback.message.answer(
        f"🔄 <b>{coin_from} → {coin_to}</b>\n\n"
        f"Введите количество <b>{coin_from}</b>, которое хотите отправить:{min_hint}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])
    )
    await state.set_state(Swap.amount)
    await callback.answer()

@router.message(Swap.amount)
async def process_swap_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.').strip())
    except ValueError:
        await message.answer("❌ Введите число. Например: <code>5000</code>", parse_mode="HTML")
        return
    if amount <= 0:
        await message.answer("❌ Сумма должна быть больше нуля.")
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
        f"<blockquote>Отправляете: <b>{amount} {coin_from}</b>\nПолучаете: <b>≈ {estimated} {coin_to}</b></blockquote>\n\n"
        f"📥 Введите <b>{coin_to}-адрес</b> получателя:",
        parse_mode="HTML",
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
        await message.answer("❌ <b>Неверный адрес.</b>\n\nПроверьте, что вставили правильный адрес для выбранной валюты и попробуйте ещё раз.", parse_mode="HTML")
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
        f"✅ <b>Своп создан: {coin_from} → {coin_to}</b>\n\n"
        f"<blockquote>"
        f"📤 Отправьте: <b>{amount_from} {coin_from}</b>\n"
        f"📥 Получите: <b>≈ {estimated} {coin_to}</b>\n"
        f"📬 Адрес зачисления: <code>{address}</code>"
        f"</blockquote>\n\n"
        f"⬇️ Переведите монеты на этот адрес:\n<code>{deposit_address}</code>\n\n"
        f"⏳ Статус обновится автоматически. Отслеживайте на странице свопа:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Статус свопа", url=swap_link)]]),
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data == "menu_orders")
async def menu_orders(callback: CallbackQuery):
    await my_orders(callback.message, uid=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order_callback(callback: CallbackQuery):
    uid = callback.from_user.id
    try:
        oid = int(callback.data.split("_")[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Неверный ID", show_alert=True)
        return

    import datetime as _dt
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, status, created_at FROM orders WHERE order_id=?", (oid,))
        row = c.fetchone()

    if not row or row[0] != uid:
        await callback.answer("❌ Заявка не найдена.", show_alert=True)
        return
    _, status, created = row

    if status != "pending":
        await callback.answer(
            f"Нельзя отменить: заявка уже в статусе «{status}».",
            show_alert=True
        )
        return

    # Проверяем 10-минутное окно
    try:
        age = (_dt.datetime.utcnow() -
               _dt.datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
        if age > 600:
            await callback.answer(
                "⏰ Окно отмены истекло (10 минут).\nОбратитесь в поддержку: " + SUPPORT_BOT,
                show_alert=True
            )
            return
    except Exception:
        pass

    with db_conn(5) as conn:
        conn.execute(
            "UPDATE orders SET status='cancelled', updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
            (oid,)
        )
        conn.commit()

    await callback.message.edit_text(
        f"🚫 <b>Заявка #{oid} отменена.</b>\n\nСредства не были списаны.",
        parse_mode="HTML"
    )
    await callback.answer("Заявка отменена.")
    await notify_admins(
        f"🚫 Клиент {uid} отменил заявку #{oid}",
        parse_mode="HTML"
    )

@router.callback_query(F.data == "menu_ref")
async def menu_ref(callback: CallbackQuery):
    username = (await bot.get_me()).username
    ref_link = f"https://t.me/{username}?start=ref_{callback.from_user.id}"
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(total_bonus_btc), 0) FROM referrals WHERE referrer_id=?", (callback.from_user.id,))
        ref_count, total_bonus = c.fetchone()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", switch_inline_query=ref_link)],
        [InlineKeyboardButton(text="💸 Вывести бонус в BTC", callback_data="ref_withdraw")],
    ])
    text = (
        f"🎁 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей — получай <b>10%</b> от нашей комиссии в BTC за каждый их обмен.\n\n"
        f"🔗 Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        f"<blockquote>"
        f"👤 Приглашено: <b>{ref_count}</b>\n"
        f"💰 Накоплено: <b>{total_bonus:.8f} BTC</b>"
        f"</blockquote>\n\n"
        f"💡 Бонус начисляется сразу после завершения обмена реферала. "
        f"Вывести можно в любой момент на любой BTC-адрес."
    )
    await send_sticker_safe(callback.message.chat.id, STICKER_REFERRAL)
    if IMG_REFERRAL.exists():
        await callback.message.answer_photo(FSInputFile(IMG_REFERRAL), caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "rate_sub_toggle")
async def rate_sub_toggle(callback: CallbackQuery):
    uid = callback.from_user.id
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO rate_subscriptions (user_id) VALUES (?)", (uid,))
        c.execute("SELECT enabled FROM rate_subscriptions WHERE user_id=?", (uid,))
        current = c.fetchone()[0]
        new_val = 0 if current else 1
        c.execute("UPDATE rate_subscriptions SET enabled=? WHERE user_id=?", (new_val, uid))
        conn.commit()
    if new_val:
        await callback.answer("✅ Уведомления о курсе включены!", show_alert=True)
    else:
        await callback.answer("🔕 Уведомления о курсе отключены.", show_alert=True)


@router.callback_query(F.data == "prompt_promo")
async def prompt_promo(callback: CallbackQuery):
    uid = callback.from_user.id
    current = _active_promos.get(uid)
    if current:
        await callback.answer(
            f"Промокод активен — скидка {current[1]:.0f}%.\nОн применится к следующей заявке.",
            show_alert=True
        )
    else:
        await callback.message.answer(
            "🎟 Введите промокод командой:\n<code>/promo ВАШ_КОД</code>",
            parse_mode="HTML"
        )
        await callback.answer()


@router.callback_query(F.data == "ref_withdraw")
async def ref_withdraw(callback: CallbackQuery):
    await callback.answer()
    text = await withdraw_referral_bonus(callback.from_user.id)
    await callback.message.answer(text, parse_mode="HTML")

@router.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery):
    await profile(callback.message, uid=callback.from_user.id)
    await callback.answer()

@router.callback_query(F.data == "menu_support")
async def menu_support(callback: CallbackQuery):
    await callback.message.answer("💬 <b>Поддержка ObsidianExchange</b>\n\n<blockquote>Оператор ответит в течение нескольких минут. Сообщите номер заявки если вопрос по конкретному обмену.</blockquote>\n\n👤 @ObsidianSupBot", parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "menu_reviews")
async def menu_reviews(callback: CallbackQuery):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*), AVG(rating) FROM reviews WHERE status='published'")
        count, avg_rating = c.fetchone()
    text = (
        f"⭐ <b>Отзывы клиентов</b>\n\n"
        f"<blockquote>Средняя оценка: <b>{avg_rating:.1f} / 5</b>\nНа основе {count} отзывов</blockquote>\n\n" if count else
        f"⭐ <b>Отзывы клиентов</b>\n\nБудьте первым, кто оставит отзыв!\n\n"
    )
    text += "📢 Канал с отзывами: @ObsidianReviews"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "menu_about")
async def menu_about(callback: CallbackQuery):
    await callback.message.answer(
        "🟣 <b>ObsidianExchange</b>\n\n"
        "<blockquote expandable>"
        "Надёжный P2P-обменник нового поколения. Работаем с 2024 года.\n\n"
        "✅ Без KYC и верификации\n"
        "⚡ Автоматические выплаты\n"
        "🔒 Двойная защита каждой сделки\n"
        "💱 BTC, LTC, USDT (TRC20)\n"
        "💳 Оплата: СБП, карта, приложения банков"
        "</blockquote>\n\n"
        "📊 Комиссия от 2% (USDT) до 19% (крупные суммы BTC/LTC)\n"
        "🌐 obsidian-exchange.org\n\n"
        "<i>Используя сервис, вы принимаете условия пользовательского соглашения — /offer</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📜 Пользовательское соглашение",
                                 url=f"{PUBLIC_RELAY}/offer")
        ]])
    )
    await callback.answer()


_OFFER_TEXT = (
    "📜 <b>Пользовательское соглашение (публичная оферта)</b>\n\n"
    "<b>1. Общие положения</b>\n"
    "<blockquote expandable>1.1. Сервис «ObsidianExchange» (далее — Сервис) предоставляет пользователям возможность "
    "обмена рублей на криптовалюту (BTC, LTC, USDT TRC-20), обратного обмена криптовалюты на рубли "
    "и свопа криптовалют через Telegram-бота и сайт obsidian-exchange.org.\n"
    "1.2. Взаимодействие с пользователем осуществляется автоматически через Telegram-бота Сервиса. "
    "По вопросам работы Сервиса пользователь может обратиться в поддержку.\n"
    "1.3. Используя Сервис, пользователь подтверждает согласие с условиями настоящего соглашения.</blockquote>\n\n"
    "<b>2. Описание услуги</b>\n"
    "<blockquote expandable>2.1. Пользователь создаёт заявку в Telegram-боте или на сайте, указывая направление обмена, "
    "сумму и адрес получения.\n"
    "2.2. Сервис предоставляет пользователю реквизиты для перевода рублей.\n"
    "2.3. После поступления средств на указанные реквизиты Сервис отправляет пользователю указанную "
    "в заявке сумму в выбранной криптовалюте.\n"
    "2.4. Курс обмена и комиссии сообщаются пользователю до совершения операции. Курс фиксируется "
    "на срок действия заявки.\n"
    "2.5. При продаже криптовалюты порядок аналогичен: после поступления и подтверждения криптовалюты "
    "Сервис переводит рубли на реквизиты пользователя.</blockquote>\n\n"
    "<b>3. Ответственность сторон</b>\n"
    "<blockquote expandable>3.1. Сервис не несёт ответственности за ошибки пользователя при вводе реквизитов, адресов или сумм.\n"
    "3.2. Сервис не несёт ответственности за задержки, связанные с работой платёжных систем, банков "
    "или блокчейн-сетей.\n"
    "3.3. Сервис не несёт ответственности за последующее использование приобретённых пользователем средств.\n"
    "3.4. Перевод, выполненный с нарушением инструкции в заявке (неверная сумма, оплата по просроченной "
    "заявке, перевод с чужих реквизитов), может потребовать ручной проверки — сроки зачисления или "
    "возврата в этом случае увеличиваются.</blockquote>\n\n"
    "<b>4. Персональные данные</b>\n"
    "<blockquote expandable>4.1. Сервис обрабатывает данные пользователя (Telegram ID, адреса кошельков, реквизиты для выплат) "
    "исключительно для выполнения обмена.\n"
    "4.2. Данные не передаются третьим лицам.\n"
    "4.3. Сервис не требует прохождения верификации личности (KYC).</blockquote>\n\n"
    "<b>5. Изменения условий</b>\n"
    "<blockquote expandable>5.1. Сервис вправе изменять условия соглашения без предварительного уведомления.\n"
    "5.2. Актуальная версия всегда доступна на obsidian-exchange.org/offer и по команде /offer в боте.</blockquote>\n\n"
    "<b>6. Прочие условия</b>\n"
    "<blockquote expandable>6.1. Использование Сервиса означает полное согласие пользователя с настоящим соглашением.\n"
    "6.2. Все споры разрешаются путём переговоров через поддержку Сервиса.</blockquote>"
)

@router.message(Command("offer"))
async def cmd_offer(message: Message):
    await message.answer(_OFFER_TEXT, parse_mode="HTML")

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
        "💰 <b>Продажа крипты → RUB</b>\n\n"
        "<blockquote>Отправьте нам монеты на указанный адрес — мы переведём рубли по СБП на ваш номер телефона в течение 30–60 минут.\n\n💱 Курс: рыночный за вычетом комиссии\n~19–27% для BTC/LTC · ~2% для USDT</blockquote>\n\n"
        "Выберите монету для продажи:",
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
        f"💰 <b>Продажа {SELL_COIN_LABELS[currency]}</b>\n\n"
        f"<blockquote>"
        f"📬 Адрес для перевода:\n<code>{receive_addr}</code>\n"
        f"💱 Курс покупки: <b>{sell_rate:,.2f} ₽</b> за 1 {currency}\n"
        f"📦 Минимум: <b>{min_amt} {currency}</b>"
        f"</blockquote>\n\n"
        f"Введите количество <b>{currency}</b>, которое хотите продать:",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(Sell.amount)
async def process_sell_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
    except ValueError:
        await message.answer("❌ Введите число. Например: <code>0.01</code>", parse_mode="HTML")
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
        f"<blockquote>Продаёте: <b>{amount} {currency}</b>\nПолучите: <b>≈ {rub_amount:,.2f} ₽</b></blockquote>\n\n"
        f"📱 Введите номер телефона для выплаты по <b>СБП</b>:\n<code>79001234567</code>",
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
        await message.answer("⛔ Временная ошибка сервера. Попробуйте через минуту или обратитесь в поддержку @ObsidianSupBot")
        await state.clear()
        return

    await state.clear()

    await message.answer(
        f"✅ <b>Заявка на продажу #{sell_id} принята!</b>\n\n"
        f"<blockquote>"
        f"📤 Отправьте: <b>{amount} {currency}</b>\n"
        f"📬 На адрес:\n<code>{receive_addr}</code>\n\n"
        f"💰 Выплата: <b>≈ {rub_amount:,.2f} ₽</b>\n"
        f"📱 На СБП: <code>{phone}</code>"
        f"</blockquote>\n\n"
        f"⏳ После подтверждения транзакции выплата поступит в течение 30–60 минут.\n\n"
        f"💬 Вопросы: @ObsidianSupBot",
        parse_mode="HTML"
    )

    try:
        kb_admin = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выплатить (подтвердить)", callback_data=f"sell_confirm_{sell_id}")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"sell_reject_{sell_id}")]
        ])
        await notify_admins(
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
    if not is_admin(callback.from_user.id):
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

    await update_user_vip_volume(user_id, rub_amount)

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ <b>Выплачено</b> {rub_amount:,.2f} RUB на {sbp_phone}",
        parse_mode="HTML"
    )
    await callback.answer("✅ Отмечено как выплачено")
    await send_sticker_safe(user_id, STICKER_SUCCESS)
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
    if not is_admin(callback.from_user.id):
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
        # Приглашение оставить публичный отзыв на внешних площадках
        try:
            invite_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Канал отзывов", url="https://t.me/ObsidianReviews")],
                [InlineKeyboardButton(text="🌐 MMGP Forum", url="https://mmgp.ru/showthread.php?t=743938")],
            ])
            await bot.send_message(
                user_id,
                f"{'⭐' * rating} <b>Спасибо за оценку!</b>\n\n"
                f"Если хотите помочь другим клиентам сделать выбор — оставьте отзыв публично.\n"
                f"Это займёт 1 минуту и очень нам поможет 🙏",
                parse_mode="HTML",
                reply_markup=invite_kb
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить приглашение на внешний отзыв user {user_id}: {e}")
    else:
        try:
            await notify_admins(
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


def check_order_limits(user_id: int) -> str | None:
    """Возвращает текст ошибки если клиент превысил лимиты, иначе None.

    Лимиты:
    - Не более 3 заявок в статусе pending одновременно
    - Не более 10 новых заявок за 24 часа
    - Cooldown 3 минуты между заявками
    """
    try:
        import datetime as _dt
        now = _dt.datetime.utcnow()
        day_ago   = (now - _dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        three_min = (now - _dt.timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")
        with db_conn(5) as conn:
            c = conn.cursor()
            # Суточный лимит
            c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND created_at > ?",
                      (user_id, day_ago))
            daily = c.fetchone()[0]
            if daily >= 10:
                return "Достигнут суточный лимит заявок (10 в день). Попробуйте завтра."
            # Cooldown
            c.execute("SELECT MAX(created_at) FROM orders WHERE user_id=?", (user_id,))
            last = c.fetchone()[0]
            if last and last > three_min:
                return "Слишком частые заявки. Подождите 3 минуты перед следующей."
    except Exception:
        pass
    return None
@router.callback_query(F.data.startswith("cur_"))
async def process_currency(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.split("_")[1]
    await state.update_data(currency=currency)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Указать сумму в RUB", callback_data="amtmode_rub")],
        [InlineKeyboardButton(text=f"💱 Указать сумму в {currency}", callback_data="amtmode_crypto")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await callback.message.answer("💱 <b>Как указать сумму?</b>\n\nВведите сколько хотите заплатить в рублях, или сколько крипты хотите получить:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "amtmode_rub")
async def amtmode_rub(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        f"💵 <b>Введите сумму в рублях</b>\n\n<blockquote>Минимум: {int(MIN_AMOUNT):,} ₽\nМаксимум: {int(MAX_AMOUNT):,} ₽</blockquote>".replace(",", " "),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]),
        parse_mode="HTML"
    )
    await state.set_state(Exchange.amount)
    await callback.answer()

@router.callback_query(F.data == "amtmode_crypto")
async def amtmode_crypto(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    currency = data['currency']
    await callback.message.answer(
        f"💱 <b>Введите сумму в {currency}</b>\n\nБот автоматически рассчитает, сколько рублей нужно оплатить с учётом комиссии.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]),
        parse_mode="HTML"
    )
    await state.set_state(Exchange.crypto_amount)
    await callback.answer()

@router.message(Exchange.amount)
async def process_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.').strip())
    except ValueError:
        await message.answer("❌ Введите число. Например: <code>5000</code>", parse_mode="HTML")
        return
    if amount < MIN_AMOUNT or amount > MAX_AMOUNT:
        await message.answer(f"❌ Сумма должна быть от {MIN_AMOUNT} до {MAX_AMOUNT} RUB.")
        return
    # Скидка 1000 ₽ за каждый 5-й обмен от 5000 ₽
    if check_fifth_exchange_discount(message.from_user.id, amount):
        amount = max(amount - 1000, MIN_AMOUNT)
        await message.answer(
            f"🎰 <b>Поздравляем!</b> Это ваш юбилейный обмен — скидка <b>1 000 ₽</b> применена!\n"
            f"💵 К оплате: <b>{amount:,.0f} ₽</b>",
            parse_mode="HTML"
        )
    await state.update_data(amount=amount)
    a, b, correct = generate_captcha()
    await state.update_data(captcha_correct=correct)
    await message.answer(
        f"🛡 <b>Защита от роботов</b>\n\nСколько будет <b>{a} + {b}</b>?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]),
        parse_mode="HTML"
    )
    await state.set_state(Exchange.captcha)

@router.message(Exchange.crypto_amount)
async def process_crypto_amount(message: Message, state: FSMContext):
    try:
        crypto_amt = float(message.text.replace(',', '.').strip())
    except ValueError:
        await message.answer("❌ Введите число. Например: <code>5000</code>", parse_mode="HTML")
        return
    if crypto_amt <= 0:
        await message.answer("❌ Сумма должна быть больше нуля.")
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
        f"<blockquote>Чтобы получить <b>{crypto_amt} {currency}</b> нужно оплатить:\n<b>{rub_amount:,.2f} ₽</b>  (комиссия {get_commission_percent(rub_amount)}%)</blockquote>",
        parse_mode="HTML"
    )
    a, b, correct = generate_captcha()
    await state.update_data(captcha_correct=correct)
    await message.answer(
        f"🛡 <b>Защита от роботов</b>\n\nСколько будет <b>{a} + {b}</b>?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]),
        parse_mode="HTML"
    )
    await state.set_state(Exchange.captcha)

@router.message(Exchange.captcha)
async def process_captcha(message: Message, state: FSMContext):
    try:
        answer = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    if answer != data.get("captcha_correct"):
        await message.answer("❌ Неверный ответ. Попробуйте снова — введите /start чтобы начать заново.")
        await state.clear()
        return
    curr = data['currency']
    await message.answer(
        f"📥 <b>Введите {curr}-адрес</b>\n\nКуда отправить монеты после подтверждения оплаты:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]),
        parse_mode="HTML"
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
            await callback.answer("❌ Заявка не найдена", show_alert=True)
            return
        order_user_id, rub_amount, address, currency, status = row
        if status != 'pending':
            await callback.answer("ℹ️ Эта заявка уже обработана", show_alert=True)
            return
        rub_fmt2 = f"{int(rub_amount):,}".replace(",", " ")
        text = (f"💰 <b>Заявка #{order_id} — пользователь сообщил об оплате</b>\n\n"
                f"<blockquote>"
                f"👤 ID: <code>{order_user_id}</code>\n"
                f"💸 Сумма: <b>{rub_fmt2} ₽</b> · {currency}\n"
                f"📬 Адрес: <code>{address}</code>"
                f"</blockquote>\n\n"
                f"⚠️ Проверьте поступление средств перед подтверждением.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_{order_id}")]])
        await notify_staff( text, reply_markup=kb, disable_notification=False, parse_mode="HTML")
        msg_text = f"⏳ <b>Ожидаем подтверждение</b>\n\nИнформация об оплате заявки <b>#{order_id}</b> передана оператору. Обычно это занимает 5–15 минут."
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
            text = f"✅ <b>Заявка #{order_id} выполнена!</b>\n\n<blockquote>Монеты отправлены на ваш адрес</blockquote>\n\n🔗 <code>{tx}</code>"
        elif status == "paid":
            text = f"🔄 <b>Заявка #{order_id}</b>\n\n<blockquote>Оплата получена — обрабатываем отправку монет…</blockquote>"
        else:
            text = f"⏳ <b>Заявка #{order_id}</b>\n\n<blockquote>Ожидаем поступление оплаты</blockquote>\n\nЕсли уже оплатили — нажмите «Я оплатил»"
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
    if not is_staff(callback.from_user.id):
        await callback.answer("⛔ Нет прав доступа.", show_alert=True)
        return
    import random
    code = str(random.randint(1000, 9999))
    order_id = int(callback.data.split("_")[-1])
    pending_admin_action[callback.from_user.id] = {"order_id": order_id, "code": code, "timestamp": time.time()}
    await callback.message.answer(f"🔐 Ваш код подтверждения: <b>{code}</b>\nДействителен 5 минут.", parse_mode="HTML")
    await callback.answer("Код отправлен")

@router.message(Command("confirm"))
async def confirm_payout(message: Message):
    if not is_staff(message.from_user.id): return
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
                    log_staff_action(message.from_user.id, "confirm_order", order_id)
                    if not is_admin(message.from_user.id):
                        await notify_admins(
                            f"👷 Оператор @{message.from_user.username or message.from_user.id} "
                            f"подтвердил оплату заявки <b>#{order_id}</b>",
                            parse_mode="HTML")
                else:
                    await message.answer("Ошибка подтверждения.")
        del pending_admin_action[message.from_user.id]
    except: await message.answer("Использование: /confirm КОД")

# ---------- МОИ ЗАЯВКИ ----------
async def my_orders(message: Message, uid: int = None):
    # uid передаётся явно при вызове из callback: у callback.message
    # from_user — это сам бот, а не пользователь
    uid = uid or message.from_user.id
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("""SELECT order_id, rub_amount, crypto_address, currency, status,
                            created_at, paid_btc_tx
                     FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 8""", (uid,))
        orders = c.fetchall()
    if not orders:
        await message.answer(
            "🟣 <b>Мои заявки</b>\n\nУ вас пока нет ни одной заявки. Начните первый обмен прямо сейчас:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💱 Обменять", callback_data="menu_exchange")
            ]]),
            parse_mode="HTML"
        )
        return

    import datetime as _dt
    STATUS_ICON = {"pending": "⏳", "paid": "🔄", "sent": "🚀", "failed": "❌", "cancelled": "🚫"}
    STATUS_LABEL = {"pending": "Ожидает оплаты", "paid": "Обрабатывается",
                    "sent": "Выполнена", "failed": "Ошибка", "cancelled": "Отменена"}
    CUR_ICON = {"BTC": "₿", "LTC": "Ł", "USDT": "💵"}

    for oid, rub, addr, curr, status, created, tx in orders:
        icon   = STATUS_ICON.get(status, "❔")
        label  = STATUS_LABEL.get(status, status)
        cur_ic = CUR_ICON.get(curr, curr)
        amt_fmt = f"{int(rub):,}".replace(",", " ")
        addr_short = f"{addr[:6]}…{addr[-4:]}" if addr and len(addr) > 10 else (addr or "—")

        text = (
            f"{icon} <b>Заявка #{oid}</b> · {label}\n"
            f"<blockquote>"
            f"💸 {amt_fmt} ₽  →  {cur_ic} {curr}\n"
            f"📬 <code>{addr_short}</code>\n"
            f"🕐 {created[:16] if created else '—'}"
            f"</blockquote>"
        )
        if tx:
            tx_short = tx[:16] + "…" if len(tx) > 20 else tx
            text += f"\n🔗 <code>{tx_short}</code>"

        # Кнопки: отмена только для pending в первые 10 минут
        buttons = []
        if status == "pending" and created:
            try:
                age = (_dt.datetime.utcnow() -
                       _dt.datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
                if age < 600:
                    buttons.append(InlineKeyboardButton(
                        text="❌ Отменить", callback_data=f"cancel_order_{oid}"
                    ))
            except Exception:
                pass
        if tx and len(tx) > 20:
            # Угадываем блокчейн-эксплорер
            if curr == "BTC":
                explorer = f"https://mempool.space/tx/{tx}"
            elif curr == "LTC":
                explorer = f"https://blockchair.com/litecoin/transaction/{tx}"
            else:
                explorer = f"https://tronscan.org/#/transaction/{tx}"
            buttons.append(InlineKeyboardButton(text="🔍 Explorer", url=explorer))

        kb = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
        await message.answer(text, parse_mode="HTML", reply_markup=kb)

    await message.answer(
        f"📋 Последние {min(len(orders), 8)} заявок · Вся история: /myhistory",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💱 Новый обмен", callback_data="menu_exchange")
        ]])
    )

# ---------- ПРОФИЛЬ ----------
async def profile(message: Message, uid: int = None):
    # uid передаётся явно при вызове из callback (from_user у callback.message — бот)
    uid = uid or message.from_user.id
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM orders WHERE user_id=?", (uid,))
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*), COALESCE(SUM(rub_amount),0) FROM orders WHERE user_id=? AND status='sent'", (uid,))
        row = c.fetchone(); completed, volume = row[0], row[1]
        # Любимая валюта (по кол-ву выполненных заявок)
        c.execute("""SELECT currency, COUNT(*) as cnt FROM orders
                     WHERE user_id=? AND status='sent'
                     GROUP BY currency ORDER BY cnt DESC LIMIT 1""", (uid,))
        fav_row = c.fetchone()
        fav_currency = fav_row[0] if fav_row else None
        # Дата первой заявки
        c.execute("SELECT MIN(created_at) FROM orders WHERE user_id=?", (uid,))
        first_row = c.fetchone()
        first_date = first_row[0][:10] if first_row and first_row[0] else None
        # Рефералы
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (uid,))
        refs = c.fetchone()[0]
        c.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_bonuses WHERE referrer_id=?", (uid,))
        ref_bonus = c.fetchone()[0]
        # Подписка на курс
        c.execute("SELECT enabled FROM rate_subscriptions WHERE user_id=?", (uid,))
        sub_row = c.fetchone()
        sub_enabled = sub_row[0] if sub_row else 0

    vip_name, discount = get_user_vip(uid)
    vip_icons = {'Platinum': '💎 Platinum', 'Gold': '🥇 Gold', 'Silver': '🥈 Silver'}
    vip_line = vip_icons.get(vip_name, '⬜ Standard')
    if discount > 0:
        vip_line += f' (−{discount}%)'

    sub_icon = "🔔" if sub_enabled else "🔕"

    fav_icons = {'BTC': '₿', 'LTC': 'Ł', 'USDT': '💵'}
    fav_line = f"{fav_icons.get(fav_currency,'')}{fav_currency}" if fav_currency else "—"

    vol_fmt = f"{int(volume):,}".replace(",", " ")
    ref_bonus_fmt = f"{int(ref_bonus):,}".replace(",", " ")

    text = (
        f"👤 <b>Мой профиль — ObsidianExchange</b>\n\n"
        f"<blockquote>"
        f"📦 Заявок всего: <b>{total}</b>   ✅ Выполнено: <b>{completed}</b>\n"
        f"💰 Общий объём: <b>{vol_fmt} ₽</b>\n"
        f"🏅 Любимая валюта: <b>{fav_line}</b>\n"
        f"💎 VIP-статус: <b>{vip_line}</b>"
        f"</blockquote>\n\n"
        f"<blockquote>"
        f"🎁 Рефералов приглашено: <b>{refs}</b>\n"
        f"💸 Заработано на рефералке: <b>{ref_bonus_fmt} ₽</b>"
        f"</blockquote>\n\n"
        f"{sub_icon} Уведомления о курсе: <b>{'Вкл' if sub_enabled else 'Выкл'}</b>"
    )
    if first_date:
        text += f"\n📅 С нами с: <b>{first_date}</b>"

    # Есть ли активный промокод
    promo_active = _active_promos.get(uid)
    promo_btn_label = (f"🎟 Промокод активен (−{promo_active[1]:.0f}%)" if promo_active
                       else "🎟 Ввести промокод")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{sub_icon} {'Отключить' if sub_enabled else 'Включить'} уведомления о курсе",
                              callback_data="rate_sub_toggle")],
        [InlineKeyboardButton(text="🎁 Реферальная программа", callback_data="menu_ref")],
        [InlineKeyboardButton(text=promo_btn_label, callback_data="prompt_promo")],
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

# ---------- АДМИН-ПАНЕЛЬ ----------
@router.message(Command("report"))
async def cmd_report(message: Message):
    if not is_admin(message.from_user.id):
        return
    import datetime as _dt
    args = message.text.split()
    period = args[1] if len(args) > 1 else "today"
    today = _dt.datetime.utcnow().strftime("%Y-%m-%d")
    if period in ("today", "сегодня"):
        text = await build_admin_report("сегодня", today, today)
    elif period in ("week", "неделя"):
        d_from = (_dt.datetime.utcnow() - _dt.timedelta(days=7)).strftime("%Y-%m-%d")
        text = await build_admin_report("последние 7 дней", d_from, today)
    elif period in ("month", "месяц"):
        d_from = (_dt.datetime.utcnow() - _dt.timedelta(days=30)).strftime("%Y-%m-%d")
        text = await build_admin_report("последние 30 дней", d_from, today)
    else:
        # Вчера по умолчанию
        yesterday = (_dt.datetime.utcnow() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        text = await build_admin_report(f"вчера ({yesterday})", yesterday, yesterday)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id): return await message.answer("❌ Доступ запрещён.")
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
    if not is_admin(callback.from_user.id): return
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
    if not is_admin(callback.from_user.id): return
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
    if not is_admin(callback.from_user.id): return
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
    if not is_admin(callback.from_user.id): return
    await callback.message.edit_text("Введите команду /force_payout ORDER_ID")
    await callback.answer()

# /force_payout реализован ниже (cmd_force_payout) — с поддержкой TXID,
# уведомлением клиента и запросом оценки. Старый заглушечный обработчик убран,
# т.к. он затенял полноценный (aiogram берёт первый совпавший handler).

@router.callback_query(F.data == "admin_block_menu")
async def admin_block_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await callback.message.edit_text("Введите команду /block USER_ID")
    await callback.answer()

@router.callback_query(F.data == "admin_unblock_menu")
async def admin_unblock_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await callback.message.edit_text("Введите команду /unblock USER_ID")
    await callback.answer()

@router.message(Command("block"))
async def cmd_block(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        user_id = int(message.text.split()[1])
        with db_conn(10) as conn:
            conn.execute("INSERT OR IGNORE INTO blocked_users (user_id, reason) VALUES (?, 'admin block')", (user_id,))
            conn.commit()
        await message.answer(f"✅ Пользователь {user_id} заблокирован.")
    except: await message.answer("/block USER_ID")

@router.message(Command("unblock"))
async def cmd_unblock(message: Message):
    if not is_admin(message.from_user.id): return
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
        await message.answer("❌ <b>Неверный адрес.</b>\n\nПроверьте, что вставили правильный адрес для выбранной валюты и попробуйте ещё раз.", parse_mode="HTML")
        return
    # Антиспам: проверяем лимиты
    limit_err = check_order_limits(message.from_user.id)
    if limit_err:
        await message.answer(f"⛔ {limit_err}")
        return
    amount = data.get("amount")
    with db_conn(10) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) VALUES (?,?,?,?,?,'pending')",
                       (message.from_user.id, message.from_user.username, currency, amount, address))
        conn.commit()
        order_id = cursor.lastrowid

    # Фиксируем промокод если был активирован
    promo = _active_promos.pop(message.from_user.id, None)
    if promo:
        apply_promo_use(promo[0], message.from_user.id, order_id)

    await notify_admin(order_id, message.from_user.id, amount, address, currency)

    await state.update_data(order_id=order_id, amount=amount, currency=currency, address=address)
    await state.set_state(Exchange.payment_method)

    # Применяем фиксацию курса если есть
    _lock = get_active_rate_lock(message.from_user.id, currency)
    if _lock:
        rate = _lock["rate"] * (1 - get_commission_percent(amount, message.from_user.id) / 100)
        # Вычитаем комиссию за фиксацию из суммы (уменьшаем крипту, а не рубли)
        with db_conn(3) as conn:
            conn.execute("UPDATE rate_locks SET used=1, order_id=? WHERE id=?",
                         (_lock["lock_id"], order_id))
            conn.commit()
    else:
        rate = get_rate_with_markup(currency, amount)
    crypto_amount = round(amount / rate, 8) if rate else 0
    rub_fmt3 = f"{int(float(amount)):,}".replace(",", " ")
    text = (
        f"🟣 <b>Заявка #{order_id} создана</b>\n\n"
        f"<blockquote>"
        f"💸 Оплата: <b>{rub_fmt3} ₽</b>\n"
        f"⬇️ Получаете: <b>{crypto_amount} {currency}</b>\n"
        f"📉 Комиссия: <b>{get_commission_percent(amount)}%</b>\n"
        f"⏱ Курс действует: <b>15 минут</b>"
        f"</blockquote>\n\n"
        f"Выберите удобный способ оплаты 👇"
    )
    await send_sticker_safe(message.chat.id, STICKER_WAIT)
    inline_kb = await build_payment_methods_kb(order_id, amount, message.from_user.id)
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

    # Montera — только доверенным клиентам (≥1 успешная сделка). Защита от
    # подделки callback_data: кнопок у новичков нет, но callback можно скопировать.
    if (pm.startswith("pm_montera_sbp_") or pm.startswith("pm_gp_")) \
            and user_success_count(callback.from_user.id) < 1:
        await callback.answer("Этот способ доступен после первой успешной сделки.", show_alert=True)
        return

    if pm.startswith("pm_montera_sbp_"):
        try:
            from services.payment_service import PaymentService
            from providers.montera import MonteraProvider
            payment_service = PaymentService(provider=MonteraProvider())
            session = payment_service.create_session(order_id, amount, payment_method="sbp",
                                                     telegram_id=callback.from_user.id)
            if 'error' in session:
                # СБП-трейдер пропал пока шла проверка — пробуем карту автоматически
                avail_card = MonteraProvider().check_availability(amount, "card")
                if avail_card.get("available"):
                    await callback.message.answer(
                        "📱 СБП-реквизиты временно недоступны — автоматически переключаю на карту..."
                    )
                    session = payment_service.create_session(order_id, amount, payment_method="card",
                                                             telegram_id=callback.from_user.id)
                    if 'error' not in session:
                        raw_session = session.get('raw') or {}
                        requisites_text = format_requisites(raw_session)
                        receipt_url = raw_session.get("receipt_upload_url")
                        montera_iid = raw_session.get("order_id") or raw_session.get("id")
                        import datetime as _dt
                        _deadline = (_dt.datetime.utcnow() + _dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
                        with db_conn(5) as _c:
                            _c.execute("UPDATE orders SET montera_invoice_id=?, receipt_deadline=? WHERE order_id=?",
                                       (str(montera_iid), _deadline, order_id))
                            _c.commit()
                        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                                   f"Сумма: <b>{int(amount):,} ₽</b>\n\n"
                                   f"Переведите указанную сумму на карту:\n{requisites_text}\n\n"
                                   f"⏱ <b>У вас 30 минут</b> чтобы оплатить и отправить PDF-чек.\n\n"
                                   f"📄 <b>После оплаты отправьте PDF-чек</b> из банковского приложения.").replace(",", " ")
                        await state.update_data(montera_receipt_url=receipt_url, montera_invoice_id=montera_iid)
                        await state.set_state(Exchange.receipt_upload)
                        if IMG_SECURITY.exists() and len(caption) <= 1024:
                            await callback.message.answer_photo(FSInputFile(IMG_SECURITY), caption=caption, parse_mode="HTML")
                        else:
                            await callback.message.answer(caption, parse_mode="HTML")
                        await callback.answer()
                        return
                await reply_no_requisites(callback, order_id)
                await callback.answer()
                return
            raw_session = session.get('raw') or {}
            requisites_text = format_requisites(raw_session)
            receipt_url = raw_session.get("receipt_upload_url")
            montera_iid = raw_session.get("order_id") or raw_session.get("id")
        except Exception as e:
            logger.error(f"Ошибка создания сессии Montera SBP: {e}")
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        # Сохраняем invoice_id и дедлайн в БД
        import datetime as _dt
        _deadline = (_dt.datetime.utcnow() + _dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        with db_conn(5) as _c:
            _c.execute("UPDATE orders SET montera_invoice_id=?, receipt_deadline=? WHERE order_id=?",
                       (str(montera_iid), _deadline, order_id))
            _c.commit()

        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: <b>{int(amount):,} ₽</b>\n\n"
                   f"Переведите указанную сумму по СБП:\n{requisites_text}\n\n"
                   f"⏱ <b>У вас 30 минут</b> с момента создания заявки чтобы оплатить и отправить PDF-чек.\n\n"
                   f"📄 <b>После оплаты отправьте PDF-чек</b> из банковского приложения прямо сюда — "
                   f"без него оператор не сможет подтвердить платёж.").replace(",", " ")
        await state.update_data(montera_receipt_url=receipt_url, montera_invoice_id=montera_iid)
        await state.set_state(Exchange.receipt_upload)
        if IMG_SECURITY.exists() and len(caption) <= 1024:
            await callback.message.answer_photo(FSInputFile(IMG_SECURITY), caption=caption, parse_mode="HTML")
        else:
            await callback.message.answer(caption, parse_mode="HTML")
        await callback.answer()
        return

    elif pm.startswith("pm_gp_sbp_"):
        # GreenPay отключён — перенаправляем на Montera Card
        await callback.answer("Переключаю на оплату картой...", show_alert=False)
        if not await montera_precheck(callback, amount, "card", order_id):
            return
        try:
            from services.payment_service import PaymentService
            from providers.montera import MonteraProvider
            payment_service = PaymentService(provider=MonteraProvider())
            session = payment_service.create_session(order_id, amount, payment_method="card",
                                                     telegram_id=callback.from_user.id)
            if 'error' in session:
                await reply_no_requisites(callback, order_id)
                return
            raw_session = session.get('raw') or {}
            requisites_text = format_requisites(raw_session)
            receipt_url = raw_session.get("receipt_upload_url")
            montera_iid = raw_session.get("order_id") or raw_session.get("id")
        except Exception as e:
            logger.error(f"Ошибка создания сессии Montera (gp_sbp redirect): {e}")
            await reply_no_requisites(callback, order_id)
            return
        import datetime as _dt
        _deadline = (_dt.datetime.utcnow() + _dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        with db_conn(5) as _c:
            _c.execute("UPDATE orders SET montera_invoice_id=?, receipt_deadline=? WHERE order_id=?",
                       (str(montera_iid), _deadline, order_id))
            _c.commit()
        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: <b>{int(float(amount)):,} ₽</b>\n\n"
                   f"Переведите указанную сумму на карту:\n{requisites_text}\n\n"
                   f"⏱ <b>У вас 30 минут</b> чтобы оплатить и отправить PDF-чек.\n\n"
                   f"📄 <b>После оплаты отправьте PDF-чек</b> из банковского приложения.").replace(",", " ")
        await state.update_data(montera_receipt_url=receipt_url, montera_invoice_id=montera_iid)
        await state.set_state(Exchange.receipt_upload)
        if IMG_SECURITY.exists() and len(caption) <= 1024:
            await callback.message.answer_photo(FSInputFile(IMG_SECURITY), caption=caption, parse_mode="HTML")
        else:
            await callback.message.answer(caption, parse_mode="HTML")
        return

    elif pm.startswith("pm_gp_card_"):
        if not await montera_precheck(callback, amount, "card", order_id):
            await callback.answer()
            return
        try:
            from services.payment_service import PaymentService
            from providers.montera import MonteraProvider
            payment_service = PaymentService(provider=MonteraProvider())
            session = payment_service.create_session(order_id, amount, payment_method="card",
                                                     telegram_id=callback.from_user.id)
            if 'error' in session:
                await reply_no_requisites(callback, order_id)
                await callback.answer()
                return
            raw_session = session.get('raw') or {}
            requisites_text = format_requisites(raw_session)
            receipt_url = raw_session.get("receipt_upload_url")
            montera_iid = raw_session.get("order_id") or raw_session.get("id")
        except Exception as e:
            logger.error(f"Ошибка создания сессии Montera: {e}")
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        import datetime as _dt
        _deadline = (_dt.datetime.utcnow() + _dt.timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        with db_conn(5) as _c:
            _c.execute("UPDATE orders SET montera_invoice_id=?, receipt_deadline=? WHERE order_id=?",
                       (str(montera_iid), _deadline, order_id))
            _c.commit()

        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: <b>{int(amount):,} ₽</b>\n\n"
                   f"Переведите указанную сумму на карту:\n{requisites_text}\n\n"
                   f"⏱ <b>У вас 30 минут</b> с момента создания заявки чтобы оплатить и отправить PDF-чек.\n\n"
                   f"📄 <b>После оплаты отправьте PDF-чек</b> из банковского приложения прямо сюда — "
                   f"без него оператор не сможет подтвердить платёж.").replace(",", " ")
        await state.update_data(montera_receipt_url=receipt_url, montera_invoice_id=montera_iid)
        await state.set_state(Exchange.receipt_upload)
        if IMG_SECURITY.exists() and len(caption) <= 1024:
            await callback.message.answer_photo(FSInputFile(IMG_SECURITY), caption=caption, parse_mode="HTML")
        else:
            await callback.message.answer(caption, parse_mode="HTML")
        await callback.answer()
        return

    elif pm.startswith("pm_brabus_"):
        BRABUS_VARIANT_BY_PM = {
            # deeplink-варианты отключены — CROSS_BORDER ведёт на иностранные карты через редирект,
            # не на российские банки. Оставлены только для совместимости со старыми сообщениями.
            "pm_brabus_deeplink_": ("tbank_deeplink", None, 1000),
            "pm_brabus_alfa_":     ("alfa_deeplink",  None, 1000),
            "pm_brabus_tbank_":    ("tbank_deeplink", None, 1000),
            "pm_brabus_sber_":     ("sber_deeplink",  None, 1000),
            "pm_brabus_vietqr_":   ("vietqr",         None, 1000),
        }
        entry = next(
            (v for prefix, v in BRABUS_VARIANT_BY_PM.items() if pm.startswith(prefix)),
            None
        )
        if not entry:
            await callback.answer("Этот способ оплаты временно недоступен.")
            return
        variant, pmethod, min_amount = entry

        if float(amount) < min_amount:
            await reply_no_requisites(
                callback, order_id,
                f"Минимальная сумма для этого способа оплаты — {min_amount:,} ₽.".replace(",", " ")
            )
            await callback.answer()
            return

        try:
            from services.payment_service import PaymentService
            from providers.brabus import BrabusProvider
            provider = BrabusProvider(variant=variant)
            payment_service = PaymentService(provider=provider)
            session = payment_service.create_session(order_id, amount, payment_method=pmethod)
            if 'error' in session:
                await reply_no_requisites(callback, order_id)
                await callback.answer()
                return
            raw = session.get('raw') or {}
        except Exception as e:
            logger.error(f"Ошибка создания сессии Brabus[{variant}]: {e}")
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        invoice_id = raw.get('invoice_id')

        # VietQR — отправляем QR-картинку
        if variant == "vietqr":
            requisites_text = format_requisites(raw)
            qr_img = raw.get('qr_image_url')
            caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\nСумма: {int(amount):,} ₽\n\n"
                       f"Отсканируйте QR-код в приложении банка (Vietcombank/BIDV/Sber/VTB):\n{requisites_text}").replace(",", " ")
            inline_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{order_id}")],
                [InlineKeyboardButton(text="🔍 Проверить статус", callback_data=f"check_{order_id}")]
            ])
            if qr_img:
                await callback.message.answer_photo(qr_img, caption=caption, reply_markup=inline_kb, parse_mode="HTML")
            else:
                await callback.message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")
            await callback.answer()
            await state.clear()
            return

        # CROSS_BORDER deeplinks — отображаем как реквизиты карты (не кнопки-ссылки).
        # deal.requisites содержит номер карты получателя и держателя.
        requisites = raw.get("requisites") or {}
        card_number = requisites.get("card_number") or requisites.get("card")
        bank_name = requisites.get("bank_name", "")
        recipient = requisites.get("recipient") or requisites.get("holder") or ""

        if not card_number:
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        req_lines = [f"💳 <b>Номер карты:</b> <code>{card_number}</code>"]
        if bank_name:
            req_lines.append(f"🏦 <b>Банк:</b> {bank_name}")
        if recipient:
            req_lines.append(f"👤 <b>Получатель:</b> {recipient}")
        req_text = "\n".join(req_lines)

        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: <b>{int(amount):,} ₽</b>\n\n"
                   f"{req_text}\n\n"
                   f"⚠️ Переводите точную сумму с вашей карты.").replace(",", " ")
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton(text="🔍 Проверить статус", callback_data=f"check_{order_id}")],
        ])
        if IMG_SECURITY.exists() and len(caption) <= 1024:
            await callback.message.answer_photo(FSInputFile(IMG_SECURITY), caption=caption, reply_markup=inline_kb, parse_mode="HTML")
        else:
            await callback.message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")
        await callback.answer()
        await state.clear()
        return

    elif pm.startswith("pm_vertu_"):
        # Vertu: реквизиты на экране, оплата подтверждается автоматически
        # опросом статуса (relay: vertu_poll_task), чек не нужен
        method = "sbp" if pm.startswith("pm_vertu_sbp_") else "card"
        try:
            from services.payment_service import PaymentService
            from providers.vertu import VertuProvider
            payment_service = PaymentService(provider=VertuProvider())
            session = payment_service.create_session(order_id, amount, payment_method=method,
                                                     telegram_id=callback.from_user.id)
            if 'error' in session:
                await reply_no_requisites(callback, order_id)
                await callback.answer()
                return
            raw_session = session.get('raw') or {}
            requisites_text = format_requisites(raw_session)
        except Exception as e:
            logger.error(f"Ошибка создания сессии Vertu {method}: {e}")
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        # Vertu может скорректировать сумму (копейки) — платить нужно ровно её
        pay_amount = float(raw_session.get('amount_rub') or amount)
        if abs(pay_amount - round(pay_amount)) > 0.004:
            amount_str = f"{pay_amount:,.2f}"
            exact_note = "\n⚠️ Переведите <b>точную сумму</b> — до копейки."
        else:
            amount_str = f"{int(round(pay_amount)):,}"
            exact_note = ""
        way = "по СБП" if method == "sbp" else "на карту"
        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: <b>{amount_str} ₽</b>\n\n"
                   f"Переведите указанную сумму {way}:\n{requisites_text}\n{exact_note}\n"
                   f"⏱ Реквизиты действительны <b>30 минут</b>.\n"
                   f"✅ Оплата подтверждается автоматически — чек не требуется.").replace(",", " ")

    elif pm.startswith("pm_xpay_"):
        # XPayConnect: реквизиты на экране, оплата подтверждается автоматически
        # вебхуком /xpay/webhook, чек не нужен
        method = "sbp" if pm.startswith("pm_xpay_sbp_") else "card"
        try:
            from services.payment_service import PaymentService
            from providers.xpayconnect import XPayConnectProvider
            payment_service = PaymentService(provider=XPayConnectProvider())
            session = payment_service.create_session(order_id, amount, payment_method=method,
                                                     telegram_id=callback.from_user.id)
            if 'error' in session:
                await reply_no_requisites(callback, order_id)
                await callback.answer()
                return
            raw_session = session.get('raw') or {}
            requisites_text = format_requisites(raw_session)
        except Exception as e:
            logger.error(f"Ошибка создания сессии XPay {method}: {e}")
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        # XPay может сдвинуть сумму для уникализации — платить нужно ровно её
        pay_amount = float(raw_session.get('amount_rub') or amount)
        if abs(pay_amount - float(amount)) > 0.004:
            amount_str = f"{pay_amount:,.0f}" if pay_amount == int(pay_amount) else f"{pay_amount:,.2f}"
            exact_note = "\n⚠️ Переведите <b>точную сумму</b> — она изменена для автоматического зачисления."
        else:
            amount_str = f"{int(round(pay_amount)):,}"
            exact_note = ""
        way = "по СБП" if method == "sbp" else "на карту"
        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: <b>{amount_str} ₽</b>\n\n"
                   f"Переведите указанную сумму {way}:\n{requisites_text}\n{exact_note}\n"
                   f"⏱ Реквизиты действительны <b>30 минут</b>.\n"
                   f"✅ Оплата подтверждается автоматически — чек не требуется.").replace(",", " ")

    elif pm.startswith("pm_storm_"):
        # StormTrade: эксклюзивные методы (QR СБП / по номеру счёта).
        # Оплата подтверждается вебхуком /stormtrade/webhook — чек не нужен
        # pm_storm_account_ (TO_ACCOUNT) удалён 08.07.2026 по требованию StormTrade
        # (только СБП/карта) — старые кнопки получат «временно недоступен»
        STORM_METHOD_BY_PM = {
            "pm_storm_sbpqr_":   ("sbp_qr",  "по QR-коду СБП"),
            "pm_storm_mobile_":  ("mobile",  "на счёт мобильного"),
            "pm_storm_sbp_":     ("sbp",     "по СБП"),
            "pm_storm_card_":    ("card",    "на карту"),
        }
        entry = next(
            (v for prefix, v in STORM_METHOD_BY_PM.items() if pm.startswith(prefix)),
            None
        )
        if not entry:
            await callback.answer("Этот способ оплаты временно недоступен.")
            return
        method, way = entry
        try:
            from services.payment_service import PaymentService
            from providers.stormtrade import StormTradeProvider
            payment_service = PaymentService(provider=StormTradeProvider())
            session = payment_service.create_session(order_id, amount, payment_method=method,
                                                     telegram_id=callback.from_user.id)
            if 'error' in session:
                await reply_no_requisites(callback, order_id)
                await callback.answer()
                return
            raw = session.get('raw') or {}
        except Exception as e:
            logger.error(f"Ошибка создания сессии StormTrade {method}: {e}")
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        requisites = raw.get('requisites') or {}
        requisites_text = format_requisites(raw)
        payment_link = requisites.get('payment_link')
        qr_img = raw.get('qr_image_url')

        caption = (f"🟣 ObsidianExchange\nЗаявка #{order_id}\n\n"
                   f"Сумма: <b>{int(float(amount)):,} ₽</b>\n\n"
                   f"Переведите указанную сумму {way}:\n{requisites_text}\n\n"
                   f"⏱ Реквизиты действительны <b>30 минут</b>.\n"
                   f"✅ Оплата подтверждается автоматически — чек не требуется.").replace(",", " ")

        kb_rows = []
        if payment_link:
            kb_rows.append([InlineKeyboardButton(text="🔳 Открыть QR / оплатить →", url=payment_link)])
        kb_rows.append([InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{order_id}")])
        kb_rows.append([InlineKeyboardButton(text="🔍 Проверить статус", callback_data=f"check_{order_id}")])
        inline_kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

        if qr_img:
            try:
                await callback.message.answer_photo(qr_img, caption=caption, reply_markup=inline_kb, parse_mode="HTML")
            except Exception:
                await callback.message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")
        elif IMG_SECURITY.exists() and len(caption) <= 1024:
            await callback.message.answer_photo(FSInputFile(IMG_SECURITY), caption=caption, reply_markup=inline_kb, parse_mode="HTML")
        else:
            await callback.message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")
        await callback.answer()
        await state.clear()
        return

    elif pm.startswith("pm_lava_"):
        # Lava: создаём инвойс, отдаём кнопку-ссылку на страницу оплаты
        try:
            from providers.lava import LavaProvider
            lava = LavaProvider()
            result = lava.create_invoice(order_id, amount, payment_method=None)
        except Exception as e:
            logger.error(f"Lava create_invoice exception: {e}")
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        if 'error' in result:
            await reply_no_requisites(callback, order_id, result['error'])
            await callback.answer()
            return

        payment_url = result.get('payment_url')
        invoice_id  = result.get('invoice_id')
        if not payment_url:
            await reply_no_requisites(callback, order_id)
            await callback.answer()
            return

        caption = (
            f"🟣 ObsidianExchange\n"
            f"Заявка <b>#{order_id}</b>\n\n"
            f"Сумма: <b>{int(amount):,} ₽</b>\n\n"
            f"Нажмите кнопку — откроется страница оплаты.\n"
            f"Выберите свой банк, подтвердите перевод."
        ).replace(",", " ")

        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Перейти к оплате →", url=payment_url)],
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{order_id}")],
            [InlineKeyboardButton(text="🔍 Проверить статус", callback_data=f"check_{order_id}")],
        ])
        if IMG_SECURITY.exists() and len(caption) <= 1024:
            await callback.message.answer_photo(
                FSInputFile(IMG_SECURITY), caption=caption,
                reply_markup=inline_kb, parse_mode="HTML"
            )
        else:
            await callback.message.answer(caption, reply_markup=inline_kb, parse_mode="HTML")
        await callback.answer()
        await state.clear()
        return

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

@router.message(Exchange.receipt_upload, F.photo)
async def process_receipt_upload(message: Message, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("order_id")
    invoice_id = data.get("brabus_invoice_id")
    if not invoice_id:
        await message.answer("⚠️ Не найдена заявка для подтверждения. Обратитесь в поддержку.")
        return
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        file_bytes = await bot.download_file(file.file_path)
        import sys
        sys.path.insert(0, '/root/relay')
        from providers.brabus import BrabusProvider
        provider = BrabusProvider(variant="with_receipt")
        result = provider.confirm_transfer(invoice_id, file_bytes.read())
        if result.get('ok'):
            await message.answer(
                "✅ Чек отправлен на проверку! Как только оплата подтвердится, мы автоматически вышлем вашу криптовалюту.",
            )
            await notify_staff( f"🧾 Получен чек для заявки #{order_id} (Brabus invoice {invoice_id})")
        else:
            await message.answer(f"❌ Не удалось отправить чек: {result.get('error', 'неизвестная ошибка')}\nПопробуйте ещё раз или обратитесь в поддержку.")
    except Exception as e:
        logger.error(f"Ошибка отправки чека Brabus: {e}")
        await message.answer("❌ Не удалось отправить чек. Попробуйте ещё раз или обратитесь в поддержку.")
        return
    await state.clear()


@router.message(Exchange.receipt_upload, F.document)
async def process_montera_receipt_upload(message: Message, state: FSMContext):
    """Принимает PDF-чек для подтверждения оплаты через Montera."""
    data = await state.get_data()
    order_id = data.get("order_id")
    receipt_url = data.get("montera_receipt_url")

    # Если нет receipt_url — это не Montera, игнорируем документ
    if not receipt_url:
        await message.answer("⚠️ Для этого способа оплаты документ не требуется. Ожидайте подтверждения автоматически.")
        return

    doc = message.document
    if not doc or not (doc.mime_type == "application/pdf" or (doc.file_name or "").lower().endswith(".pdf")):
        await message.answer("📄 Пожалуйста, отправьте файл в формате <b>PDF</b> (чек из банковского приложения).",
                             parse_mode="HTML")
        return

    try:
        file = await bot.get_file(doc.file_id)
        file_bytes_io = await bot.download_file(file.file_path)
        file_bytes = file_bytes_io.read()

        import sys
        sys.path.insert(0, '/root/relay')
        from providers.montera import MonteraProvider
        result = MonteraProvider().upload_receipt(receipt_url, file_bytes, doc.file_name or "receipt.pdf")

        if result.get("ok"):
            import datetime as _dt
            with db_conn(5) as _c:
                _c.execute("UPDATE orders SET receipt_sent_at=? WHERE order_id=?",
                           (_dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), order_id))
                _c.commit()
            await message.answer(
                "✅ Чек принят!\n\n"
                "Проверка занимает несколько минут. Как только оплата будет подтверждена — "
                "мы автоматически вышлем вашу криптовалюту."
            )
            # Берём сумму для контекста админа
            with db_conn(5) as _oc:
                _or = _oc.execute("SELECT rub_amount, username FROM orders WHERE order_id=?", (order_id,)).fetchone()
            _amt = f"{int(_or[0]):,} ₽".replace(",", " ") if _or else "?"
            _uname = f"@{_or[1]}" if (_or and _or[1]) else str(message.from_user.id)
            await notify_staff(
                f"🧾 <b>Получен PDF-чек</b> — заявка <b>#{order_id}</b>\n"
                f"👤 {_uname} · 💸 {_amt}\n"
                f"📄 {doc.file_name or 'receipt.pdf'}",
                parse_mode="HTML")
            await state.clear()
        else:
            await message.answer(
                f"❌ Не удалось загрузить чек: {result.get('error', 'неизвестная ошибка')}\n"
                f"Попробуйте ещё раз или обратитесь к оператору: {SUPPORT_BOT}"
            )
    except Exception as e:
        logger.error(f"Ошибка загрузки чека Montera: {e}")
        await message.answer(f"❌ Ошибка при отправке чека. Напишите оператору: {SUPPORT_BOT}")


# ---------- MONTERA: верификация по запросу оператора ----------

@router.message(Exchange.verification_upload, F.video)
async def process_montera_video_verification(message: Message, state: FSMContext):
    """Принимает видео-верификацию по запросу оператора Montera."""
    data = await state.get_data()
    order_id = data.get("verify_order_id")
    montera_invoice_id = data.get("montera_invoice_id")
    if not montera_invoice_id:
        await message.answer(
            "⚠️ Не удалось найти заявку. Напишите оператору: " + SUPPORT_BOT
        )
        return
    try:
        video = message.video
        file = await bot.get_file(video.file_id)
        file_bytes_io = await bot.download_file(file.file_path)
        file_bytes = file_bytes_io.read()
        import sys
        sys.path.insert(0, '/root/relay')
        from providers.montera import MonteraProvider
        filename = f"verification_{order_id}.mp4"
        result = MonteraProvider().upload_additional_info(montera_invoice_id, file_bytes, filename, "video/mp4")
        if result.get("ok"):
            await message.answer(
                "✅ Видео принято!\n\n"
                "Проверка занимает несколько минут. "
                "После подтверждения мы вышлем криптовалюту автоматически."
            )
            with db_conn(5) as _oc2:
                _or2 = _oc2.execute("SELECT rub_amount, username FROM orders WHERE order_id=?", (order_id,)).fetchone()
            _amt2 = f"{int(_or2[0]):,} ₽".replace(",", " ") if _or2 else "?"
            _uname2 = f"@{_or2[1]}" if (_or2 and _or2[1]) else str(message.from_user.id)
            await notify_staff(
                f"🎥 <b>Получено видео-подтверждение</b> — заявка <b>#{order_id}</b>\n"
                f"👤 {_uname2} · 💸 {_amt2}",
                parse_mode="HTML")
            with db_conn(5) as conn_c:
                conn_c.execute("UPDATE orders SET verification_requested=NULL WHERE order_id=?", (order_id,))
                conn_c.commit()
            await state.clear()
        else:
            err = result.get('error', 'неизвестная ошибка')
            await message.answer(
                f"⏳ <b>Не удалось отправить видео</b>\n\n"
                f"{err}\n\n"
                f"Подождите 1-2 минуты и отправьте видео повторно — оно сохранено у вас в чате.\n"
                f"Если ошибка повторяется — напишите оператору: {SUPPORT_BOT}",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Ошибка загрузки видео Montera: {e}")
        await message.answer(f"❌ Ошибка при отправке видео. Напишите оператору: {SUPPORT_BOT}")


@router.message(Exchange.verification_upload, F.document)
async def process_montera_pdf_verification(message: Message, state: FSMContext):
    """Принимает PDF-чек для верификации 'pdf-success' по запросу оператора Montera."""
    data = await state.get_data()
    order_id = data.get("verify_order_id")
    montera_invoice_id = data.get("montera_invoice_id")
    if not montera_invoice_id:
        await message.answer(
            "⚠️ Не удалось найти заявку. Напишите оператору: " + SUPPORT_BOT
        )
        return
    doc = message.document
    if not doc or not (doc.mime_type == "application/pdf" or (doc.file_name or "").lower().endswith(".pdf")):
        await message.answer(
            "📄 Пожалуйста, отправьте файл в формате <b>PDF</b> (чек из банковского приложения).",
            parse_mode="HTML"
        )
        return
    try:
        file = await bot.get_file(doc.file_id)
        file_bytes_io = await bot.download_file(file.file_path)
        file_bytes = file_bytes_io.read()
        import sys
        sys.path.insert(0, '/root/relay')
        from providers.montera import MonteraProvider
        filename = doc.file_name or f"verification_{order_id}.pdf"
        result = MonteraProvider().upload_additional_info(montera_invoice_id, file_bytes, filename, "application/pdf")
        if result.get("ok"):
            await message.answer(
                "✅ PDF-чек принят!\n\n"
                "Проверка занимает несколько минут. "
                "После подтверждения мы вышлем криптовалюту автоматически."
            )
            with db_conn(5) as _oc3:
                _or3 = _oc3.execute("SELECT rub_amount, username FROM orders WHERE order_id=?", (order_id,)).fetchone()
            _amt3 = f"{int(_or3[0]):,} ₽".replace(",", " ") if _or3 else "?"
            _uname3 = f"@{_or3[1]}" if (_or3 and _or3[1]) else str(message.from_user.id)
            await notify_staff(
                f"📄 <b>Получен PDF-чек верификации</b> — заявка <b>#{order_id}</b>\n"
                f"👤 {_uname3} · 💸 {_amt3}",
                parse_mode="HTML")
            with db_conn(5) as conn_c:
                conn_c.execute("UPDATE orders SET verification_requested=NULL WHERE order_id=?", (order_id,))
                conn_c.commit()
            await state.clear()
        else:
            err = result.get('error', 'неизвестная ошибка')
            await message.answer(
                f"⏳ <b>Не удалось отправить PDF</b>\n\n"
                f"{err}\n\n"
                f"Подождите 1-2 минуты и отправьте файл повторно — он сохранён у вас в чате.\n"
                f"Если ошибка повторяется — напишите оператору: {SUPPORT_BOT}",
                parse_mode="HTML"
            )
    except Exception as e:
        logger.error(f"Ошибка загрузки PDF-верификации Montera: {e}")
        await message.answer(f"❌ Ошибка при отправке. Напишите оператору: {SUPPORT_BOT}")


# ========== РАБОТНИК (ОПЕРАТОР) ==========

class WorkerState(StatesGroup):
    waiting_tx = State()

# --- Команды админа для управления работниками ---

@router.message(Command("addworker"))
async def cmd_addworker(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /addworker <telegram_id> [username]")
        return
    try:
        wid = int(parts[1])
        wname = parts[2].lstrip('@') if len(parts) > 2 else None
        with db_conn(5) as conn:
            conn.execute(
                "INSERT INTO workers (user_id, username, added_by) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET is_active=1, username=excluded.username",
                (wid, wname, message.from_user.id)
            )
            conn.commit()
        await message.answer(f"✅ Работник {wid} (@{wname or '—'}) добавлен.")
        try:
            await bot.send_message(wid,
                "🟣 <b>Добро пожаловать в ObsidianExchange!</b>\n\n"
                "Вы добавлены как оператор по обработке заявок.\n\n"
                "Команды:\n"
                "/worker — список заявок к отправке\n\n"
                "При поступлении оплаченной заявки вы получите уведомление.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    except ValueError:
        await message.answer("❌ Неверный формат ID")

@router.message(Command("removeworker"))
async def cmd_removeworker(message: Message):
    # Удаление — только главный админ
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /removeworker <telegram_id>")
        return
    try:
        wid = int(parts[1])
        with db_conn(5) as conn:
            conn.execute("UPDATE workers SET is_active=0 WHERE user_id=?", (wid,))
            conn.commit()
        await message.answer(f"✅ Работник {wid} деактивирован.")
    except ValueError:
        await message.answer("❌ Неверный формат ID")

@router.message(Command("workers"))
async def cmd_workers_list(message: Message):
    if not is_admin(message.from_user.id):
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, username, added_at, is_active FROM workers ORDER BY added_at DESC")
        rows = c.fetchall()
    if not rows:
        await message.answer("Работников нет. /addworker <id>")
        return
    text = "👷 <b>Список работников:</b>\n\n"
    for uid, uname, added, active in rows:
        status = "✅" if active else "❌"
        text += f"{status} <code>{uid}</code> @{uname or '—'} (добавлен {added[:10]})\n"
    await message.answer(text, parse_mode="HTML")

# ══════════════════════════════════════════════════════════════════
# ОПЕРАТОРЫ — управление (админ) и рабочая панель
# ══════════════════════════════════════════════════════════════════

_OPERATOR_WELCOME = (
    "🟣 <b>Добро пожаловать в команду ObsidianExchange!</b>\n\n"
    "Вы добавлены как <b>оператор</b>. Ваши инструменты:\n\n"
    "📋 /op — рабочая панель (заявки на проверке, открытые тикеты)\n"
    "🔎 /order ID — карточка заявки + данные платёжной сессии (провайдер, "
    "invoice) для разбора с трейдерами\n"
    "🔄 /pending — оплаченные заявки, ожидающие выплаты\n"
    "🎫 /tickets — открытые обращения · ответ: /reply_ID текст\n"
    "👤 /finduser ID|@username — карточка клиента\n"
    "✉️ /msg USER_ID текст — написать клиенту от имени бота\n\n"
    "Уведомления о новых заявках, оплатах, чеках и тикетах будут приходить "
    "автоматически. Подтверждение оплаты — кнопкой под уведомлением "
    "(код придёт сюда, ввести: /confirm КОД).\n\n"
    "⚠️ Подтверждайте оплату только после реальной проверки поступления средств."
)

@router.message(Command("addoperator"))
async def cmd_addoperator(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /addoperator <telegram_id> [username]")
        return
    try:
        oid = int(parts[1])
        oname = parts[2].lstrip('@') if len(parts) > 2 else None
        with db_conn(5) as conn:
            conn.execute(
                "INSERT INTO operators (user_id, username, added_by) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET is_active=1, username=excluded.username",
                (oid, oname, message.from_user.id)
            )
            conn.commit()
        log_staff_action(message.from_user.id, "add_operator", oid, oname)
        await message.answer(f"✅ Оператор {oid} (@{oname or '—'}) добавлен.")
        try:
            await bot.send_message(oid, _OPERATOR_WELCOME, parse_mode="HTML")
        except Exception:
            await message.answer("ℹ️ Приветствие не доставлено — оператор должен сначала нажать Start у бота.")
    except ValueError:
        await message.answer("❌ Неверный формат ID")

@router.message(Command("deloperator"))
async def cmd_deloperator(message: Message):
    # Удаление — только главный админ (как /removeworker)
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /deloperator <telegram_id>")
        return
    try:
        oid = int(parts[1])
        with db_conn(5) as conn:
            conn.execute("UPDATE operators SET is_active=0 WHERE user_id=?", (oid,))
            conn.commit()
        log_staff_action(message.from_user.id, "del_operator", oid)
        await message.answer(f"✅ Оператор {oid} деактивирован.")
    except ValueError:
        await message.answer("❌ Неверный формат ID")

@router.message(Command("operators"))
async def cmd_operators_list(message: Message):
    if not is_admin(message.from_user.id):
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, username, added_at, is_active FROM operators ORDER BY added_at DESC")
        rows = c.fetchall()
    if not rows:
        await message.answer("Операторов нет. /addoperator <id>")
        return
    text = "🎧 <b>Операторы:</b>\n\n"
    for uid, uname, added, active in rows:
        status = "✅" if active else "❌"
        text += f"{status} <code>{uid}</code> @{uname or '—'} (добавлен {added[:10]})\n"
    await message.answer(text, parse_mode="HTML")

@router.message(Command("op"))
async def cmd_operator_panel(message: Message):
    """Рабочая панель оператора: заявки в работе + открытые тикеты."""
    if not is_staff(message.from_user.id):
        return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("""SELECT order_id, username, user_id, rub_amount, currency, created_at
                     FROM orders WHERE status='pending'
                     ORDER BY created_at DESC LIMIT 10""")
        pending = c.fetchall()
        paid_cnt = c.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()[0]
        c.execute("""SELECT id, username, user_id, subject, updated_at
                     FROM support_tickets WHERE status='open'
                     ORDER BY updated_at ASC LIMIT 10""")
        tickets = c.fetchall()
    text = "🎧 <b>Панель оператора</b>\n\n"
    if pending:
        text += f"⏳ <b>Ожидают оплаты/проверки ({len(pending)}):</b>\n"
        for oid, uname, uid, amt, cur, created in pending:
            text += f"  #{oid} @{uname or uid} · {int(amt):,} ₽ → {cur} · {created[11:16]} · /order {oid}\n".replace(",", " ")
        text += "\n"
    else:
        text += "⏳ Нет заявок, ожидающих оплаты.\n\n"
    text += f"🔄 Оплачено, ждут выплаты: <b>{paid_cnt}</b> (/pending)\n\n"
    if tickets:
        text += f"🎫 <b>Открытые тикеты ({len(tickets)}):</b>\n"
        for tid, uname, uid, subj, upd in tickets:
            text += f"  #{tid} @{uname or uid} — {(subj or 'Без темы')[:30]} · /reply_{tid}\n"
    else:
        text += "🎫 Открытых тикетов нет."
    await message.answer(text[:4000], parse_mode="HTML")

@router.message(Command("order"))
async def cmd_order_card(message: Message):
    """/order ID — карточка заявки + платёжная сессия (для разбора с трейдерами провайдера)."""
    if not is_staff(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Формат: /order ID")
        return
    oid = int(parts[1])
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT user_id, username, rub_amount, currency, crypto_address,
                            status, created_at, updated_at, paid_btc_tx
                     FROM orders WHERE order_id=?""", (oid,))
        row = c.fetchone()
        sessions = c.execute(
            """SELECT provider, provider_invoice_id, amount, status, created_at
               FROM payment_sessions WHERE order_id=? ORDER BY id DESC LIMIT 3""",
            (oid,)).fetchall()
    if not row:
        await message.answer(f"❌ Заявка #{oid} не найдена.")
        return
    uid, uname, amt, cur, addr, status, created, updated, tx = row
    STATUS_ICON = {"pending": "⏳", "paid": "🔄", "sent": "✅", "failed": "❌", "cancelled": "🚫"}
    amt_fmt = f"{int(amt):,}".replace(",", " ")
    tx_line = f"\n🔗 TX: <code>{tx}</code>" if tx else ""
    text = (
        f"{STATUS_ICON.get(status, '❔')} <b>Заявка #{oid}</b> — {status}\n\n"
        f"<blockquote>"
        f"👤 @{uname or '—'} · ID <code>{uid}</code>\n"
        f"💸 {amt_fmt} ₽ → {cur}\n"
        f"📬 <code>{addr}</code>\n"
        f"🕐 Создана: {created[:16]} · Обновлена: {(updated or '—')[:16]}"
        f"{tx_line}"
        f"</blockquote>\n"
    )
    if sessions:
        text += "\n💳 <b>Платёжные сессии</b> (для разбора с трейдером):\n"
        for prov, inv, s_amt, s_status, s_created in sessions:
            text += (f"  • <b>{prov}</b> · invoice <code>{inv or '—'}</code>\n"
                     f"    сумма {s_amt or amt:.2f} ₽ · {s_status} · {s_created[:16]}\n")
    else:
        text += "\n💳 Платёжных сессий нет (реквизиты не выдавались)."
    kb_rows = []
    if status == 'pending':
        kb_rows.append([InlineKeyboardButton(text="✅ Подтвердить оплату",
                                             callback_data=f"admin_confirm_{oid}")])
    kb_rows.append([InlineKeyboardButton(text="✉️ Написать клиенту",
                                         callback_data=f"admin_msg_{uid}")])
    await message.answer(text[:4000], parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

# --- Панель работника ---

@router.message(Command("worker"))
async def cmd_worker_panel(message: Message):
    if not is_worker(message.from_user.id):
        return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT order_id, rub_amount, crypto_address, currency, created_at "
            "FROM orders WHERE status='paid' ORDER BY created_at ASC LIMIT 20"
        )
        rows = c.fetchall()
    if not rows:
        await message.answer("✅ Нет заявок, ожидающих отправки.")
        return
    text = f"📋 <b>Заявки к отправке ({len(rows)}):</b>\n\n"
    buttons = []
    for oid, rub, addr, curr, created in rows:
        rate = get_rate_with_markup(curr, rub)
        crypto = round(rub / rate, 8) if rate else 0
        text += (f"<b>#{oid}</b> · {rub:,.0f} RUB → <code>{crypto} {curr}</code>\n"
                 f"Адрес: <code>{addr}</code>\n"
                 f"Время: {created[:16]}\n\n")
        buttons.append([InlineKeyboardButton(
            text=f"💸 Отправить #{oid}", callback_data=f"worker_send_{oid}"
        )])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("worker_send_"))
async def worker_send_start(callback: CallbackQuery, state: FSMContext):
    if not is_worker(callback.from_user.id) and not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет прав", show_alert=True)
        return
    order_id = int(callback.data.split("_")[-1])
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT rub_amount, crypto_address, currency, status FROM orders WHERE order_id=?", (order_id,))
        row = c.fetchone()
    if not row:
        await callback.answer("❌ Заявка не найдена", show_alert=True)
        return
    rub, addr, curr, status = row
    if status == 'sent':
        await callback.answer("✅ Уже отправлено", show_alert=True)
        return
    if status not in ('paid', 'pending'):
        await callback.answer(f"Статус: {status}", show_alert=True)
        return
    await state.set_state(WorkerState.waiting_tx)
    await state.update_data(worker_order_id=order_id)
    await callback.message.answer(
        f"💸 <b>Заявка #{order_id}</b>\n"
        f"Сумма: {rub:,.0f} RUB → <code>{curr}</code>\n"
        f"Адрес: <code>{addr}</code>\n\n"
        f"Отправьте крипту на адрес выше, затем введите <b>TXID транзакции</b>:",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(WorkerState.waiting_tx)
async def worker_enter_tx(message: Message, state: FSMContext):
    if not is_worker(message.from_user.id) and not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    order_id = data.get("worker_order_id")
    tx = message.text.strip()
    if not tx or len(tx) < 10:
        await message.answer("❌ Введите корректный TXID (минимум 10 символов).")
        return
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, rub_amount, currency FROM orders WHERE order_id=?", (order_id,))
        row = c.fetchone()
        if not row:
            await message.answer("❌ Заявка не найдена.")
            await state.clear()
            return
        user_id, rub_amount, currency = row
        c.execute(
            "UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=? AND status IN ('paid','pending')",
            (tx, order_id)
        )
        conn.commit()
    await state.clear()
    await message.answer(
        f"✅ <b>Заявка #{order_id} отмечена как выполнена</b>\n"
        f"TX: <code>{tx}</code>",
        parse_mode="HTML"
    )
    await notify_admins(
        f"💸 Работник @{message.from_user.username or message.from_user.id} "
        f"выполнил заявку #{order_id}\nTX: <code>{tx}</code>",
        parse_mode="HTML"
    )
    try:
        await send_sticker_safe(user_id, STICKER_SUCCESS)
        _exp = explorer_url(currency, tx)
        _kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔍 Транзакция в блокчейне", url=_exp)]]) if _exp else None
        await bot.send_message(
            user_id,
            f"🚀 <b>Заявка #{order_id} выполнена!</b>\n\n"
            f"Криптовалюта отправлена на ваш адрес.\n"
            f"TXID: <code>{tx}</code>\n\n"
            f"Спасибо за обмен в ObsidianExchange! 🟣",
            parse_mode="HTML",
            reply_markup=_kb
        )
    except Exception:
        pass
    try:
        await credit_referral_bonus(order_id, user_id, rub_amount)
        await update_user_vip_volume(user_id, rub_amount)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# ПРОМОКОДЫ
# ══════════════════════════════════════════════════════════════════

# user_id → (code_id, discount_percent) — хранится в памяти до применения
_active_promos: dict[int, tuple[int, float]] = {}

def check_promo_code(code: str, user_id: int) -> dict | None:
    """Валидирует промокод. Возвращает dict с code_id и discount или None."""
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT id, discount_percent, max_uses, uses_count, valid_until
                     FROM promo_codes
                     WHERE code=? COLLATE NOCASE AND is_active=1
                       AND valid_until >= datetime('now')""", (code,))
        row = c.fetchone()
        if not row:
            return None
        cid, disc, max_uses, uses_count, valid_until = row
        if uses_count >= max_uses:
            return None
        # Проверяем не использовал ли этот юзер уже
        c.execute("SELECT 1 FROM promo_uses WHERE code_id=? AND user_id=?", (cid, user_id))
        if c.fetchone():
            return None
    return {"code_id": cid, "discount": disc}

def apply_promo_use(code_id: int, user_id: int, order_id: int):
    """Фиксирует использование промокода."""
    with db_conn(5) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO promo_uses (code_id, user_id, order_id) VALUES (?,?,?)",
            (code_id, user_id, order_id)
        )
        conn.execute(
            "UPDATE promo_codes SET uses_count = uses_count + 1 WHERE id=?",
            (code_id,)
        )
        conn.commit()


@router.message(Command("promo"))
async def cmd_promo(message: Message):
    """Клиент вводит /promo КОД — код применяется к следующей заявке."""
    parts = message.text.split()
    if len(parts) < 2:
        current = _active_promos.get(message.from_user.id)
        if current:
            await message.answer(f"✅ У вас активирован промокод со скидкой <b>{current[1]:.0f}%</b>.\n"
                                 f"Он будет применён к следующей заявке.", parse_mode="HTML")
        else:
            await message.answer("Введите: <code>/promo КОД</code>", parse_mode="HTML")
        return
    code = parts[1].strip().upper()
    result = check_promo_code(code, message.from_user.id)
    if not result:
        await message.answer(
            "❌ Промокод не найден, уже использован вами или истёк срок действия."
        )
        return
    _active_promos[message.from_user.id] = (result["code_id"], result["discount"])
    await message.answer(
        f"🎉 Промокод <b>{code}</b> активирован!\n"
        f"Скидка <b>{result['discount']:.0f}%</b> к комиссии будет применена к следующей заявке.",
        parse_mode="HTML"
    )


@router.message(Command("addpromo"))
async def cmd_addpromo(message: Message):
    """/addpromo КОД СКИДКА МАКС_ИСПОЛЬЗОВАНИЙ ДНЕЙ_ДЕЙСТВИЯ"""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 5:
        await message.answer(
            "Формат: /addpromo КОД СКИДКА_% МАХ_ИСПОЛЬЗОВАНИЙ ДНЕЙ\n"
            "Пример: /addpromo OBSIDIAN20 5 100 30"
        )
        return
    code, discount, max_uses, days = parts[1].upper(), float(parts[2]), int(parts[3]), int(parts[4])
    import datetime as _dt
    valid_until = (_dt.datetime.utcnow() + _dt.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with db_conn(5) as conn:
        try:
            conn.execute(
                "INSERT INTO promo_codes (code, discount_percent, max_uses, valid_until) VALUES (?,?,?,?)",
                (code, discount, max_uses, valid_until)
            )
            conn.commit()
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
            return
    await message.answer(
        f"✅ Промокод создан:\n"
        f"Код: <b>{code}</b>\n"
        f"Скидка: <b>{discount:.0f}%</b>\n"
        f"Использований: <b>{max_uses}</b>\n"
        f"Действует до: <b>{valid_until[:10]}</b>",
        parse_mode="HTML"
    )


@router.message(Command("promos"))
async def cmd_promos(message: Message):
    """Список активных промокодов."""
    if not is_admin(message.from_user.id):
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT code, discount_percent, uses_count, max_uses, valid_until
                     FROM promo_codes WHERE is_active=1 ORDER BY id DESC LIMIT 20""")
        rows = c.fetchall()
    if not rows:
        await message.answer("Нет активных промокодов.")
        return
    text = "🎟 <b>Активные промокоды:</b>\n\n"
    for code, disc, used, maxu, until in rows:
        status = "✅" if used < maxu else "⛔"
        text += f"{status} <code>{code}</code> — {disc:.0f}% · {used}/{maxu} · до {until[:10]}\n"
    await message.answer(text, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
# БЛОКИРОВКА АДРЕСОВ (антифрод)
# ══════════════════════════════════════════════════════════════════

@router.message(Command("blockaddr"))
async def cmd_blockaddr(message: Message):
    """/blockaddr АДРЕС ПРИЧИНА — добавить адрес в чёрный список."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Формат: /blockaddr АДРЕС [причина]")
        return
    addr = parts[1].strip()
    reason = parts[2].strip() if len(parts) > 2 else "manual block"
    with db_conn(5) as conn:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO blocked_addresses (address, reason, blocked_by) VALUES (?,?,?)",
                (addr, reason, message.from_user.id)
            )
            conn.commit()
        except Exception as e:
            await message.answer(f"❌ {e}")
            return
    await message.answer(f"✅ Адрес заблокирован:\n<code>{addr}</code>\nПричина: {reason}", parse_mode="HTML")


@router.message(Command("unblockaddr"))
async def cmd_unblockaddr(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: /unblockaddr АДРЕС")
        return
    addr = parts[1].strip()
    with db_conn(5) as conn:
        conn.execute("DELETE FROM blocked_addresses WHERE address=?", (addr,))
        conn.commit()
    await message.answer(f"✅ Адрес разблокирован: <code>{addr}</code>", parse_mode="HTML")


@router.message(Command("blocklist"))
async def cmd_blocklist(message: Message):
    if not is_admin(message.from_user.id):
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT address, reason, created_at FROM blocked_addresses ORDER BY created_at DESC LIMIT 20")
        rows = c.fetchall()
    if not rows:
        await message.answer("Чёрный список пуст.")
        return
    text = "🚫 <b>Заблокированные адреса:</b>\n\n"
    for addr, reason, dt in rows:
        text += f"<code>{addr[:20]}…</code>\n  {reason} · {dt[:10]}\n"
    await message.answer(text, parse_mode="HTML")


# ══════════════════════════════════════════════════════════════════
# ЭКСПОРТ ИСТОРИИ ДЛЯ КЛИЕНТА
# ══════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════
# ПОДДЕРЖКА — ТИКЕТЫ ПРЯМО В БОТЕ
# ══════════════════════════════════════════════════════════════════

class SupportTicketState(StatesGroup):
    subject = State()
    message = State()
    reply   = State()   # для ответа от админа

# ОТКЛЮЧЁН: тикеты вынесены в отдельный support-бот (@ObsidianSupBot). Активен
# menu_support выше (редирект на support-бот). Ниже — легаси внутрибот-тикеты.
async def menu_support_new(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    # Показываем открытые тикеты юзера
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT id, subject, status, updated_at
                     FROM support_tickets WHERE user_id=?
                     ORDER BY updated_at DESC LIMIT 5""", (uid,))
        tickets = c.fetchall()

    kb_rows = []
    if tickets:
        for tid, subj, status, upd in tickets:
            icon = {"open": "🟡", "answered": "🟢", "closed": "⚫"}.get(status, "⚪")
            label = (subj or "Обращение")[:28]
            kb_rows.append([InlineKeyboardButton(
                text=f"{icon} #{tid} {label}", callback_data=f"ticket_view_{tid}"
            )])
    kb_rows.append([InlineKeyboardButton(text="✏️ Новое обращение", callback_data="ticket_new")])
    kb_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])

    text = "🆘 <b>Поддержка ObsidianExchange</b>\n\n"
    if tickets:
        text += "Ваши обращения:\n"
        text += "🟡 открыто · 🟢 отвечено · ⚫ закрыто\n"
    else:
        text += "У вас нет активных обращений.\n"
    text += "\nСреднее время ответа: до 30 минут."
    await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
                                  parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "ticket_new")
async def ticket_new(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "✏️ <b>Новое обращение</b>\n\nКратко опишите тему (1-2 слова):\n"
        "Например: <i>Зависла заявка</i>, <i>Ошибка оплаты</i>, <i>Другое</i>",
        parse_mode="HTML"
    )
    await state.set_state(SupportTicketState.subject)
    await callback.answer()


@router.message(SupportTicketState.subject)
async def ticket_enter_subject(message: Message, state: FSMContext):
    subj = message.text.strip()[:100]
    await state.update_data(ticket_subject=subj)
    await message.answer(
        f"📝 Тема: <b>{subj}</b>\n\n"
        f"Опишите проблему подробнее. Прикрепите скриншот если нужно:",
        parse_mode="HTML"
    )
    await state.set_state(SupportTicketState.message)


@router.message(SupportTicketState.message)
async def ticket_enter_message(message: Message, state: FSMContext):
    data = await state.get_data()
    # /reply_N без текста ведёт сюда же: у стаффа в data лежит admin_reply_tid —
    # это ответ в тикет, а не создание нового
    reply_tid = data.get("admin_reply_tid")
    if reply_tid and is_staff(message.from_user.id):
        await state.clear()
        await _send_admin_reply(reply_tid, message.text or message.caption or "[медиа]", message)
        return
    subj = data.get("ticket_subject", "Без темы")
    uid  = message.from_user.id
    uname = message.from_user.username or str(uid)
    text_body = message.text or message.caption or "[медиа-файл]"

    with db_conn(5) as conn:
        conn.execute(
            "INSERT INTO support_tickets (user_id, username, subject, status, web_user_id) VALUES (?,?,?,'open',0)",
            (uid, uname, subj)
        )
        tid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO support_messages (ticket_id, sender, message) VALUES (?,?,?)",
            (tid, "user", text_body)
        )
        conn.commit()

    # Пересылаем медиа если есть
    media_info = ""
    if message.photo:
        fid = message.photo[-1].file_id
        for _aid in staff_ids():
            try:
                await bot.send_photo(_aid, fid,
                    caption=f"🎫 <b>Тикет #{tid}</b> от @{uname} ({uid})\n<b>{subj}</b>\n\n{text_body}\n\n"
                            f"/reply_{tid}",
                    parse_mode="HTML")
            except Exception:
                pass
        media_info = " + фото"
    elif message.document:
        fid = message.document.file_id
        for _aid in staff_ids():
            try:
                await bot.send_document(_aid, fid,
                    caption=f"🎫 <b>Тикет #{tid}</b> от @{uname} ({uid})\n<b>{subj}</b>\n\n{text_body}\n\n"
                            f"/reply_{tid}",
                    parse_mode="HTML")
            except Exception:
                pass
        media_info = " + документ"
    else:
        await notify_staff(
            f"🎫 <b>Тикет #{tid}</b> от @{uname} ({uid})\n"
            f"<b>{subj}</b>\n\n{text_body}\n\n/reply_{tid}",
            parse_mode="HTML"
        )

    await message.answer(
        f"✅ <b>Обращение #{tid} принято!</b>\n\n"
        f"Ответим в течение 30 минут. Вы получите уведомление в этом боте.",
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data.startswith("ticket_view_"))
async def ticket_view(callback: CallbackQuery):
    tid = int(callback.data.split("_")[2])
    uid = callback.from_user.id
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT subject, status FROM support_tickets WHERE id=? AND user_id=?", (tid, uid))
        row = c.fetchone()
        if not row:
            await callback.answer("Тикет не найден.", show_alert=True)
            return
        subj, status = row
        c.execute("SELECT sender, message, created_at FROM support_messages WHERE ticket_id=? ORDER BY id",
                  (tid,))
        msgs = c.fetchall()

    status_label = {"open": "🟡 Открыт", "answered": "🟢 Отвечен", "closed": "⚫ Закрыт"}.get(status, status)
    text = f"🎫 <b>Тикет #{tid}</b> — {subj}\n{status_label}\n\n"
    for sender, msg_text, dt in msgs[-10:]:
        who = "👤 Вы" if sender == "user" else "🟣 Поддержка"
        text += f"<b>{who}</b> [{dt[:16]}]:\n{msg_text}\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать ещё", callback_data=f"ticket_reply_{tid}")],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="menu_support")],
    ]) if status != "closed" else InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 К списку", callback_data="menu_support")
    ]])
    await callback.message.answer(text[:4000], parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("ticket_reply_"))
async def ticket_reply_start(callback: CallbackQuery, state: FSMContext):
    tid = int(callback.data.split("_")[2])
    await state.update_data(reply_ticket_id=tid)
    await callback.message.answer(f"📩 Напишите ответ в тикет #{tid}:")
    await state.set_state(SupportTicketState.reply)
    await callback.answer()


@router.message(SupportTicketState.reply)
async def ticket_reply_message(message: Message, state: FSMContext):
    data = await state.get_data()
    tid  = data["reply_ticket_id"]
    uid  = message.from_user.id
    text_body = message.text or message.caption or "[медиа]"
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT subject, username FROM support_tickets WHERE id=? AND user_id=?", (tid, uid))
        row = c.fetchone()
        if not row:
            await message.answer("❌ Тикет не найден.")
            await state.clear()
            return
        subj, uname = row
        conn.execute("INSERT INTO support_messages (ticket_id, sender, message) VALUES (?,?,?)",
                     (tid, "user", text_body))
        conn.execute("UPDATE support_tickets SET status='open', updated_at=datetime('now') WHERE id=?", (tid,))
        conn.commit()
    await message.answer(f"✅ Сообщение добавлено в тикет #{tid}.")
    await notify_staff(
        f"🔔 <b>Новое сообщение в тикет #{tid}</b>\nОт @{uname} ({uid})\n<b>{subj}</b>\n\n{text_body}\n\n/reply_{tid}",
        parse_mode="HTML"
    )
    await state.clear()


# ── Ответ от администратора ──────────────────────────────────────

@router.message(lambda m: is_staff(m.from_user.id) and m.text and m.text.startswith("/reply_"))
async def admin_reply_ticket(message: Message, state: FSMContext):
    parts = message.text.split(None, 1)
    try:
        tid = int(parts[0].replace("/reply_", ""))
    except ValueError:
        await message.answer("Формат: /reply_ID текст ответа")
        return
    reply_text = parts[1].strip() if len(parts) > 1 else None
    if not reply_text:
        # Ждём следующее сообщение
        await state.update_data(admin_reply_tid=tid)
        await message.answer(f"Введите ответ для тикета #{tid}:")
        await state.set_state(SupportTicketState.message)
        return
    await _send_admin_reply(tid, reply_text, message)


@router.message(Command("tickets"))
async def cmd_tickets(message: Message):
    """Список открытых тикетов для администратора/оператора."""
    if not is_staff(message.from_user.id):
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT id, user_id, username, subject, status, updated_at
                     FROM support_tickets WHERE status IN ('open','answered')
                     ORDER BY updated_at DESC LIMIT 20""")
        rows = c.fetchall()
    if not rows:
        await message.answer("✅ Нет открытых тикетов.")
        return
    text = "🎫 <b>Открытые тикеты:</b>\n\n"
    icons = {"open": "🟡", "answered": "🟢"}
    for tid, uid, uname, subj, status, upd in rows:
        text += (f"{icons.get(status,'⚪')} <b>#{tid}</b> @{uname or uid} "
                 f"— {subj or 'Без темы'}\n"
                 f"   {upd[:16]} · /reply_{tid}\n\n")
    await message.answer(text, parse_mode="HTML")


@router.message(Command("force_payout"))
async def cmd_force_payout(message: Message):
    """/force_payout ORDER_ID [TXID] — вручную отметить заявку как выполненную."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(None, 2)
    if len(parts) < 2:
        await message.answer(
            "Формат: /force_payout ORDER_ID\n"
            "или: /force_payout ORDER_ID TXID"
        )
        return
    try:
        oid = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ORDER_ID")
        return
    txid = parts[2].strip() if len(parts) > 2 else None

    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, rub_amount, currency, status FROM orders WHERE order_id=?", (oid,))
        row = c.fetchone()

    if not row:
        await message.answer(f"❌ Заявка #{oid} не найдена.")
        return
    user_id, rub, currency, status = row
    if status == "sent":
        await message.answer(f"⚠️ Заявка #{oid} уже в статусе «sent».")
        return

    with db_conn(5) as conn:
        if txid:
            conn.execute(
                "UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                (txid, oid)
            )
        else:
            conn.execute(
                "UPDATE orders SET status='sent', updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                (oid,)
            )
        conn.commit()

    amt_fmt = f"{int(rub):,}".replace(",", " ")
    CUR_ICON = {"BTC": "₿", "LTC": "Ł", "USDT": "💵"}
    await message.answer(
        f"✅ Заявка #{oid} отмечена как выполнена.\n"
        f"{amt_fmt} ₽ → {CUR_ICON.get(currency,'')} {currency}"
        + (f"\nTXID: <code>{txid}</code>" if txid else ""),
        parse_mode="HTML"
    )
    # Уведомляем клиента (status_notifier подхватит через pending-цикл,
    # но дублируем сразу чтобы не ждать 20 секунд)
    try:
        text = (
            f"🚀 <b>Заявка #{oid} выполнена!</b>\n\n"
            f"{amt_fmt} ₽ → {CUR_ICON.get(currency,'')} {currency} отправлен на ваш адрес."
        )
        if txid:
            text += f"\n\n🔗 TXID: <code>{txid}</code>"
        text += "\n\n<b>Оцените качество обслуживания:</b>"
        _rows = []
        _exp = explorer_url(currency, txid)
        if _exp:
            _rows.append([InlineKeyboardButton(text="🔍 Транзакция в блокчейне", url=_exp)])
        _rows.append([
            InlineKeyboardButton(text="😞 1", callback_data=f"rate_{oid}_1"),
            InlineKeyboardButton(text="😐 2", callback_data=f"rate_{oid}_2"),
            InlineKeyboardButton(text="🙂 3", callback_data=f"rate_{oid}_3"),
            InlineKeyboardButton(text="😊 4", callback_data=f"rate_{oid}_4"),
            InlineKeyboardButton(text="🤩 5", callback_data=f"rate_{oid}_5"),
        ])
        rate_kb = InlineKeyboardMarkup(inline_keyboard=_rows)
        await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=rate_kb)
    except Exception as e:
        await message.answer(f"⚠️ Не удалось уведомить клиента {user_id}: {e}")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """/broadcast текст — массовая рассылка всем активным пользователям."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer(
            "Формат: /broadcast текст сообщения\n\n"
            "Сообщение отправится всем пользователям с заявками за последние 30 дней.\n"
            "Поддерживает HTML: <b>жирный</b>, <i>курсив</i>, <code>код</code>",
            parse_mode="HTML"
        )
        return
    text = parts[1].strip()

    # Получаем уникальных активных пользователей
    with db_conn(10) as conn:
        c = conn.cursor()
        c.execute("""SELECT DISTINCT user_id FROM orders
                     WHERE user_id > 0
                       AND created_at >= datetime('now', '-30 days')
                     ORDER BY MAX(created_at) DESC""")
        users = [r[0] for r in c.fetchall()]

    if not users:
        await message.answer("Нет активных пользователей для рассылки.")
        return

    msg = await message.answer(
        f"📣 Начинаю рассылку для <b>{len(users)}</b> пользователей...",
        parse_mode="HTML"
    )
    ok = err = 0
    for uid in users:
        try:
            await bot.send_message(
                uid,
                f"📣 <b>ObsidianExchange</b>\n\n{text}",
                parse_mode="HTML"
            )
            ok += 1
        except Exception:
            err += 1
        await asyncio.sleep(0.05)  # 20 в секунду, Telegram лимит 30

    await msg.edit_text(
        f"📣 Рассылка завершена.\n✅ Доставлено: {ok} · ❌ Ошибок: {err}",
        parse_mode="HTML"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """/stats — быстрая сводка сегодня для администратора."""
    if not is_admin(message.from_user.id):
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        # Сегодня
        c.execute("""SELECT COUNT(*), COALESCE(SUM(rub_amount),0)
                     FROM orders WHERE date(created_at)=date('now')""")
        today_cnt, today_vol = c.fetchone()
        c.execute("""SELECT COUNT(*), COALESCE(SUM(rub_amount),0)
                     FROM orders WHERE status='sent' AND date(created_at)=date('now')""")
        today_done, today_done_vol = c.fetchone()
        # Ожидают
        c.execute("SELECT COUNT(*) FROM orders WHERE status='pending'")
        pend = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders WHERE status='paid'")
        paid_cnt = c.fetchone()[0]
        # Новые юзеры сегодня
        c.execute("""SELECT COUNT(*) FROM (
                         SELECT DISTINCT user_id FROM orders WHERE date(created_at)=date('now')
                         AND user_id NOT IN (
                             SELECT DISTINCT user_id FROM orders WHERE date(created_at)<date('now')
                         ))""")
        new_users = c.fetchone()[0]
        # Открытые тикеты
        c.execute("SELECT COUNT(*) FROM support_tickets WHERE status IN ('open','answered')")
        tickets = c.fetchone()[0]
        # Лимитные заявки
        c.execute("SELECT COUNT(*) FROM limit_orders WHERE status='active'")
        limit_orders = c.fetchone()[0]
        # DCA
        c.execute("SELECT COUNT(*) FROM dca_schedules WHERE status='active'")
        dca_cnt = c.fetchone()[0]

    vol_fmt = f"{int(today_vol):,}".replace(",", " ")
    done_vol_fmt = f"{int(today_done_vol):,}".replace(",", " ")
    text = (
        f"📊 <b>Статистика сегодня</b>\n\n"
        f"<blockquote>"
        f"📦 Всего заявок: {today_cnt} (объём {vol_fmt} ₽)\n"
        f"✅ Выполнено: {today_done} ({done_vol_fmt} ₽)\n"
        f"⏳ Ожидают оплаты: {pend}\n"
        f"🔄 Оплачено → в обработке: {paid_cnt}\n"
        f"👤 Новых клиентов: {new_users}"
        f"</blockquote>\n\n"
        f"<blockquote>"
        f"🎫 Открытых тикетов: {tickets}\n"
        f"⏳ Лимитных заявок: {limit_orders}\n"
        f"📅 Активных DCA: {dca_cnt}"
        f"</blockquote>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats_refresh")],
        [InlineKeyboardButton(text="📋 Ожидают выплаты", callback_data="admin_show_pending")],
        [InlineKeyboardButton(text="📊 Отчёт за день", callback_data="admin_report_today")],
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "admin_stats_refresh")
async def admin_stats_refresh(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.delete()
    # Сводка считается инлайн ниже (раньше здесь был битый вызов cmd_stats с
    # пустым Message — ломал refresh; убран)
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT COUNT(*), COALESCE(SUM(rub_amount),0)
                     FROM orders WHERE date(created_at)=date('now')""")
        today_cnt, today_vol = c.fetchone()
        c.execute("SELECT COUNT(*) FROM orders WHERE status='pending'")
        pend = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders WHERE status='paid'")
        paid_cnt = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM support_tickets WHERE status IN ('open','answered')")
        tickets = c.fetchone()[0]
    vol_fmt = f"{int(today_vol):,}".replace(",", " ")
    text = (
        f"📊 <b>Сводка (обновлено)</b>\n"
        f"Заявок сегодня: {today_cnt} · {vol_fmt} ₽\n"
        f"Ожидают: {pend} · Оплачено: {paid_cnt} · Тикеты: {tickets}"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_show_pending")
async def admin_show_pending_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await cmd_pending(callback.message, uid=callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "admin_report_today")
async def admin_report_today_cb(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    import datetime as _dt
    today = _dt.date.today().isoformat()
    report = await build_admin_report("сегодня", f"{today} 00:00", f"{today} 23:59")
    await callback.message.answer(report, parse_mode="HTML")
    await callback.answer()


async def _send_admin_reply(tid: int, reply_text: str, admin_message):
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, subject FROM support_tickets WHERE id=?", (tid,))
        row = c.fetchone()
        if not row:
            await admin_message.answer(f"❌ Тикет #{tid} не найден.")
            return
        user_id, subj = row
        conn.execute("INSERT INTO support_messages (ticket_id, sender, message) VALUES (?,?,?)",
                     (tid, "admin", reply_text))
        conn.execute("UPDATE support_tickets SET status='answered', updated_at=datetime('now') WHERE id=?", (tid,))
        conn.commit()
    try:
        await bot.send_message(
            user_id,
            f"💬 <b>Ответ по обращению #{tid}</b>\n<i>{subj}</i>\n\n{reply_text}\n\n"
            f"Посмотреть всю переписку: /support",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📩 Ответить", callback_data=f"ticket_reply_{tid}")
            ]])
        )
        await admin_message.answer(f"✅ Ответ отправлен клиенту (тикет #{tid})")
        log_staff_action(admin_message.from_user.id, "reply_ticket", tid)
    except Exception as e:
        await admin_message.answer(f"❌ Не удалось отправить: {e}")


# ══════════════════════════════════════════════════════════════════
# ИНСТРУМЕНТЫ АДМИНИСТРАТОРА
# ══════════════════════════════════════════════════════════════════

@router.message(Command("finduser"))
async def cmd_finduser(message: Message):
    """/finduser ID или /finduser @username — полная карточка клиента."""
    if not is_staff(message.from_user.id):
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer("Формат: /finduser 123456789 или /finduser @username")
        return
    query = parts[1].strip().lstrip("@")
    with db_conn(5) as conn:
        c = conn.cursor()
        if query.isdigit():
            c.execute("""SELECT user_id, username,
                                COUNT(*) as total,
                                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) as sent_cnt,
                                COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) as volume
                         FROM orders WHERE user_id=?""", (int(query),))
        else:
            c.execute("""SELECT user_id, username,
                                COUNT(*) as total,
                                SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) as sent_cnt,
                                COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) as volume
                         FROM orders WHERE username=?""", (query,))
        row = c.fetchone()

    if not row or not row[0]:
        await message.answer("❌ Пользователь не найден в базе заявок.")
        return

    uid, uname, total, sent_cnt, volume = row
    vip_name, disc = get_user_vip(uid)
    vip_icons = {'Platinum': '💎', 'Gold': '🥇', 'Silver': '🥈'}

    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (uid,))
        refs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM support_tickets WHERE user_id=? AND status='open'", (uid,))
        open_tickets = c.fetchone()[0]
        c.execute("SELECT id, status, rub_amount, currency, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 3", (uid,))
        last3 = c.fetchall()
        blocked = bool(conn.execute("SELECT 1 FROM blocked_users WHERE user_id=?", (uid,)).fetchone())

    vol_fmt = f"{int(volume):,}".replace(",", " ")
    text = (
        f"👤 <b>Клиент: @{uname or '—'}</b>\n"
        f"ID: <code>{uid}</code>"
        f"{' 🚫 ЗАБЛОКИРОВАН' if blocked else ''}\n\n"
        f"<blockquote>"
        f"📦 Заявок: {total} · Выполнено: {sent_cnt}\n"
        f"💰 Объём: {vol_fmt} ₽\n"
        f"{vip_icons.get(vip_name,'')} VIP: {vip_name or 'Standard'}"
        f"{f' (−{disc}%)' if disc else ''}\n"
        f"👥 Рефералов: {refs}\n"
        f"🎫 Открытых тикетов: {open_tickets}"
        f"</blockquote>\n\n"
        f"<b>Последние 3 заявки:</b>\n"
    )
    STATUS_ICON = {"pending": "⏳", "paid": "🔄", "sent": "✅", "failed": "❌", "cancelled": "🚫"}
    for oid, st, amt, cur, dt in last3:
        text += f"  {STATUS_ICON.get(st,'?')} #{oid} · {int(amt):,} ₽ → {cur} · {dt[:10]}\n".replace(",", " ")

    kb_rows = [[InlineKeyboardButton(text="✉️ Написать клиенту", callback_data=f"admin_msg_{uid}")]]
    if is_admin(message.from_user.id):
        # Блокировка — только админам
        kb_rows.append([InlineKeyboardButton(
            text="🚫 Заблокировать" if not blocked else "✅ Разблокировать",
            callback_data=f"admin_{'block' if not blocked else 'unblock'}_{uid}")])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@router.message(Command("pending"))
async def cmd_pending(message: Message, uid: int = None):
    """/pending — заявки которые оплачены но ещё не выплачены."""
    caller = uid or message.from_user.id
    if not is_staff(caller):
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT order_id, user_id, username, rub_amount, currency,
                            crypto_address, updated_at
                     FROM orders WHERE status='paid'
                     ORDER BY updated_at ASC LIMIT 15""")
        rows = c.fetchall()
    if not rows:
        await message.answer("✅ Нет оплаченных заявок, ожидающих выплаты.")
        return
    show_force = is_admin(caller)  # force_payout — только админам
    text = f"🔄 <b>Ожидают выплаты ({len(rows)}):</b>\n\n"
    for oid, uid, uname, amt, cur, addr, upd in rows:
        addr_s = f"{addr[:8]}…{addr[-4:]}" if addr else "—"
        text += (f"<b>#{oid}</b> @{uname or uid} · {int(amt):,} ₽ → {cur}\n"
                 f"  📬 <code>{addr_s}</code> · {upd[:16]}\n"
                 + (f"  /force_payout {oid}\n\n" if show_force else f"  /order {oid}\n\n")).replace(",", " ")
    await message.answer(text, parse_mode="HTML")


@router.message(Command("msg"))
async def cmd_msg(message: Message, state: FSMContext):
    """/msg USER_ID текст — отправить сообщение клиенту от имени бота."""
    if not is_staff(message.from_user.id):
        return
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        await message.answer("Формат: /msg USER_ID текст сообщения")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный USER_ID")
        return
    text = parts[2].strip()
    try:
        await bot.send_message(
            target_id,
            f"🟣 <b>Сообщение от ObsidianExchange</b>\n\n{text}",
            parse_mode="HTML"
        )
        await message.answer(f"✅ Отправлено пользователю {target_id}")
        log_staff_action(message.from_user.id, "msg_user", target_id, text[:200])
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.callback_query(F.data.startswith("admin_msg_"))
async def admin_msg_callback(callback: CallbackQuery, state: FSMContext):
    if not is_staff(callback.from_user.id):
        return
    target_id = int(callback.data.split("_")[2])
    await callback.message.answer(
        f"✉️ Чтобы написать клиенту, отправьте:\n<code>/msg {target_id} текст сообщения</code>",
        parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_block_"))
async def admin_block_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = int(callback.data.split("_")[2])
    with db_conn(5) as conn:
        conn.execute("INSERT OR IGNORE INTO blocked_users (user_id) VALUES (?)", (uid,))
        conn.commit()
    await callback.answer(f"🚫 Пользователь {uid} заблокирован.", show_alert=True)


@router.callback_query(F.data.startswith("admin_unblock_"))
async def admin_unblock_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    uid = int(callback.data.split("_")[2])
    with db_conn(5) as conn:
        conn.execute("DELETE FROM blocked_users WHERE user_id=?", (uid,))
        conn.commit()
    await callback.answer(f"✅ Пользователь {uid} разблокирован.", show_alert=True)


@router.message(Command("mystatus"))
async def cmd_mystatus(message: Message):
    """/mystatus ORDER_ID — статус конкретной заявки."""
    parts = message.text.split()
    uid = message.from_user.id
    if len(parts) < 2:
        # Показать последнюю заявку
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("""SELECT order_id FROM orders WHERE user_id=?
                         ORDER BY created_at DESC LIMIT 1""", (uid,))
            row = c.fetchone()
        if not row:
            await message.answer("У вас нет заявок. Начните обмен в меню.")
            return
        oid = row[0]
    else:
        try:
            oid = int(parts[1])
        except ValueError:
            await message.answer("Формат: /mystatus 1234")
            return

    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT order_id, user_id, rub_amount, currency, crypto_address,
                            status, created_at, paid_btc_tx
                     FROM orders WHERE order_id=?""", (oid,))
        row = c.fetchone()

    if not row or row[1] != uid:
        await message.answer("❌ Заявка не найдена.")
        return

    oid, _, rub, cur, addr, status, created, tx = row
    STATUS_ICON  = {"pending": "⏳", "paid": "🔄", "sent": "🚀", "failed": "❌", "cancelled": "🚫"}
    STATUS_LABEL = {"pending": "Ожидает оплаты", "paid": "Оплата подтверждена — обрабатываем",
                    "sent": "Выполнена ✅", "failed": "Ошибка", "cancelled": "Отменена"}
    CUR_ICON = {"BTC": "₿", "LTC": "Ł", "USDT": "💵"}

    text = (
        f"{STATUS_ICON.get(status,'❔')} <b>Заявка #{oid}</b>\n\n"
        f"Статус: <b>{STATUS_LABEL.get(status, status)}</b>\n"
        f"Сумма: <b>{int(rub):,} ₽</b> → {CUR_ICON.get(cur,'')} {cur}\n"
        f"Адрес: <code>{addr}</code>\n"
        f"Создана: {created[:16] if created else '—'}"
    ).replace(",", " ")
    if tx:
        text += f"\n🔗 TXID: <code>{tx}</code>"

    buttons = []
    if tx and len(tx) > 20:
        if cur == "BTC":
            url = f"https://mempool.space/tx/{tx}"
        elif cur == "LTC":
            url = f"https://blockchair.com/litecoin/transaction/{tx}"
        else:
            url = f"https://tronscan.org/#/transaction/{tx}"
        buttons.append(InlineKeyboardButton(text="🔍 Проверить в блокчейне", url=url))

    import datetime as _dt
    if status == "pending" and created:
        try:
            age = (_dt.datetime.utcnow() -
                   _dt.datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")).total_seconds()
            if age < 600:
                buttons.append(InlineKeyboardButton(
                    text="❌ Отменить заявку", callback_data=f"cancel_order_{oid}"
                ))
        except Exception:
            pass

    kb = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("myhistory"))
async def cmd_myhistory(message: Message):
    """Клиент получает CSV со всеми своими заявками."""
    uid = message.from_user.id
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT order_id, created_at, currency, rub_amount, status,
                            crypto_address, paid_btc_tx
                     FROM orders WHERE user_id=? ORDER BY order_id DESC""", (uid,))
        rows = c.fetchall()
    if not rows:
        await message.answer("У вас пока нет заявок.")
        return

    from io import StringIO
    import csv as _csv
    buf = StringIO()
    w = _csv.writer(buf)
    w.writerow(["#", "Дата", "Валюта", "Сумма RUB", "Статус", "Адрес", "TXID"])
    status_map = {"sent": "Выполнена", "paid": "Оплачена", "pending": "Ожидает",
                  "failed": "Ошибка", "cancelled": "Отменена"}
    for oid, dt, cur, amt, status, addr, tx in rows:
        w.writerow([oid, dt[:16] if dt else "", cur, f"{amt:.2f}",
                    status_map.get(status, status), addr or "", tx or ""])
    buf.seek(0)

    from aiogram.types import BufferedInputFile
    await message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8-sig"), filename=f"obsidian_history_{uid}.csv"),
        caption=f"📋 История ваших заявок — {len(rows)} шт.\nОткройте в Excel или Google Sheets."
    )


# ══════════════════════════════════════════════════════════════════
# DCA — АВТОПОКУПКА ПО РАСПИСАНИЮ
# Клиент настраивает: "покупай BTC на 3000 ₽ каждые 7 дней"
# ══════════════════════════════════════════════════════════════════

class DCAState(StatesGroup):
    currency  = State()
    amount    = State()
    interval  = State()
    address   = State()

_DCA_INTERVALS = {
    "3":  "Каждые 3 дня",
    "7":  "Каждую неделю",
    "14": "Раз в 2 недели",
    "30": "Раз в месяц",
}

@router.callback_query(F.data == "menu_dca")
async def menu_dca(callback: CallbackQuery, state: FSMContext):
    if is_user_blocked(callback.from_user.id):
        await callback.answer("⛔ Доступ ограничен.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₿ Bitcoin (BTC)",  callback_data="dca_cur_BTC")],
        [InlineKeyboardButton(text="Ł Litecoin (LTC)", callback_data="dca_cur_LTC")],
        [InlineKeyboardButton(text="💵 USDT (TRC20)",  callback_data="dca_cur_USDT")],
        [InlineKeyboardButton(text="📋 Мои DCA",       callback_data="dca_list")],
        [InlineKeyboardButton(text="🔙 Назад",         callback_data="back_to_menu")],
    ])
    await callback.message.answer(
        "📅 <b>DCA — автопокупка по расписанию</b>\n\n"
        "Настройте регулярную покупку крипты: бот будет автоматически "
        "создавать заявку по расписанию и присылать вам ссылку на оплату.\n\n"
        "Стратегия <b>DCA</b> (усреднение стоимости) снижает риски "
        "волатильности — вы покупаете по разным ценам и усредняете.\n\n"
        "Выберите валюту:",
        reply_markup=kb, parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("dca_cur_"))
async def dca_choose_currency(callback: CallbackQuery, state: FSMContext):
    cur = callback.data.split("_")[2]
    await state.update_data(dca_currency=cur)
    min_a = int(os.getenv('MIN_AMOUNT', 2000))
    await callback.message.answer(
        f"💰 Введите сумму в рублях для каждой покупки:\n"
        f"(минимум <b>{min_a:,} ₽</b>)\n\nПример: <code>3000</code>".replace(",", " "),
        parse_mode="HTML"
    )
    await state.set_state(DCAState.amount)
    await callback.answer()

@router.message(DCAState.amount)
async def dca_enter_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите число, например <code>3000</code>", parse_mode="HTML")
        return
    min_a = float(os.getenv('MIN_AMOUNT', 2000))
    max_a = float(os.getenv('MAX_AMOUNT', 500000))
    if amount < min_a or amount > max_a:
        await message.answer(f"❌ Сумма от {int(min_a):,} до {int(max_a):,} ₽".replace(",", " "))
        return
    await state.update_data(dca_amount=amount)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"dca_int_{days}")]
        for days, label in _DCA_INTERVALS.items()
    ])
    await message.answer("🗓 Как часто покупать?", reply_markup=kb)
    await state.set_state(DCAState.interval)

@router.callback_query(F.data.startswith("dca_int_"), DCAState.interval)
async def dca_choose_interval(callback: CallbackQuery, state: FSMContext):
    days = callback.data.split("_")[2]
    await state.update_data(dca_interval=int(days))
    data = await state.get_data()
    cur = data["dca_currency"]
    await callback.message.answer(
        f"📬 Введите ваш <b>{cur}-адрес</b> для получения криптовалюты:",
        parse_mode="HTML"
    )
    await state.set_state(DCAState.address)
    await callback.answer()

@router.message(DCAState.address)
async def dca_enter_address(message: Message, state: FSMContext):
    addr = message.text.strip()
    data = await state.get_data()
    cur = data["dca_currency"]
    if not validate_crypto_address(addr, cur):
        await message.answer(f"❌ Неверный {cur}-адрес. Проверьте и введите снова.")
        return
    await state.update_data(dca_address=addr)
    amount   = data["dca_amount"]
    interval = data["dca_interval"]
    interval_label = _DCA_INTERVALS.get(str(interval), f"каждые {interval} дней")
    commission = get_commission_percent(amount, message.from_user.id)
    rate = get_cached_rate(cur)
    net_rate = rate * (1 - commission / 100)
    approx = round(amount / net_rate, 8) if net_rate else 0
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Запустить DCA",  callback_data="dca_confirm")],
        [InlineKeyboardButton(text="❌ Отмена",         callback_data="back_to_menu")],
    ])
    await message.answer(
        f"📋 <b>Подтвердите DCA-расписание</b>\n\n"
        f"<blockquote>"
        f"Валюта: <b>{cur}</b>\n"
        f"Сумма каждой покупки: <b>{int(amount):,} ₽</b>\n"
        f"≈ получаете: <b>{approx:.6f} {cur}</b> (по текущему курсу)\n"
        f"Расписание: <b>{interval_label}</b>\n"
        f"Адрес: <code>{addr}</code>"
        f"</blockquote>\n\n"
        f"Первая покупка — сегодня. Бот пришлёт ссылку на оплату.".replace(",", " "),
        reply_markup=kb, parse_mode="HTML"
    )

@router.callback_query(F.data == "dca_confirm", DCAState.address)
async def dca_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uid  = callback.from_user.id
    import datetime as _dt
    next_run = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with db_conn(5) as conn:
        conn.execute("""INSERT INTO dca_schedules
            (user_id, currency, rub_amount, crypto_address, interval_days, next_run)
            VALUES (?,?,?,?,?,?)""",
            (uid, data["dca_currency"], data["dca_amount"],
             data["dca_address"], data["dca_interval"], next_run))
        conn.commit()
    await callback.message.answer(
        f"✅ <b>DCA запущен!</b>\n\n"
        f"Буду покупать <b>{data['dca_currency']}</b> на <b>{int(data['dca_amount']):,} ₽</b> "
        f"{_DCA_INTERVALS.get(str(data['dca_interval']), '')}.\n\n"
        f"Управление: /mydca".replace(",", " "),
        parse_mode="HTML"
    )
    await state.clear()
    await callback.answer()

@router.message(Command("mydca"))
@router.callback_query(F.data == "dca_list")
async def dca_list(update, state: FSMContext = None):
    msg = update if isinstance(update, Message) else update.message
    uid = update.from_user.id
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT id, currency, rub_amount, interval_days, next_run, runs_total, status
                     FROM dca_schedules WHERE user_id=? ORDER BY id DESC LIMIT 10""", (uid,))
        rows = c.fetchall()
    if not rows:
        await msg.answer("У вас нет активных DCA-расписаний.\n\nЗапустить: нажмите 📅 DCA в меню.")
        if isinstance(update, CallbackQuery): await update.answer()
        return
    text = "📅 <b>Ваши DCA-расписания:</b>\n\n"
    icons = {"active": "✅", "paused": "⏸", "cancelled": "❌"}
    for did, cur, amt, intv, next_r, runs, status in rows:
        text += (f"{icons.get(status,'?')} <b>#{did}</b> {cur} · {int(amt):,} ₽ "
                 f"· каждые {intv}д · выполнено {runs}х\n"
                 f"   Следующая: {next_r[:10]}\n\n").replace(",", " ")
    text += "Отменить: /canceldca ID"
    await msg.answer(text, parse_mode="HTML")
    if isinstance(update, CallbackQuery): await update.answer()

@router.message(Command("canceldca"))
async def dca_cancel(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /canceldca ID")
        return
    try:
        did = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID")
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM dca_schedules WHERE id=?", (did,))
        row = c.fetchone()
        if not row or row[0] != message.from_user.id:
            await message.answer("❌ Расписание не найдено или не ваше.")
            return
        conn.execute("UPDATE dca_schedules SET status='cancelled' WHERE id=?", (did,))
        conn.commit()
    await message.answer(f"✅ DCA-расписание #{did} отменено.")


async def dca_runner():
    """Фоновая задача: раз в час проверяет DCA-расписания и создаёт заявки."""
    import datetime as _dt
    while True:
        try:
            now_str = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("""SELECT id, user_id, currency, rub_amount, crypto_address, interval_days
                             FROM dca_schedules
                             WHERE status='active' AND next_run <= ?""", (now_str,))
                due = c.fetchall()

            for did, uid, cur, amt, addr, intv in due:
                try:
                    # Создаём заявку
                    with db_conn(5) as conn:
                        conn.execute(
                            "INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) "
                            "VALUES (?,?,?,?,?,'pending')",
                            (uid, f"dca_{did}", cur, amt, addr)
                        )
                        oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                        # Обновляем next_run
                        next_run = (_dt.datetime.utcnow() + _dt.timedelta(days=intv)).strftime("%Y-%m-%d %H:%M:%S")
                        conn.execute(
                            "UPDATE dca_schedules SET next_run=?, runs_total=runs_total+1 WHERE id=?",
                            (next_run, did)
                        )
                        conn.commit()

                    icons = {'BTC': '₿', 'LTC': 'Ł', 'USDT': '💵'}
                    commission = get_commission_percent(amt, uid)
                    rate = get_cached_rate(cur)
                    net_rate = rate * (1 - commission / 100)
                    approx = round(amt / net_rate, 8) if net_rate else 0
                    bot_username = os.getenv('BOT_USERNAME', 'Obsidian666999bot')
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="💳 Оплатить",
                            url=f"https://t.me/{bot_username}?start=pay_{oid}"
                        )
                    ]])
                    await bot.send_message(
                        uid,
                        f"📅 <b>DCA — время покупки!</b>\n\n"
                        f"Заявка <b>#{oid}</b>:\n"
                        f"{icons.get(cur,'')} {approx:.6f} {cur} за {int(amt):,} ₽\n\n"
                        f"Нажмите кнопку и оплатите — криптовалюта уйдёт на ваш адрес автоматически.".replace(",", " "),
                        reply_markup=kb, parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"dca_runner order error did={did}: {e}")

        except Exception as e:
            logger.error(f"dca_runner error: {e}")

        await asyncio.sleep(3600)


# ══════════════════════════════════════════════════════════════════
# КРИПТО-ПОДАРКИ
# Клиент оплачивает подарок → получает код → дарит другу
# Друг вводит код, указывает адрес → получает крипту
# ══════════════════════════════════════════════════════════════════

import secrets as _secrets

class GiftState(StatesGroup):
    currency = State()
    amount   = State()
    address  = State()   # адрес получателя при выкупе

def _make_gift_code() -> str:
    """6-символьный код подарка (только буквы+цифры без похожих символов)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(_secrets.choice(alphabet) for _ in range(6))

async def _generate_gift_card(currency: str, rub_amount: int, code: str) -> bytes | None:
    """Генерирует PNG-карточку подарка через PIL. Возвращает bytes или None."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io
        W, H = 800, 420
        BG   = (18, 10, 30)
        PURP = (138, 43, 226)
        GOLD = (255, 215, 0)
        img  = Image.new("RGB", (W, H), BG)
        d    = ImageDraw.Draw(img)
        # Рамка
        for i in range(3):
            d.rectangle([i, i, W-1-i, H-1-i], outline=PURP)
        # Заголовок
        try:
            fnt_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            fnt_med  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            fnt_code = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 52)
            fnt_sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        except Exception:
            fnt_big = fnt_med = fnt_code = fnt_sm = ImageFont.load_default()
        d.text((W//2, 50),  "🟣 ObsidianExchange", font=fnt_big, fill=PURP, anchor="mm")
        d.text((W//2, 105), "КРИПТО-ПОДАРОК",       font=fnt_med, fill=(220,200,255), anchor="mm")
        icons = {"BTC": "₿", "LTC": "Ł", "USDT": "💵"}
        label = f"{icons.get(currency,'')} {currency}  ·  {rub_amount:,} ₽".replace(",", " ")
        d.text((W//2, 185), label, font=fnt_med, fill=GOLD, anchor="mm")
        d.text((W//2, 265), code,  font=fnt_code, fill=(255,255,255), anchor="mm")
        d.text((W//2, 330), "Введи /redeem КОД в @Obsidian666999bot", font=fnt_sm, fill=(180,160,210), anchor="mm")
        d.text((W//2, 370), "obsidian-exchange.org", font=fnt_sm, fill=(120,100,160), anchor="mm")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"gift card generation failed: {e}")
        return None


@router.callback_query(F.data == "menu_gift")
async def menu_gift(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₿ Bitcoin (BTC)",  callback_data="gift_cur_BTC")],
        [InlineKeyboardButton(text="Ł Litecoin (LTC)", callback_data="gift_cur_LTC")],
        [InlineKeyboardButton(text="💵 USDT (TRC20)",  callback_data="gift_cur_USDT")],
        [InlineKeyboardButton(text="🔙 Назад",         callback_data="back_to_menu")],
    ])
    await callback.message.answer(
        "🎁 <b>Крипто-подарок</b>\n\n"
        "Сделайте подарок другу — оплатите криптовалюту, получите "
        "красивую карточку с кодом и отправьте её другу.\n\n"
        "Друг вводит код в боте, указывает свой адрес — "
        "и получает крипту прямо на кошелёк.\n\n"
        "Выберите валюту подарка:",
        reply_markup=kb, parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("gift_cur_"))
async def gift_choose_currency(callback: CallbackQuery, state: FSMContext):
    cur = callback.data.split("_")[2]
    await state.update_data(gift_currency=cur)
    min_a = int(os.getenv("MIN_AMOUNT", 2000))
    rate  = get_cached_rate(cur)
    commission = get_commission_percent(10000, callback.from_user.id)
    net_rate = rate * (1 - commission / 100)
    example_rub = 5000
    example_crypto = round(example_rub / net_rate, 6) if net_rate else 0
    await callback.message.answer(
        f"💰 Введите сумму подарка <b>в рублях</b>:\n"
        f"(минимум {min_a:,} ₽)\n\n"
        f"Пример: 5 000 ₽ ≈ {example_crypto} {cur}".replace(",", " "),
        parse_mode="HTML"
    )
    await state.set_state(GiftState.amount)
    await callback.answer()

@router.message(GiftState.amount)
async def gift_enter_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите число, например <code>3000</code>", parse_mode="HTML")
        return
    min_a = float(os.getenv("MIN_AMOUNT", 2000))
    max_a = float(os.getenv("MAX_AMOUNT", 500000))
    if amount < min_a or amount > max_a:
        await message.answer(f"❌ Сумма от {int(min_a):,} до {int(max_a):,} ₽".replace(",", " "))
        return
    data = await state.get_data()
    cur  = data["gift_currency"]
    commission = get_commission_percent(amount, message.from_user.id)
    rate = get_cached_rate(cur)
    net_rate = rate * (1 - commission / 100)
    approx = round(amount / net_rate, 8) if net_rate else 0
    # Генерируем уникальный код заранее
    code = _make_gift_code()
    while True:
        with db_conn(3) as conn:
            c = conn.cursor()
            c.execute("SELECT 1 FROM gift_vouchers WHERE code=?", (code,))
            if not c.fetchone():
                break
        code = _make_gift_code()
    await state.update_data(gift_amount=amount, gift_approx=approx, gift_code=code)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплатить подарок", callback_data="gift_pay")],
        [InlineKeyboardButton(text="❌ Отмена",           callback_data="back_to_menu")],
    ])
    await message.answer(
        f"🎁 <b>Подарок — {cur}</b>\n\n"
        f"<blockquote>"
        f"Сумма: <b>{int(amount):,} ₽</b>\n"
        f"Получатель получит: <b>≈ {approx:.6f} {cur}</b>\n"
        f"Код подарка: <b>{code}</b>"
        f"</blockquote>\n\n"
        f"После оплаты получите карточку с кодом для отправки другу.".replace(",", " "),
        reply_markup=kb, parse_mode="HTML"
    )

@router.callback_query(F.data == "gift_pay", GiftState.amount)
async def gift_pay(callback: CallbackQuery, state: FSMContext):
    data   = await state.get_data()
    uid    = callback.from_user.id
    cur    = data["gift_currency"]
    amount = data["gift_amount"]
    code   = data["gift_code"]
    # Создаём заявку — адрес-заглушка (заменится при выкупе)
    placeholder_addr = {"BTC": "1GiftPlaceholder1111111111111111111",
                        "LTC": "LGiftPlaceholder111111111111111111",
                        "USDT": "TGiftPlaceholderUSDT111111111111111"}.get(cur, "placeholder")
    with db_conn(5) as conn:
        conn.execute(
            "INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) "
            "VALUES (?,?,?,?,?,'pending')",
            (uid, f"gift_{code}", cur, amount, placeholder_addr)
        )
        oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO gift_vouchers (sender_id, currency, rub_amount, code, order_id) VALUES (?,?,?,?,?)",
            (uid, cur, amount, code, oid)
        )
        conn.commit()
    await state.update_data(order_id=oid, gift_order_id=oid)
    await state.set_state(Exchange.payment_method)
    # Показываем выбор способа оплаты как обычно
    commission = get_commission_percent(amount, uid)
    rate = get_cached_rate(cur)
    net_rate = rate * (1 - commission / 100)
    approx = round(amount / net_rate, 8) if net_rate else 0
    await callback.message.answer(
        f"🟣 Заявка <b>#{oid}</b> создана (подарок {code})\n\n"
        f"Сумма: <b>{int(amount):,} ₽</b> → ≈ {approx:.6f} {cur}\n\n"
        f"Выберите способ оплаты:".replace(",", " "),
        reply_markup=await build_payment_methods_kb(oid, amount),
        parse_mode="HTML"
    )
    await callback.answer()


async def _send_gift_card(sender_id: int, gift_id: int):
    """Отправляет карточку подарка отправителю после подтверждения оплаты."""
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT currency, rub_amount, code FROM gift_vouchers WHERE id=?", (gift_id,))
        row = c.fetchone()
    if not row:
        return
    cur, amt, code = row
    card_bytes = await _generate_gift_card(cur, int(amt), code)
    text = (
        f"🎁 <b>Ваш крипто-подарок готов!</b>\n\n"
        f"Код подарка: <code>{code}</code>\n\n"
        f"Отправьте другу это сообщение:\n\n"
        f"<blockquote>🟣 Тебе подарили {cur} на {int(amt):,} ₽!\n"
        f"Открой @Obsidian666999bot и введи команду:\n"
        f"/redeem {code}</blockquote>".replace(",", " ")
    )
    try:
        if card_bytes:
            from aiogram.types import BufferedInputFile
            await bot.send_photo(sender_id, BufferedInputFile(card_bytes, "gift.png"),
                                 caption=text, parse_mode="HTML")
        else:
            await bot.send_message(sender_id, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"_send_gift_card error: {e}")


@router.message(Command("redeem"))
async def cmd_redeem(message: Message, state: FSMContext):
    """Получатель вводит /redeem КОД."""
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Введите: <code>/redeem КОД</code>", parse_mode="HTML")
        return
    code = parts[1].strip().upper()
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT id, currency, rub_amount, status, sender_id FROM gift_vouchers WHERE code=?", (code,))
        row = c.fetchone()
    if not row:
        await message.answer("❌ Подарочный код не найден.")
        return
    gid, cur, amt, status, sender_id = row
    if status == "redeemed":
        await message.answer("❌ Этот подарок уже был получен.")
        return
    if status not in ("paid",):
        await message.answer("⏳ Подарок ещё не оплачен отправителем. Попробуйте позже.")
        return
    if message.from_user.id == sender_id:
        await message.answer("❌ Нельзя получить собственный подарок.")
        return
    commission = get_commission_percent(amt, message.from_user.id)
    rate = get_cached_rate(cur)
    net_rate = rate * (1 - commission / 100)
    approx = round(amt / net_rate, 8) if net_rate else 0
    await state.update_data(redeem_gift_id=gid, redeem_currency=cur,
                            redeem_amount=amt, redeem_approx=approx)
    await state.set_state(GiftState.address)
    icons = {"BTC": "₿", "LTC": "Ł", "USDT": "💵"}
    await message.answer(
        f"🎁 <b>Подарок найден!</b>\n\n"
        f"{icons.get(cur,'')} <b>{approx:.6f} {cur}</b> (~{int(amt):,} ₽)\n\n"
        f"Введите ваш <b>{cur}-адрес</b> для получения:".replace(",", " "),
        parse_mode="HTML"
    )

@router.message(GiftState.address)
async def gift_enter_recipient_address(message: Message, state: FSMContext):
    addr = message.text.strip()
    data = await state.get_data()
    cur  = data["redeem_currency"]
    gid  = data["redeem_gift_id"]
    amt  = data["redeem_amount"]
    if not validate_crypto_address(addr, cur):
        await message.answer(f"❌ Неверный {cur}-адрес. Проверьте и введите снова.")
        return
    uid = message.from_user.id
    # Создаём заявку для получателя
    with db_conn(5) as conn:
        conn.execute(
            "INSERT INTO orders (user_id, username, currency, rub_amount, crypto_address, status) "
            "VALUES (?,?,?,?,?,'paid')",
            (uid, f"gift_redeem_{gid}", cur, amt, addr)
        )
        oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "UPDATE gift_vouchers SET status='redeemed', recipient_id=?, recipient_address=?, claimed_at=datetime('now') WHERE id=?",
            (uid, addr, gid)
        )
        conn.commit()
    await message.answer(
        f"✅ <b>Подарок принят!</b>\n\n"
        f"Криптовалюта {cur} будет отправлена на ваш адрес в течение 15 минут.\n"
        f"Заявка #{oid}.",
        parse_mode="HTML"
    )
    await notify_workers_paid(oid, amt, addr, cur)
    await notify_admins(
        f"🎁 Подарочный код {data.get('redeem_gift_id')} выкуплен!\n"
        f"Получатель: {uid} · {cur} · {int(amt):,} ₽ · {addr}\n"
        f"Заявка #{oid}".replace(",", " "),
        parse_mode="HTML"
    )
    await state.clear()


# ══════════════════════════════════════════════════════════════════
# ГАРАНТИРОВАННЫЙ КУРС НА 15 МИНУТ
# Клиент фиксирует курс — платит 100 ₽ за блокировку.
# Если рынок улетел — его это не касается.
# ══════════════════════════════════════════════════════════════════

RATE_LOCK_FEE    = 100.0   # стоимость фиксации курса, руб
RATE_LOCK_MINS   = 15      # длительность фиксации

@router.callback_query(F.data == "menu_ratelock")
async def menu_ratelock(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₿ Зафиксировать BTC",  callback_data="ratelock_BTC")],
        [InlineKeyboardButton(text="Ł Зафиксировать LTC",  callback_data="ratelock_LTC")],
        [InlineKeyboardButton(text="💵 Зафиксировать USDT", callback_data="ratelock_USDT")],
        [InlineKeyboardButton(text="🔙 Назад",              callback_data="back_to_menu")],
    ])
    btc = get_cached_rate("BTC")
    ltc = get_cached_rate("LTC")
    usdt = get_cached_rate("USDT")
    await callback.message.answer(
        f"🔒 <b>Гарантированный курс</b>\n\n"
        f"Зафиксируйте текущий курс на <b>{RATE_LOCK_MINS} минут</b> — "
        f"даже если рынок улетит, ваш обмен пройдёт по зафиксированной цене.\n\n"
        f"<blockquote>"
        f"₿ BTC → {int(btc):,} ₽\n"
        f"Ł LTC → {int(ltc):,} ₽\n"
        f"💵 USDT → {usdt:.2f} ₽"
        f"</blockquote>\n\n"
        f"Стоимость фиксации: <b>{int(RATE_LOCK_FEE)} ₽</b> "
        f"(вычитается из суммы обмена)\n\n"
        f"Выберите валюту:".replace(",", " "),
        reply_markup=kb, parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("ratelock_"))
async def ratelock_choose(callback: CallbackQuery):
    cur  = callback.data.split("_")[1]
    uid  = callback.from_user.id
    rate = get_cached_rate(cur)
    import datetime as _dt
    until = (_dt.datetime.utcnow() + _dt.timedelta(minutes=RATE_LOCK_MINS)).strftime("%Y-%m-%d %H:%M:%S")
    with db_conn(5) as conn:
        # Деактивируем старые локи этого юзера по этой валюте
        conn.execute("UPDATE rate_locks SET used=1 WHERE user_id=? AND currency=? AND used=0", (uid, cur))
        conn.execute(
            "INSERT INTO rate_locks (user_id, currency, locked_rate, fee_rub, locked_until) VALUES (?,?,?,?,?)",
            (uid, cur, rate, RATE_LOCK_FEE, until)
        )
        conn.commit()
    await callback.message.answer(
        f"🔒 <b>Курс зафиксирован!</b>\n\n"
        f"{cur}: <b>{int(rate):,} ₽</b>\n"
        f"Действует до: <b>{until[11:16]} UTC</b> ({RATE_LOCK_MINS} мин)\n\n"
        f"Создайте заявку на обмен <b>прямо сейчас</b> — "
        f"курс будет применён автоматически.\n"
        f"Комиссия за фиксацию <b>{int(RATE_LOCK_FEE)} ₽</b> вычтется из суммы.".replace(",", " "),
        parse_mode="HTML"
    )
    await callback.answer()


def get_active_rate_lock(user_id: int, currency: str) -> dict | None:
    """Возвращает активную фиксацию курса или None."""
    import datetime as _dt
    now = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with db_conn(3) as conn:
        c = conn.cursor()
        c.execute("""SELECT id, locked_rate, fee_rub FROM rate_locks
                     WHERE user_id=? AND currency=? AND used=0 AND locked_until > ?
                     ORDER BY id DESC LIMIT 1""", (user_id, currency, now))
        row = c.fetchone()
    if row:
        return {"lock_id": row[0], "rate": row[1], "fee": row[2]}
    return None


# ---------- АДМИН-КОМАНДЫ УПРАВЛЕНИЯ ----------
@router.message(Command("setrate"))
async def cmd_setrate(message: Message):
    if not is_admin(message.from_user.id): return
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
    if not is_admin(message.from_user.id): return
    await message.answer(
        f"Текущие лимиты:\n"
        f"Мин: {MIN_AMOUNT:,.0f} RUB\n"
        f"Макс: {MAX_AMOUNT:,.0f} RUB\n"
        f"Крупная заявка: {HIGH_AMOUNT:,.0f} RUB\n"
        f"Комиссия: 27% (до 5000 RUB), 23% (5000-15000 RUB), 19% (от 15000 RUB) для BTC/LTC; 2% для USDT"
    )

# ОТКЛЁН дубликат: /stats обслуживает cmd_stats выше. Тело оставлено как легаси.
async def cmd_stats(message: Message):
    if not is_admin(message.from_user.id): return
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
async def build_admin_report(period_label: str, date_from: str, date_to: str) -> str:
    """Строит текст отчёта за указанный период (date_from/date_to — строки YYYY-MM-DD)."""
    with db_conn(10) as conn:
        c = conn.cursor()
        # Выполненные заявки
        c.execute("""SELECT COUNT(*), COALESCE(SUM(rub_amount),0)
                     FROM orders WHERE date(created_at) BETWEEN ? AND ? AND status='sent'""",
                  (date_from, date_to))
        cnt_sent, vol_sent = c.fetchone()
        # Все созданные
        c.execute("SELECT COUNT(*) FROM orders WHERE date(created_at) BETWEEN ? AND ?",
                  (date_from, date_to))
        cnt_all = c.fetchone()[0]
        # По валютам
        c.execute("""SELECT currency, COUNT(*), COALESCE(SUM(rub_amount),0)
                     FROM orders WHERE date(created_at) BETWEEN ? AND ? AND status='sent'
                     GROUP BY currency ORDER BY 3 DESC""",
                  (date_from, date_to))
        by_cur = c.fetchall()
        # Новые пользователи (первая заявка за период)
        c.execute("""SELECT COUNT(DISTINCT user_id) FROM orders
                     WHERE date(created_at) BETWEEN ? AND ?
                       AND user_id > 0
                       AND NOT EXISTS (
                           SELECT 1 FROM orders o2
                           WHERE o2.user_id = orders.user_id
                             AND date(o2.created_at) < ?
                       )""",
                  (date_from, date_to, date_from))
        new_users = c.fetchone()[0]
        # Средний чек
        avg_check = (vol_sent / cnt_sent) if cnt_sent else 0
        # Конверсия
        conv = (cnt_sent / cnt_all * 100) if cnt_all else 0
        # Реферальные бонусы выплачено
        c.execute("""SELECT COALESCE(SUM(bonus_amount),0) FROM referral_bonuses
                     WHERE date(created_at) BETWEEN ? AND ?""",
                  (date_from, date_to))
        ref_paid = c.fetchone()[0]

    vol_fmt = f"{int(vol_sent):,}".replace(",", " ")
    avg_fmt = f"{int(avg_check):,}".replace(",", " ")
    ref_fmt = f"{int(ref_paid):,}".replace(",", " ")

    lines = [f"📊 <b>Отчёт ObsidianExchange — {period_label}</b>\n"]
    lines.append(f"📦 Заявок создано: <b>{cnt_all}</b>")
    lines.append(f"✅ Выполнено: <b>{cnt_sent}</b> ({conv:.0f}%)")
    lines.append(f"💰 Объём: <b>{vol_fmt} ₽</b>")
    lines.append(f"📐 Средний чек: <b>{avg_fmt} ₽</b>")
    lines.append(f"👤 Новых клиентов: <b>{new_users}</b>")
    lines.append(f"🎁 Реф. бонусов выплачено: <b>{ref_fmt} ₽</b>")

    if by_cur:
        lines.append("\n<b>По валютам:</b>")
        icons = {'BTC': '₿', 'LTC': 'Ł', 'USDT': '💵'}
        for cur, c_cnt, c_vol in by_cur:
            lines.append(f"  {icons.get(cur, cur)} {cur}: {c_cnt} шт · {int(c_vol):,} ₽".replace(",", " "))

    return "\n".join(lines)


async def daily_report():
    """Отправляет ежедневный отчёт в 09:00 UTC (12:00 МСК)."""
    while True:
        import datetime as _dt
        now = _dt.datetime.utcnow()
        # Ждём 09:00 UTC
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target += _dt.timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

        yesterday = (_dt.datetime.utcnow() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        text = await build_admin_report(f"вчера ({yesterday})", yesterday, yesterday)
        try:
            await notify_admins( text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"daily_report send error: {e}")

async def check_stuck_orders():
    while True:
        with db_conn(10) as conn:
            c = conn.cursor()
            threshold = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT order_id FROM orders WHERE status='pending' AND created_at < ?", (threshold,))
            stuck = c.fetchall()
            if stuck:
                ids = ", ".join([str(row[0]) for row in stuck])
                await notify_admins( f"🕒 Зависшие заявки (>30 мин): {ids}")
        await asyncio.sleep(900)


# ══════════════════════════════════════════════════════════════════
# ЛИМИТНЫЕ ЗАЯВКИ — покупка крипты по целевому курсу
# Клиент задаёт курс и ждёт: бот сам создаёт заявку при достижении.
# Комиссия: +1% (LIMIT_COMMISSION_EXTRA) к стандартной.
# ══════════════════════════════════════════════════════════════════
LIMIT_COMMISSION_EXTRA = 1.0   # доп. % за лимитный ордер
LIMIT_ORDER_TTL_DAYS   = 7     # ордер истекает через 7 дней

_LIMIT_CURRENCIES = {
    "BTC":  ("₿ Bitcoin",   "BTC"),
    "LTC":  ("Ł Litecoin",  "LTC"),
    "USDT": ("💵 USDT TRC20","USDT"),
}

@router.callback_query(F.data == "menu_limit")
async def menu_limit(callback: CallbackQuery, state: FSMContext):
    if is_user_blocked(callback.from_user.id):
        await callback.answer("⛔ Доступ ограничен.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="₿ Bitcoin (BTC)",    callback_data="lo_cur_BTC")],
        [InlineKeyboardButton(text="Ł Litecoin (LTC)",   callback_data="lo_cur_LTC")],
        [InlineKeyboardButton(text="💵 USDT (TRC20)",    callback_data="lo_cur_USDT")],
        [InlineKeyboardButton(text="📋 Мои лимитки",     callback_data="lo_list")],
        [InlineKeyboardButton(text="🔙 Назад",           callback_data="back_to_menu")],
    ])
    await callback.message.answer(
        "⏳ <b>Лимитная заявка</b>\n\n"
        "Укажите курс и сумму — бот автоматически создаст заявку на покупку "
        "криптовалюты как только курс достигнет вашей цели.\n\n"
        "📌 Комиссия: стандартная <b>+1%</b>\n"
        "⏱ Ордер действует <b>7 дней</b>, затем отменяется.\n\n"
        "Выберите валюту:",
        reply_markup=kb, parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("lo_cur_"))
async def lo_choose_currency(callback: CallbackQuery, state: FSMContext):
    cur = callback.data.split("_")[2]
    if cur not in _LIMIT_CURRENCIES:
        await callback.answer("❌ Неверная валюта", show_alert=True)
        return
    await state.update_data(lo_currency=cur)
    rate = get_cached_rate(cur)
    rate_fmt = f"{int(rate):,}".replace(",", " ")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📉 Купить если НИЖЕ",  callback_data="lo_dir_below")],
        [InlineKeyboardButton(text="📈 Купить если ВЫШЕ",  callback_data="lo_dir_above")],
        [InlineKeyboardButton(text="🔙 Назад",             callback_data="menu_limit")],
    ])
    await callback.message.answer(
        f"⏳ <b>Лимитная заявка — {_LIMIT_CURRENCIES[cur][0]}</b>\n\n"
        f"Текущий курс: <b>{rate_fmt} ₽</b> за 1 {cur}\n\n"
        f"Что вы хотите сделать?",
        reply_markup=kb, parse_mode="HTML"
    )
    await state.set_state(LimitOrder.direction)
    await callback.answer()

@router.callback_query(F.data.startswith("lo_dir_"), LimitOrder.direction)
async def lo_choose_direction(callback: CallbackQuery, state: FSMContext):
    direction = callback.data.split("_")[2]
    await state.update_data(lo_direction=direction)
    data = await state.get_data()
    cur = data["lo_currency"]
    rate = get_cached_rate(cur)
    rate_fmt = f"{int(rate):,}".replace(",", " ")
    dir_label = "ниже" if direction == "below" else "выше"
    await callback.message.answer(
        f"💱 Укажите целевой курс {cur} в рублях\n"
        f"(сейчас: <b>{rate_fmt} ₽</b>)\n\n"
        f"Как только курс станет <b>{dir_label}</b> вашей цифры — "
        f"заявка будет создана автоматически.\n\n"
        f"Введите курс цифрой, например: <code>{int(rate * (0.97 if direction == 'below' else 1.03)):,}</code>".replace(",", " "),
        parse_mode="HTML"
    )
    await state.set_state(LimitOrder.rate)
    await callback.answer()

@router.message(LimitOrder.rate)
async def lo_enter_rate(message: Message, state: FSMContext):
    try:
        target_rate = float(message.text.replace(" ", "").replace(",", "."))
        if target_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число, например <code>5800000</code>", parse_mode="HTML")
        return
    data = await state.get_data()
    cur = data["lo_currency"]
    cur_rate = get_cached_rate(cur)
    direction = data["lo_direction"]
    # Предупреждаем если цель уже достигнута
    if direction == "below" and target_rate >= cur_rate:
        await message.answer(
            f"⚠️ Текущий курс <b>{int(cur_rate):,} ₽</b> уже ниже вашей цели.\n"
            f"Укажите курс <b>ниже</b> текущего или сделайте обычный обмен.".replace(",", " "),
            parse_mode="HTML"
        )
        return
    if direction == "above" and target_rate <= cur_rate:
        await message.answer(
            f"⚠️ Текущий курс <b>{int(cur_rate):,} ₽</b> уже выше вашей цели.\n"
            f"Укажите курс <b>выше</b> текущего или сделайте обычный обмен.".replace(",", " "),
            parse_mode="HTML"
        )
        return
    await state.update_data(lo_rate=target_rate)
    min_a = float(os.getenv('MIN_AMOUNT', 2000))
    max_a = float(os.getenv('MAX_AMOUNT', 500000))
    await message.answer(
        f"✅ Целевой курс: <b>{int(target_rate):,} ₽</b>\n\n"
        f"Введите сумму <b>в рублях</b>, которую вы готовы потратить:\n"
        f"Мин: <b>{int(min_a):,} ₽</b>  Макс: <b>{int(max_a):,} ₽</b>".replace(",", " "),
        parse_mode="HTML"
    )
    await state.set_state(LimitOrder.amount)

@router.message(LimitOrder.amount)
async def lo_enter_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(" ", "").replace(",", "."))
    except ValueError:
        await message.answer("❌ Введите число, например <code>5000</code>", parse_mode="HTML")
        return
    min_a = float(os.getenv('MIN_AMOUNT', 2000))
    max_a = float(os.getenv('MAX_AMOUNT', 500000))
    if amount < min_a or amount > max_a:
        await message.answer(f"❌ Сумма должна быть от {int(min_a):,} до {int(max_a):,} ₽".replace(",", " "))
        return
    data = await state.get_data()
    cur = data["lo_currency"]
    target_rate = data["lo_rate"]
    commission = get_commission_percent(amount, message.from_user.id) + LIMIT_COMMISSION_EXTRA
    net_rate = target_rate * (1 - commission / 100)
    crypto_amount = round(amount / net_rate, 8)
    await state.update_data(lo_amount=amount, lo_crypto_approx=crypto_amount, lo_commission=commission)
    await message.answer(
        f"💰 Сумма: <b>{int(amount):,} ₽</b>\n"
        f"≈ получите: <b>{crypto_amount:.6f} {cur}</b>\n"
        f"(по курсу {int(target_rate):,} ₽ − {commission:.1f}% комиссии)\n\n"
        f"Введите ваш <b>{cur}-адрес</b> для получения:".replace(",", " "),
        parse_mode="HTML"
    )
    await state.set_state(LimitOrder.address)

@router.message(LimitOrder.address)
async def lo_enter_address(message: Message, state: FSMContext):
    address = message.text.strip()
    data = await state.get_data()
    cur = data["lo_currency"]
    if not validate_crypto_address(address, cur):
        await message.answer(f"❌ Неверный {cur}-адрес. Проверьте и введите снова.")
        return
    await state.update_data(lo_address=address)
    data = await state.get_data()
    target_rate = data["lo_rate"]
    amount = data["lo_amount"]
    direction = data["lo_direction"]
    commission = data["lo_commission"]
    crypto_approx = data["lo_crypto_approx"]
    dir_label = "упадёт ниже" if direction == "below" else "вырастет выше"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать лимитный ордер", callback_data="lo_confirm")],
        [InlineKeyboardButton(text="❌ Отмена",                 callback_data="back_to_menu")],
    ])
    await message.answer(
        f"📋 <b>Подтвердите лимитный ордер</b>\n\n"
        f"<blockquote>"
        f"Валюта: <b>{cur}</b>\n"
        f"Триггер: курс {dir_label} <b>{int(target_rate):,} ₽</b>\n"
        f"Сумма: <b>{int(amount):,} ₽</b>\n"
        f"≈ получите: <b>{crypto_approx:.6f} {cur}</b>\n"
        f"Адрес: <code>{address}</code>\n"
        f"Комиссия: <b>{commission:.1f}%</b>\n"
        f"Срок: <b>7 дней</b>"
        f"</blockquote>\n\n"
        f"После создания бот будет следить за курсом и уведомит вас.".replace(",", " "),
        reply_markup=kb, parse_mode="HTML"
    )

@router.callback_query(F.data == "lo_confirm", LimitOrder.address)
async def lo_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    uid = callback.from_user.id
    import datetime as _dt
    expires = (_dt.datetime.utcnow() + _dt.timedelta(days=LIMIT_ORDER_TTL_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    with db_conn(5) as conn:
        conn.execute("""
            INSERT INTO limit_orders
              (user_id, currency, target_rate, direction, rub_amount, crypto_address, payment_method, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid, data["lo_currency"], data["lo_rate"], data["lo_direction"],
              data["lo_amount"], data["lo_address"], "sbp", expires))
        conn.commit()
    direction_text = "упадёт ниже" if data["lo_direction"] == "below" else "вырастет выше"
    await callback.message.answer(
        f"⏳ <b>Лимитный ордер создан!</b>\n\n"
        f"Слежу за курсом {data['lo_currency']}.\n"
        f"Как только курс {direction_text} <b>{int(data['lo_rate']):,} ₽</b> — "
        f"сразу уведомлю вас и создам заявку.\n\n"
        f"Управление: /limits".replace(",", " "),
        parse_mode="HTML"
    )
    await state.clear()
    await callback.answer()

# (снят дубль /limits — команду обслуживает cmd_limits выше; здесь только колбэк lo_list)
@router.callback_query(F.data == "lo_list")
async def lo_list(update, state: FSMContext = None):
    msg = update if isinstance(update, Message) else update.message
    uid = update.from_user.id
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT id, currency, direction, target_rate, rub_amount, status, expires_at
                     FROM limit_orders WHERE user_id=? AND status IN ('active','triggered')
                     ORDER BY id DESC LIMIT 10""", (uid,))
        rows = c.fetchall()
    if not rows:
        await msg.answer("У вас нет активных лимитных ордеров.\n\nСоздать: /limitbuy")
        if isinstance(update, CallbackQuery):
            await update.answer()
        return
    text = "📋 <b>Ваши лимитные ордера:</b>\n\n"
    dir_icons = {"below": "📉", "above": "📈"}
    status_icons = {"active": "⏳", "triggered": "🔔"}
    for lid, cur, direc, rate, amt, status, exp in rows:
        text += (f"{status_icons.get(status,'?')} <b>#{lid}</b> {dir_icons.get(direc,'')} "
                 f"{cur} @ {int(rate):,} ₽ · {int(amt):,} ₽\n"
                 f"   Статус: {status} · до {exp[:10]}\n\n").replace(",", " ")
    text += "Отменить: /cancelimit ID"
    await msg.answer(text, parse_mode="HTML")
    if isinstance(update, CallbackQuery):
        await update.answer()

@router.message(Command("cancelimit"))
async def lo_cancel(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /cancelimit ID")
        return
    try:
        lid = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID")
        return
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM limit_orders WHERE id=?", (lid,))
        row = c.fetchone()
        if not row or row[0] != message.from_user.id:
            await message.answer("❌ Ордер не найден или не ваш.")
            return
        conn.execute("UPDATE limit_orders SET status='cancelled' WHERE id=?", (lid,))
        conn.commit()
    await message.answer(f"✅ Лимитный ордер #{lid} отменён.")


async def limit_order_watcher():
    """Фоновая задача: проверяет курс каждые 5 минут, срабатывает при достижении цели."""
    import datetime as _dt
    while True:
        try:
            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("""SELECT id, user_id, currency, target_rate, direction,
                                    rub_amount, crypto_address
                             FROM limit_orders
                             WHERE status='active' AND expires_at > datetime('now')""")
                active = c.fetchall()

            for lid, uid, cur, target_rate, direction, rub_amount, address in active:
                current = get_cached_rate(cur)
                if current <= 0:
                    continue
                triggered = (direction == "below" and current <= target_rate) or \
                            (direction == "above" and current >= target_rate)
                if not triggered:
                    continue

                # Создаём обычную заявку
                commission = get_commission_percent(rub_amount, uid) + LIMIT_COMMISSION_EXTRA
                net_rate = current * (1 - commission / 100)
                crypto_amount = round(rub_amount / net_rate, 8)

                with db_conn(5) as conn:
                    conn.execute("""
                        INSERT INTO orders (user_id, currency, rub_amount, crypto_address, status, username)
                        VALUES (?, ?, ?, ?, 'pending', 'limit_order')
                    """, (uid, cur, rub_amount, address))
                    new_order_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        "UPDATE limit_orders SET status='triggered', triggered_at=datetime('now'), order_id=? WHERE id=?",
                        (new_order_id, lid)
                    )
                    conn.commit()

                dir_label = "упал ниже" if direction == "below" else "вырос выше"
                icons = {'BTC': '₿', 'LTC': 'Ł', 'USDT': '💵'}
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Оплатить заявку",
                                         url=f"https://t.me/{os.getenv('BOT_USERNAME', 'Obsidian666999bot')}?start=pay_{new_order_id}")]
                ])
                try:
                    await bot.send_message(
                        uid,
                        f"🎯 <b>Ваш курс достигнут!</b>\n\n"
                        f"Курс {cur} {dir_label} {int(target_rate):,} ₽\n"
                        f"Сейчас: <b>{int(current):,} ₽</b>\n\n"
                        f"Заявка <b>#{new_order_id}</b> создана:\n"
                        f"{icons.get(cur,'')}{crypto_amount:.6f} {cur} · {int(rub_amount):,} ₽\n\n"
                        f"⚡ Оплатите в течение <b>15 минут</b> — курс может измениться!".replace(",", " "),
                        reply_markup=kb, parse_mode="HTML"
                    )
                except Exception:
                    pass
                await notify_admins(
                    f"🎯 Лимитный ордер #{lid} сработал!\n"
                    f"Клиент {uid} · {cur} · {int(rub_amount):,} ₽\n"
                    f"Создана заявка #{new_order_id}".replace(",", " "),
                    parse_mode="HTML"
                )

            # Истёкшие — отменяем
            with db_conn(5) as conn:
                conn.execute("""
                    UPDATE limit_orders SET status='expired'
                    WHERE status='active' AND expires_at <= datetime('now')
                """)
                conn.commit()

        except Exception as e:
            logger.error(f"limit_order_watcher error: {e}")

        await asyncio.sleep(300)  # каждые 5 минут


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
                await notify_admins( "✅ Сайт снова доступен.")
            else:
                await notify_admins( f"❌ Сайт недоступен!")
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
            await notify_admins( f"⚠️ Осталось {free_gb:.1f} ГБ свободного места на диске!")
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
    """Авто-обработка оплаченных заявок.

    Безопасность: status='paid' выставляется ТОЛЬКО вебхуком от провайдера
    (с проверкой HMAC/токена). Клиент не может подделать этот статус.

    Логика:
    - Заявки <= AUTO_PAYOUT_LIMIT: пытаемся выплатить автоматически из горячего
      кошелька; при нехватке средств — немедленно уведомляем работников.
    - Заявки > AUTO_PAYOUT_LIMIT: всегда уходят в ручную обработку к работникам.
    - Каждая заявка обрабатывается только один раз (таблица sent_notifications).
    """
    while True:
        try:
            with db_conn(10) as conn:
                c = conn.cursor()
                # Берём только свежие 'paid' заявки (не старше 24 часов),
                # которые ещё не попали в обработку
                c.execute("""
                    SELECT o.order_id, o.user_id, o.rub_amount, o.crypto_address, o.currency
                    FROM orders o
                    WHERE o.status = 'paid'
                      AND o.updated_at >= datetime('now', '-24 hours')
                      AND NOT EXISTS (
                          SELECT 1 FROM sent_notifications sn
                          WHERE sn.order_id = o.order_id AND sn.event = 'payout_triggered'
                      )
                    ORDER BY o.created_at ASC
                    LIMIT 5
                """)
                paid_orders = c.fetchall()

            for order_id, user_id, rub_amount, address, currency in paid_orders:
                # Маркируем сразу — предотвращает двойную обработку
                with db_conn(5) as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO sent_notifications (order_id, event) VALUES (?, 'payout_triggered')",
                        (order_id,)
                    )
                    conn.commit()

                # Уведомляем клиента: начинаем обработку
                try:
                    cur_emoji = {'BTC': '₿', 'LTC': 'Ł', 'USDT': '💵 USDT'}.get(currency, currency)
                    await bot.send_message(
                        user_id,
                        f"🔄 <b>Заявка #{order_id}</b>\n\n"
                        f"Оплата подтверждена! Отправляем {cur_emoji} на ваш адрес.\n"
                        f"Обычно это занимает 5–15 минут.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

                if rub_amount <= AUTO_PAYOUT_LIMIT:
                    # Малая заявка — пробуем авто-выплату
                    try:
                        payout_id = await process_payout_async(order_id, rub_amount, address, currency)
                        if payout_id:
                            with db_conn(5) as conn:
                                conn.execute(
                                    "UPDATE orders SET status='sent', paid_btc_tx=?, updated_at=CURRENT_TIMESTAMP WHERE order_id=?",
                                    (payout_id, order_id)
                                )
                                conn.commit()
                            await notify_admins(
                                f"✅ <b>Авто-выплата #{order_id}</b>\n{rub_amount:,.0f} RUB → {currency}\n"
                                f"TXID: <code>{payout_id}</code>",
                                parse_mode="HTML"
                            )
                            await credit_referral_bonus(order_id, user_id, rub_amount)
                            await update_user_vip_volume(user_id, rub_amount)
                        else:
                            # Горячий кошелёк пуст — уходит к работникам
                            await notify_workers_paid(order_id, rub_amount, address, currency)
                    except Exception as e:
                        logger.error(f"Ошибка авто-выплаты #{order_id}: {e}")
                        await notify_workers_paid(order_id, rub_amount, address, currency)
                else:
                    # Крупная заявка — всегда вручную
                    await notify_workers_paid(order_id, rub_amount, address, currency)

        except Exception as e:
            logger.error(f"auto_check_payments error: {e}")

        await asyncio.sleep(15)


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
                            await send_sticker_safe(user_id, STICKER_SUCCESS)
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
                        await send_sticker_safe(user_id, STICKER_SUCCESS)
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
                await notify_admins( "❌ Бэкапы отсутствуют!")
                continue
            latest = max(files, key=os.path.getmtime)
            age_hours = (time.time() - os.path.getmtime(latest)) / 3600
            if age_hours > 2:
                await notify_admins( f"⚠️ Последний бэкап старше 2 часов ({age_hours:.1f} ч).")
            elif os.path.getsize(latest) < 1000:
                await notify_admins( "❌ Последний бэкап слишком маленький (возможно, повреждён).")
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
                    await notify_admins( f"⚠️ SSL-сертификат истекает через {days_left} дней!")
        except Exception as e:
            logger.error(f"Ошибка проверки SSL: {e}")
        await asyncio.sleep(86400)  # раз в сутки


# ОТКЛЁН дубликат: /broadcast обслуживает cmd_broadcast (FSM) выше.
async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id): return
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
    if not is_admin(message.from_user.id): return
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
                await send_sticker_safe(user_id[0], STICKER_SUCCESS)
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


# (снят дубль /history — команду обслуживает простая cmd_history выше; эта
# пагинированная версия остаётся для колбэка hist_ пагинации)
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


# ОТКЛЁН дубликат: /order обслуживает cmd_order_card выше (карточка для операторов).
async def cmd_order(message: Message):
    if not is_admin(message.from_user.id):
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

def explorer_url(currency, tx):
    """Ссылка на транзакцию в блокчейн-эксплорере по валюте."""
    if not tx:
        return None
    return {
        'BTC': f"https://mempool.space/tx/{tx}",
        'LTC': f"https://blockchair.com/litecoin/transaction/{tx}",
        'USDT': f"https://tronscan.org/#/transaction/{tx}",
    }.get((currency or 'BTC').upper())

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
        _addr_mask = f"{client_address[:6]}…{client_address[-4:]}" if client_address and len(client_address) > 12 else "***"
        logger.info(f"Выплата #{order_id} выполнена: {amount} {currency} -> {_addr_mask}, txid={txid}")
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
        await notify_admins(
            f"💸 Выплата реф. бонуса пользователю {user_id}: {total:.8f} BTC\nTXID: <code>{txid}</code>",
            parse_mode="HTML")
    except Exception:
        pass
    return f"✅ Бонус выведен!\nСумма: {total:.8f} BTC\nTXID: <code>{txid}</code>"


async def balance_monitor():
    """Проверяет баланс USDT раз в 6 часов. BTC/LTC теперь в smart_monitor."""
    while True:
        await asyncio.sleep(6 * 3600)
        if not os.getenv('USDT_PRIVATE_KEY'):
            continue
        try:
            client = Tron()
            priv_key = PrivateKey(bytes.fromhex(os.getenv('USDT_PRIVATE_KEY')))
            addr = priv_key.public_key.to_base58check_address()
            contract = client.get_contract('TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t')
            usdt_balance = contract.functions.balanceOf(addr) / 1e6
            if usdt_balance < 10 and not _alert_active("usdt_low"):
                await notify_admins(
                    f"🔴 <b>Низкий баланс USDT</b>: {usdt_balance:.2f} USDT\n"
                    f"Пополните горячий кошелёк.", parse_mode="HTML")
                _set_alert("usdt_low", True)
            elif usdt_balance >= 10:
                _set_alert("usdt_low", False)
        except Exception as e:
            logger.error(f"Ошибка проверки баланса USDT: {e}")


@router.message(Command("testpost"))
async def cmd_testpost(message: Message):
    """Отправляет тестовый ежедневный пост только себе (только для админа)."""
    if not is_admin(message.from_user.id):
        return
    await message.answer("⏳ Отправляю тестовый пост...")
    await send_daily_post(target_id=message.from_user.id)
    await message.answer("✅ Готово! Для запуска рассылки всем: /broadcast")


# ОТКЛЁН дубликат: /broadcast обслуживает cmd_broadcast (FSM) выше.
async def cmd_broadcast(message: Message):
    """Запускает немедленную рассылку всем пользователям (только для админа)."""
    if not is_admin(message.from_user.id):
        return
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM bot_users WHERE broadcast_enabled=1")
            count = c.fetchone()[0]
    except Exception:
        count = 0
    await message.answer(f"🚀 Запускаю рассылку {count} пользователям...")
    asyncio.create_task(send_daily_post())


@router.message(Command("getfileid"))
async def cmd_getfileid(message: Message):
    """Возвращает file_id GIF/стикера/фото для использования в DAILY_POST_GIF."""
    if not is_admin(message.from_user.id):
        return
    if message.animation:
        await message.reply(f"🎞 GIF file_id:\n<code>{message.animation.file_id}</code>", parse_mode="HTML")
    elif message.sticker:
        await message.reply(f"🎯 Sticker file_id:\n<code>{message.sticker.file_id}</code>", parse_mode="HTML")
    elif message.photo:
        await message.reply(f"🖼 Photo file_id:\n<code>{message.photo[-1].file_id}</code>", parse_mode="HTML")
    elif message.video:
        await message.reply(f"🎬 Video file_id:\n<code>{message.video.file_id}</code>", parse_mode="HTML")
    else:
        await message.reply("Отправь GIF/фото/стикер с командой /getfileid в подписи.")


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    """Показывает текущие балансы и адреса горячих кошельков (BTC/LTC/USDT)."""
    if not is_admin(message.from_user.id):
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
    if not is_admin(message.from_user.id):
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
# Состояние алертов хранится в Redis (db=1) чтобы пережить перезапуски.
# Ключи: monitor:alert:{name} = "1" (алерт активен) или "0" (ок)
_monitor_redis = None
try:
    import redis as _redis_mod
    _monitor_redis = _redis_mod.Redis(host='localhost', port=6379, db=1, decode_responses=True)
except Exception:
    pass

def _alert_active(key: str) -> bool:
    if _monitor_redis:
        return _monitor_redis.get(f"monitor:alert:{key}") == "1"
    return False

def _set_alert(key: str, active: bool):
    if _monitor_redis:
        _monitor_redis.set(f"monitor:alert:{key}", "1" if active else "0", ex=86400)

async def smart_monitor():
    # Разные интервалы для разных проверок
    _iter = 0
    while True:
        _iter += 1
        try:
            # ── Relay (каждые 2 мин) ──────────────────────────────────────────
            try:
                r = requests.get("http://127.0.0.1:5001/", timeout=5)
                relay_ok = r.status_code < 500
            except Exception:
                relay_ok = False
            was_down = _alert_active("relay_down")
            if not relay_ok and not was_down:
                await notify_admins( "❌ <b>Relay недоступен!</b> Проверьте сервис relay-fastapi.", parse_mode="HTML")
                _set_alert("relay_down", True)
            elif relay_ok and was_down:
                await notify_admins( "✅ Relay снова доступен.")
                _set_alert("relay_down", False)

            # ── Провайдеры (раз в 15 мин = каждые 7 итераций по 2 мин) ──────
            if _iter % 7 == 0:
                providers_to_check = [
                    ("Платёжный шлюз 1", "https://montera.one/api/health",   "p1"),
                    ("Платёжный шлюз 2", "https://greenpay.win/",             "p2"),
                    ("Платёжный шлюз 3", os.getenv('BRABUS_BASE_URL', 'https://api.brabus.work') + "/", "p3"),
                ]
                for pname, purl, pkey in providers_to_check:
                    try:
                        rp = requests.get(purl, timeout=8)
                        is_up = rp.status_code < 500
                    except Exception:
                        is_up = False
                    was_p_down = _alert_active(f"provider_{pkey}")
                    if not is_up and not was_p_down:
                        await notify_admins(
                            f"⚠️ <b>{pname}</b> недоступен — резервный маршрут активен.",
                            parse_mode="HTML")
                        _set_alert(f"provider_{pkey}", True)
                    elif is_up and was_p_down:
                        await notify_admins( f"✅ <b>{pname}</b> снова работает.", parse_mode="HTML")
                        _set_alert(f"provider_{pkey}", False)

            # ── Балансы кошельков (раз в час = каждые 30 итераций) ───────────
            if _iter % 30 == 0:
                # BTC
                try:
                    wallet = Wallet('PayoutWallet')
                    wallet.scan()
                    btc_bal = wallet.balance(network='bitcoin')
                    if btc_bal < 10000 and not _alert_active("btc_low"):
                        await notify_admins(
                            f"🔴 <b>Низкий баланс BTC</b>: {btc_bal} сат\n"
                            f"Пополните горячий кошелёк.", parse_mode="HTML")
                        _set_alert("btc_low", True)
                    elif btc_bal >= 10000:
                        _set_alert("btc_low", False)
                except Exception:
                    pass  # кошелёк пустой или недоступен — не шумим

                # LTC
                try:
                    ltc_wallet = Wallet('PayoutLTC')
                    ltc_wallet.scan()
                    ltc_bal = ltc_wallet.balance(network='litecoin')
                    if ltc_bal < 500000 and not _alert_active("ltc_low"):
                        await notify_admins(
                            f"🔴 <b>Низкий баланс LTC</b>: {ltc_bal} сат\n"
                            f"Пополните горячий кошелёк.", parse_mode="HTML")
                        _set_alert("ltc_low", True)
                    elif ltc_bal >= 500000:
                        _set_alert("ltc_low", False)
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Ошибка в smart_monitor: {e}")

        await asyncio.sleep(120)  # базовый тик 2 минуты


# ========== СКИДКА ЗА КАЖДЫЙ 5-Й ОБМЕН ==========

def check_fifth_exchange_discount(user_id: int, rub_amount: float) -> bool:
    """Возвращает True если следующий обмен будет 5-м (или кратным 5) от 5000+ RUB."""
    if rub_amount < 5000:
        return False
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id=? AND status='completed' AND rub_amount >= 5000",
                (user_id,)
            )
            count = c.fetchone()[0]
        return count > 0 and (count % 5 == 4)
    except Exception:
        return False


# ========== ЕЖЕДНЕВНЫЙ ПОСТ В КАНАЛ ==========

async def compose_daily_post() -> str:
    btc_rate  = get_cached_rate('BTC')  or 0
    ltc_rate  = get_cached_rate('LTC')  or 0
    usdt_rate = get_cached_rate('USDT') or 0

    def fmt(val):
        return f"{int(val):,}".replace(",", " ") if val else "—"

    btc_buy  = int(round(btc_rate  / (1 - 0.27))) if btc_rate  else 0
    ltc_buy  = int(round(ltc_rate  / (1 - 0.27))) if ltc_rate  else 0
    usdt_buy = round(usdt_rate / (1 - 0.02), 2)   if usdt_rate else 0

    text = (
        f"🟣 <b>ObsidianExchange</b> — обмен RUB ⇄ крипта за 15 минут\n"
        f"Без верификации · всё делает бот · 24/7\n\n"

        f"💱 <b>Курсы прямо сейчас:</b>\n"
        f"<blockquote>"
        f"₿ BTC — от <b>{fmt(btc_buy)} ₽</b>\n"
        f"Ł LTC — от <b>{fmt(ltc_buy)} ₽</b>\n"
        f"₮ USDT TRC-20 — от <b>{usdt_buy:.2f} ₽</b>"
        f"</blockquote>\n\n"

        f"⚡️ <b>Как это работает:</b>\n"
        f"<blockquote expandable>"
        f"1. Выбираешь валюту и сумму (от 2 000 ₽)\n"
        f"2. Платишь по СБП или картой — Альфа, Т-Банк, VietQR\n"
        f"3. Крипта уходит на твой адрес сразу после оплаты\n\n"
        f"А ещё: своп BTC ⇄ LTC ⇄ USDT без регистрации,\n"
        f"лимитные заявки, DCA-автопокупка, фиксация курса"
        f"</blockquote>\n\n"

        f"📈 <b>Комиссия BTC / LTC:</b>\n"
        f"<blockquote>"
        f"2–5к → <b>27%</b> · 5–10к → <b>25%</b> · 10–20к → <b>23%</b> · 20к+ → <b>19%</b>\n"
        f"USDT TRC-20 → <b>2%</b>"
        f"</blockquote>\n\n"

        f"💎 VIP-скидки до <b>−10%</b> · 🎁 рефералка <b>10%</b> с нашей комиссии\n"
        f"🔥 Каждый 5-й обмен от 5 000 ₽ — минус <b>1 000 ₽</b> автоматически"
    )
    return text


async def _send_post_to(uid: int, text: str):
    """Отправляет пост: видеобаннер + текст caption + кнопки — одно сообщение."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Начать обмен", url="https://t.me/Obsidian666999bot"),
         InlineKeyboardButton(text="🌐 Личный кабинет", url=f"{PUBLIC_RELAY}/webapp")]
    ])
    if POST_HEADER_FILE_ID:
        await bot.send_animation(chat_id=uid, animation=POST_HEADER_FILE_ID,
                                 caption=text, parse_mode="HTML", reply_markup=kb)
    elif DAILY_POST_GIF:
        await bot.send_animation(chat_id=uid, animation=DAILY_POST_GIF,
                                 caption=text, parse_mode="HTML", reply_markup=kb)
    else:
        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)


async def compose_announce_text() -> str:
    """Текст разового объявления о возобновлении работы."""
    btc_rate  = get_cached_rate('BTC')  or 0
    ltc_rate  = get_cached_rate('LTC')  or 0
    usdt_rate = get_cached_rate('USDT') or 0

    def fmt(val):
        return f"{int(val):,}".replace(",", " ") if val else "—"

    btc_buy  = int(round(btc_rate  / (1 - 0.27))) if btc_rate  else 0
    ltc_buy  = int(round(ltc_rate  / (1 - 0.27))) if ltc_rate  else 0
    usdt_buy = round(usdt_rate / (1 - 0.02), 2)   if usdt_rate else 0

    return (
        f"🟣 <b>ObsidianExchange</b>\n\n"
        f"✅ <b>Технические работы завершены!</b>\n\n"
        f"Мы вернулись и готовы принимать новые заявки прямо сейчас.\n\n"
        f"💼 <b>Резервы пополнены до 500 000 ₽</b> на все направления:\n"
        f"<blockquote>"
        f"₿  BTC · Ł LTC · 💵 USDT TRC20"
        f"</blockquote>\n\n"
        f"📊 <b>Актуальные курсы:</b>\n"
        f"<blockquote>"
        f"₿  BTC  — от <b>{fmt(btc_buy)} ₽</b>\n"
        f"Ł  LTC  — от <b>{fmt(ltc_buy)} ₽</b>\n"
        f"💵 USDT — от <b>{usdt_buy:.2f} ₽</b>"
        f"</blockquote>\n\n"
        f"🔒 Non-KYC · Без верификации · Мин. 2 000 ₽\n\n"
        f"👉 Нажмите <b>«Обменять»</b> — бот ответит мгновенно!"
    )


async def send_announce(target_id: int = None):
    """Рассылает разовое объявление всем пользователям (или одному target_id для теста)."""
    text = await compose_announce_text()

    if target_id:
        try:
            await bot.send_message(target_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Ошибка тестовой отправки объявления: {e}")
        return

    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM bot_users WHERE broadcast_enabled=1")
            user_ids = [row[0] for row in c.fetchall()]
    except Exception as e:
        logger.error(f"Не удалось получить список пользователей для объявления: {e}")
        return

    sent = 0
    failed = 0
    blocked = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err or "deactivated" in err or "forbidden" in err or "not found" in err:
                blocked += 1
                try:
                    with db_conn(5) as conn:
                        conn.execute("UPDATE bot_users SET broadcast_enabled=0 WHERE user_id=?", (uid,))
                        conn.commit()
                except Exception:
                    pass
            else:
                failed += 1
                logger.warning(f"Не удалось отправить объявление пользователю {uid}: {e}")
        await asyncio.sleep(0.05)

    logger.info(f"Объявление разослано: отправлено {sent}, заблокировали {blocked}, ошибок {failed}")
    try:
        await notify_admins(
            f"📣 Рассылка объявления завершена:\n"
            f"✅ Доставлено: {sent}\n"
            f"🚫 Заблокировали бота: {blocked}\n"
            f"❌ Ошибок: {failed}"
        )
    except Exception:
        pass


@router.message(Command("testannounce"))
async def cmd_testannounce(message: Message):
    """Отправляет тестовое объявление только себе (только для админа)."""
    if not is_admin(message.from_user.id):
        return
    await message.answer("⏳ Отправляю тестовое объявление...")
    await send_announce(target_id=message.from_user.id)
    await message.answer("✅ Готово! Если всё ок — запусти /announce для рассылки всем.")


@router.message(Command("announce"))
async def cmd_announce(message: Message):
    """Рассылает разовое объявление всем пользователям (только для админа)."""
    if not is_admin(message.from_user.id):
        return
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM bot_users WHERE broadcast_enabled=1")
            count = c.fetchone()[0]
    except Exception:
        count = 0
    await message.answer(f"📣 Запускаю рассылку объявления {count} пользователям...")
    asyncio.create_task(send_announce())


async def send_daily_post(target_id: int = None):
    """Рассылает ежедневный пост всем пользователям бота (или одному target_id для теста)."""
    text = await compose_daily_post()

    if target_id:
        try:
            await _send_post_to(target_id, text)
        except Exception as e:
            logger.error(f"Ошибка тестовой отправки поста: {e}")
        return

    # Массовая рассылка
    try:
        with db_conn(5) as conn:
            c = conn.cursor()
            c.execute("SELECT user_id FROM bot_users WHERE broadcast_enabled=1")
            user_ids = [row[0] for row in c.fetchall()]
    except Exception as e:
        logger.error(f"Не удалось получить список пользователей для рассылки: {e}")
        return

    sent = 0
    failed = 0
    blocked = 0
    for uid in user_ids:
        try:
            await _send_post_to(uid, text)
            sent += 1
        except Exception as e:
            err = str(e).lower()
            if "blocked" in err or "deactivated" in err or "forbidden" in err or "not found" in err:
                blocked += 1
                try:
                    with db_conn(5) as conn:
                        conn.execute("UPDATE bot_users SET broadcast_enabled=0 WHERE user_id=?", (uid,))
                        conn.commit()
                except Exception:
                    pass
            else:
                failed += 1
                logger.warning(f"Не удалось отправить пост пользователю {uid}: {e}")
        await asyncio.sleep(0.05)  # 20 сообщений/сек — в рамках лимитов Telegram

    logger.info(f"Рассылка завершена: отправлено {sent}, заблокировали бота {blocked}, ошибок {failed}")
    try:
        await notify_admins(
            f"📊 Ежедневная рассылка завершена:\n"
            f"✅ Доставлено: {sent}\n"
            f"🚫 Заблокировали бота: {blocked}\n"
            f"❌ Ошибок: {failed}"
        )
    except Exception:
        pass


_RATE_TIPS = [
    "💡 <b>VIP-статус</b> даёт скидку до 10% — накапливается автоматически от суммы всех обменов.",
    "🔄 <b>Своп</b> BTC ↔ LTC ↔ USDT без регистрации и верификации — комиссия всего ~1%.",
    "🎁 <b>Реферальная программа:</b> приглашай друзей и получай 10% от нашей комиссии в BTC навсегда.",
    "🔒 <b>Non-KYC:</b> мы не запрашиваем документы. Никогда. Это принцип, а не временная акция.",
    "⚡ <b>Скорость:</b> среднее время обработки заявки — 5–15 минут в рабочее время.",
    "💰 <b>Продажа крипты:</b> принимаем BTC, LTC, USDT TRC20 → выплата рублями на СБП.",
    "⭐ <b>Каждый 5-й обмен</b> от 5 000 ₽ — автоматическая скидка 1 000 ₽.",
]
_rate_tip_index = 0


async def rate_alert_scheduler():
    """Умные уведомления об изменении курса — не чаще раза в сутки, только при движении >5%."""
    global _rate_tip_index
    CHANGE_THRESHOLD = 0.05   # 5% изменение = повод уведомить
    MIN_INTERVAL    = 86400   # минимум 24 часа между уведомлениями одному пользователю
    CHECK_EVERY     = 1800    # проверяем каждые 30 минут

    await asyncio.sleep(120)  # дать боту полностью запуститься

    while True:
        try:
            btc  = get_cached_rate('BTC')  or 0
            ltc  = get_cached_rate('LTC')  or 0
            usdt = get_cached_rate('USDT') or 0
            now  = time.time()

            if not btc:
                await asyncio.sleep(CHECK_EVERY)
                continue

            def fmt(v, d=0):
                return f"{v:,.{d}f}".replace(',', ' ') if v else '—'

            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT rs.user_id, rs.last_notified, rs.last_btc, rs.last_ltc, rs.last_usdt
                    FROM rate_subscriptions rs
                    WHERE rs.enabled = 1
                """)
                subscribers = c.fetchall()

            for uid, last_notified, last_btc, last_ltc, last_usdt in subscribers:
                # Пропускаем если уведомляли менее 24 часов назад
                if now - last_notified < MIN_INTERVAL:
                    continue

                # Считаем изменение курса с момента последнего уведомления
                btc_change  = abs(btc  - last_btc)  / last_btc  if last_btc  else 1
                ltc_change  = abs(ltc  - last_ltc)  / last_ltc  if last_ltc  else 1
                usdt_change = abs(usdt - last_usdt) / last_usdt if last_usdt else 1

                significant = (btc_change >= CHANGE_THRESHOLD or
                               ltc_change >= CHANGE_THRESHOLD or
                               usdt_change >= CHANGE_THRESHOLD)

                # Если прошло больше 48 часов — всё равно шлём (но не слишком часто)
                overdue = last_notified > 0 and (now - last_notified > 172800)

                if not significant and not overdue:
                    continue

                # Формируем стрелку тренда
                def trend(cur, prev):
                    if not prev:
                        return ''
                    return ' 📈' if cur > prev else ' 📉'

                tip = _RATE_TIPS[_rate_tip_index % len(_RATE_TIPS)]
                _rate_tip_index += 1

                text = (
                    f"📊 <b>Курс криптовалют сейчас</b>\n\n"
                    f"<blockquote>"
                    f"₿  BTC  — <b>{fmt(btc)} ₽</b>{trend(btc, last_btc)}\n"
                    f"Ł  LTC  — <b>{fmt(ltc)} ₽</b>{trend(ltc, last_ltc)}\n"
                    f"💵 USDT — <b>{fmt(usdt, 2)} ₽</b>{trend(usdt, last_usdt)}"
                    f"</blockquote>\n\n"
                    f"{tip}\n\n"
                    f"<i>Чтобы отключить уведомления — зайди в 👤 Профиль.</i>"
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💱 Обменять сейчас", callback_data="menu_exchange")]
                ])
                try:
                    await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
                    with db_conn(5) as conn:
                        conn.execute(
                            "UPDATE rate_subscriptions SET last_notified=?, last_btc=?, last_ltc=?, last_usdt=? WHERE user_id=?",
                            (now, btc, ltc, usdt, uid)
                        )
                        conn.commit()
                except Exception as e:
                    err = str(e).lower()
                    if "blocked" in err or "forbidden" in err or "deactivated" in err:
                        with db_conn(5) as conn:
                            conn.execute("UPDATE rate_subscriptions SET enabled=0 WHERE user_id=?", (uid,))
                            conn.commit()
                    else:
                        logger.warning(f"rate_alert: не удалось отправить {uid}: {e}")
                await asyncio.sleep(0.05)

        except Exception as e:
            logger.error(f"rate_alert_scheduler error: {e}")

        await asyncio.sleep(CHECK_EVERY)


async def daily_post_scheduler():
    """Рассылает пост с курсами каждые 5 часов.
       Метка в Redis переживает перезапуски — иначе каждый restart бота
       рассылал пост заново через 60 секунд."""
    interval = 5 * 3600
    await asyncio.sleep(60)  # небольшая задержка после старта бота
    while True:
        last = 0.0
        try:
            if _monitor_redis:
                last = float(_monitor_redis.get("monitor:last_daily_post") or 0)
        except Exception:
            pass
        wait = interval - (time.time() - last)
        if wait > 0:
            logger.info(f"Рассылка поста по плану через {wait/60:.0f} мин")
            await asyncio.sleep(wait)
        try:
            if _monitor_redis:
                _monitor_redis.set("monitor:last_daily_post", str(time.time()))
        except Exception:
            pass
        await send_daily_post()
        logger.info("Следующий пост с курсами через 5ч")
        await asyncio.sleep(interval)


# ══════════════════════════════════════════════════════════════════
# АВТОПОСТЫ — НАПОМИНАНИЯ О ФУНКЦИОНАЛЕ
# Каждый понедельник в 11:00 МСК — ротируем блок функций.
# Раз в 4 недели — тарифная сетка целиком.
# ══════════════════════════════════════════════════════════════════

_TARIFF_TEXT = """💎 <b>Тарифная сетка ObsidianExchange</b>

<blockquote><b>Комиссия зависит от суммы:</b>
• 2 000 — 4 999 ₽ → <b>27%</b>
• 5 000 — 9 999 ₽ → <b>25%</b>
• 10 000 — 19 999 ₽ → <b>23%</b>
• от 20 000 ₽ → <b>19%</b>
• USDT (TRC-20) → <b>~2%</b></blockquote>

<blockquote><b>VIP-скидки (накопительно):</b>
🥈 Silver — от 30 000 ₽ оборота → <b>−3%</b>
🥇 Gold — от 100 000 ₽ → <b>−6%</b>
💎 Platinum — от 300 000 ₽ → <b>−10%</b></blockquote>

<blockquote><b>Специальные тарифы:</b>
⏳ Лимитная заявка → <b>+1%</b> к стандарту
🔒 Фиксация курса на 15 мин → <b>100 ₽</b>
🎁 Промокод → скидка до <b>−5%</b> к комиссии</blockquote>

Обмен BTC, LTC, USDT TRC-20 · Оплата СБП / карта · Без KYC"""

_FEATURE_POSTS = [
    # 0 — лимитные заявки
    (
        "⏳ <b>Лимитные заявки — покупайте по нужному курсу</b>\n\n"
        "Устали следить за курсом вручную?\n\n"
        "Просто скажите боту: «куплю BTC когда курс упадёт до X» — "
        "и бот сам создаст заявку в нужный момент. Вам останется только оплатить.\n\n"
        "<blockquote>✅ Работает круглосуточно\n"
        "✅ Ордер действует 7 дней\n"
        "✅ Комиссия всего +1% к стандарту</blockquote>\n\n"
        "👉 Нажмите <b>⏳ Лимитная заявка</b> в меню бота.",
        "menu_limit"
    ),
    # 1 — DCA
    (
        "📅 <b>DCA — копите крипту без стресса</b>\n\n"
        "Профессиональная стратегия усреднения теперь в вашем кармане.\n\n"
        "Настройте регулярную покупку — бот будет автоматически создавать заявку "
        "каждые 3, 7, 14 или 30 дней. Вы просто оплачиваете.\n\n"
        "<blockquote>💡 Покупки по разным ценам = ниже средняя стоимость\n"
        "⚡ Без мониторинга рынка\n"
        "🔄 Подходит для BTC, LTC, USDT</blockquote>\n\n"
        "👉 Нажмите <b>📅 DCA-автопокупка</b> в меню бота.",
        "menu_dca"
    ),
    # 2 — подарки
    (
        "🎁 <b>Крипто-подарок — оригинальный способ поздравить</b>\n\n"
        "Подарите другу или близкому криптовалюту — даже если у него нет кошелька.\n\n"
        "<blockquote>1️⃣ Вы оплачиваете подарок\n"
        "2️⃣ Получаете красивую карточку с кодом\n"
        "3️⃣ Отправляете другу в любом мессенджере\n"
        "4️⃣ Друг вводит код → получает крипту на свой адрес</blockquote>\n\n"
        "₿ BTC · Ł LTC · 💵 USDT — от 2 000 ₽\n\n"
        "👉 Нажмите <b>🎁 Подарить крипту</b> в меню бота.",
        "menu_gift"
    ),
    # 3 — тарифная сетка (раз в 4 недели)
    (_TARIFF_TEXT, "menu_exchange"),
    # 4 — фиксация курса
    (
        "🔒 <b>Гарантированный курс — оплачивайте без спешки</b>\n\n"
        "Курс всегда движется. Бывает обидно: нашёл хороший момент, а пока "
        "собирал деньги — курс ушёл.\n\n"
        "Теперь не так: нажмите <b>🔒 Зафиксировать курс</b> и 15 минут "
        "курс принадлежит вам — рынок хоть на 5% улетит.\n\n"
        "<blockquote>💰 Стоимость фиксации: 100 ₽\n"
        "⏱ Длительность: 15 минут\n"
        "✅ Применяется автоматически при создании заявки</blockquote>\n\n"
        "👉 Нажмите <b>🔒 Зафиксировать курс</b> в меню бота.",
        "menu_ratelock"
    ),
    # 5 — рефералка
    (
        "🎁 <b>Зарабатывайте на рефералке без вложений</b>\n\n"
        "Пригласите друга — получите бонус с каждого его обмена навсегда.\n\n"
        "<blockquote>• Ваш друг делает обмен → вы получаете бонус\n"
        "• Бонус начисляется автоматически\n"
        "• Вывод в любой момент</blockquote>\n\n"
        "Чем больше активных рефералов — тем выше пассивный доход.\n\n"
        "👉 Нажмите <b>🎁 Пригласить и заработать</b> в меню бота.",
        "menu_ref"
    ),
    # 6 — VIP
    (
        "💎 <b>VIP-статус — меньше комиссия, больше выгода</b>\n\n"
        "Чем больше вы обмениваете — тем дешевле каждый следующий обмен.\n\n"
        "<blockquote>🥈 Silver (от 30 000 ₽) → комиссия −3%\n"
        "🥇 Gold (от 100 000 ₽) → комиссия −6%\n"
        "💎 Platinum (от 300 000 ₽) → комиссия −10%</blockquote>\n\n"
        "Статус начисляется автоматически. Проверить — в разделе <b>👤 Профиль</b>.\n\n"
        "👉 Ваш статус и текущий объём — /profile",
        "menu_profile"
    ),
    # 7 — полный функционал (сводка)
    (
        "🟣 <b>ObsidianExchange — всё в одном боте</b>\n\n"
        "<blockquote>"
        "💱 Купить BTC, LTC, USDT — от 2 000 ₽\n"
        "⏳ Лимитная заявка — по нужному курсу\n"
        "📅 DCA — автопокупка по расписанию\n"
        "🔒 Фиксация курса на 15 минут\n"
        "🎁 Крипто-подарки для друзей\n"
        "💎 VIP-скидки до −10%\n"
        "🎟 Промокоды\n"
        "📋 История и экспорт заявок\n"
        "🆘 Поддержка 24/7"
        "</blockquote>\n\n"
        "Оплата: СБП или карта. Без KYC. Работаем с 2024 года.\n\n"
        "👉 Начать обмен →",
        "menu_exchange"
    ),
]

# Глобальный счётчик ротации (сохраняем между перезапусками в файле)
_FEATURE_INDEX_FILE = "/root/bot/.feature_index"

def _get_feature_index() -> int:
    try:
        return int(open(_FEATURE_INDEX_FILE).read().strip())
    except Exception:
        return 0

def _set_feature_index(i: int):
    try:
        open(_FEATURE_INDEX_FILE, "w").write(str(i))
    except Exception:
        pass


async def feature_broadcast(target_id: int = None):
    """Рассылка одного поста из ротации всем пользователям (или target_id для теста)."""
    idx = _get_feature_index()
    text, btn_data = _FEATURE_POSTS[idx % len(_FEATURE_POSTS)]
    _set_feature_index((idx + 1) % len(_FEATURE_POSTS))

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💱 Открыть", callback_data=btn_data)
    ]])

    if target_id:
        await bot.send_message(target_id, text, parse_mode="HTML", reply_markup=kb)
        return

    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("""SELECT DISTINCT user_id FROM orders
                     WHERE user_id > 0
                     GROUP BY user_id""")
        users = [r[0] for r in c.fetchall()]

    sent = skipped = 0
    for uid in users:
        try:
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except Exception:
            skipped += 1
        await asyncio.sleep(0.05)

    await notify_admins(
        f"📣 Фича-пост #{idx} разослан\n✅ {sent} · ⛔ {skipped}",
        parse_mode="HTML"
    )


_BROADCAST_INTERVAL = 3 * 3600  # 3 часа между рассылками

async def feature_broadcast_scheduler():
    """Рассылка постов из ротации раз в 3 часа. Хранит метку времени в Redis — переживает перезапуски."""
    await asyncio.sleep(60)  # небольшая пауза при старте

    _r = None
    try:
        import redis as _redis_sync
        _r = _redis_sync.Redis(host='localhost', port=6379, db=1, decode_responses=True)
    except Exception:
        pass

    LAST_KEY = "broadcast:last_sent_at"

    while True:
        try:
            now_ts = int(__import__('time').time())
            last_ts = int(_r.get(LAST_KEY) or 0) if _r else 0
            elapsed = now_ts - last_ts

            if elapsed >= _BROADCAST_INTERVAL:
                await feature_broadcast()
                if _r:
                    _r.set(LAST_KEY, now_ts)
                logger.info(f"feature_broadcast отправлен, следующий через 3ч")
            else:
                wait_left = _BROADCAST_INTERVAL - elapsed
                logger.info(f"feature_broadcast: пропуск, следующий через {wait_left//60}мин")
        except Exception as e:
            logger.error(f"feature_broadcast_scheduler error: {e}")
        await asyncio.sleep(600)  # проверяем каждые 10 минут


_PROMO_POST_HTML = """🔮💜💎⚡🌑⚡🟣✨💫
<b>ObsidianExchange</b> — крипто-обменник нового поколения

Без паспорта · Без ожидания · Бот работает сам круглосуточно

〰〰〰〰〰〰〰〰〰〰〰〰〰

⚡ <b>ЧТО УМЕЕТ НАШ БОТ</b>

▸ <b>Покупка и продажа</b> — платишь рублями по СБП или картой, бот автоматически отправляет BTC / LTC / USDT на твой адрес сразу после оплаты

▸ <b>Своп</b> — меняешь BTC → LTC → USDT напрямую, без конвертации в рубли

▸ <b>Лимитные заявки</b> — выставляешь целевой курс и забываешь. Бот сам исполнит сделку когда цена достигнет нужной отметки. Работает 7 дней

▸ <b>DCA-автопокупка</b> — настраиваешь расписание раз и навсегда. Бот покупает крипту каждые N дней без твоего участия. Усредняй позицию без нервов

▸ <b>Фиксация курса</b> — заморозь текущий курс на 15 минут пока ищешь средства. Рынок хоть на 5% улетит — курс твой

▸ <b>Крипто-подарок</b> — отправь BTC, LTC или USDT другу прямо в боте, одной кнопкой. Получи красивую карточку с кодом

〰〰〰〰〰〰〰〰〰〰〰〰〰

📊 <b>ПРОГРЕССИВНАЯ КОМИССИЯ</b>

<blockquote>• 500 – 2 000 ₽ → <b>25%</b>
• 2 000 – 10 000 ₽ → <b>23%</b>
• от 10 000 ₽ → <b>21%</b>
• 💎 VIP Platinum → <b>от 19%</b>

<i>Чем больше объём — тем ниже комиссия</i></blockquote>

💎 <b>VIP-статусы:</b> 🥈 Silver · 🥇 Gold · 💎 Platinum — присваивается автоматически по объёму, скидка без заявок

👥 <b>Реферальная программа</b> — получай <b>1%</b> с каждого обмена приглашённых навсегда. Статистика в разделе Профиль

🎟 <b>Промокоды</b> для новых клиентов — следи за каналом, публикуем регулярно

〰〰〰〰〰〰〰〰〰〰〰〰〰

✅ NON-KYC — никаких документов и верификации. Никогда
✅ Автовыплаты — крипта уходит сразу после подтверждения оплаты
✅ Мониторинг 24/7 — уведомления на каждом шаге заявки
✅ Поддержка прямо в боте — отвечаем за 30 минут
✅ Личный кабинет — obsidian-exchange.org

〰〰〰〰〰〰〰〰〰〰〰〰〰

👉 <b>@Obsidian666999bot</b>
🌐 obsidian-exchange.org

<i>BTC · LTC · USDT TRC-20 · СБП · Карта · Работаем без выходных</i>"""


@router.message(Command("postpromo"))
async def cmd_postpromo(message: Message):
    """/postpromo — рекламный пост с баннером в канал.
       /postpromo preview — предпросмотр без публикации."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    preview = len(parts) > 1 and parts[1] == "preview"
    target = message.chat.id if preview else CHANNEL_ID

    # Буквы названия вместо баннера — превью в ленте показывает "OBS..."
    _sd = pathlib.Path("/root/bot/images/stickers")
    _letter_seq = ["letter_O", "letter_B", "letter_S", "letter_I", "letter_D",
                   "letter_I", "letter_A", "letter_N", "letter_EX"]
    try:
        letter_media = [
            InputMediaPhoto(media=FSInputFile(str(_sd / f"{fn}.png")))
            for fn in _letter_seq
            if (_sd / f"{fn}.png").exists()
        ]
        if letter_media:
            await bot.send_media_group(target, letter_media)

        # Полный рекламный текст отдельным сообщением
        await bot.send_message(
            target,
            _PROMO_POST_HTML,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        if preview:
            await message.answer("👆 Предпросмотр выше. Для публикации: /postpromo")
        else:
            await message.answer("✅ Пост опубликован в канале.\n🔗 Закрепи: удержи → Закрепить")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(Command("featurepost"))
async def cmd_featurepost(message: Message):
    """/featurepost — тест текущего поста / /featurepost all — рассылка всем."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) > 1 and parts[1] == "all":
        await message.answer("📣 Запускаю рассылку...")
        await feature_broadcast()
    else:
        idx = _get_feature_index()
        text, btn_data = _FEATURE_POSTS[idx % len(_FEATURE_POSTS)]
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💱 Открыть", callback_data=btn_data)
        ]])
        await message.answer(f"📋 Превью поста #{idx}:\n\n{text}", parse_mode="HTML", reply_markup=kb)


@router.message(Command("tariff"))
async def cmd_tariff(message: Message):
    """Публичная команда — показывает тарифную сетку."""
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💱 Обменять", callback_data="menu_exchange")
    ]])
    await message.answer(_TARIFF_TEXT, parse_mode="HTML", reply_markup=kb)


async def recall_inactive_users():
    """Раз в 3 дня напоминает клиентам, не делавшим заявок > 14 дней.
    Каждый клиент получает не более одного recall-сообщения в 14 дней."""
    import datetime as _dt
    while True:
        try:
            now = _dt.datetime.utcnow()
            # Запускаем в 10:00 UTC (13:00 МСК)
            target = now.replace(hour=10, minute=0, second=0, microsecond=0)
            if now >= target:
                target += _dt.timedelta(days=3)
            await asyncio.sleep((target - now).total_seconds())

            threshold_inactive = (
                _dt.datetime.utcnow() - _dt.timedelta(days=14)
            ).strftime("%Y-%m-%d %H:%M:%S")
            threshold_notified = (
                _dt.datetime.utcnow() - _dt.timedelta(days=14)
            ).strftime("%Y-%m-%d %H:%M:%S")

            with db_conn(5) as conn:
                c = conn.cursor()
                # Клиенты с минимум 1 успешной заявкой, неактивные > 14 дней
                c.execute("""
                    SELECT DISTINCT o.user_id
                    FROM orders o
                    WHERE o.user_id > 0
                      AND o.status = 'sent'
                      AND NOT EXISTS (
                          SELECT 1 FROM orders o2
                          WHERE o2.user_id = o.user_id
                            AND o2.created_at > ?
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM sent_notifications sn
                          WHERE sn.order_id = o.user_id AND sn.event = 'recall'
                            AND sn.created_at > ?
                      )
                    LIMIT 200
                """, (threshold_inactive, threshold_notified))
                users = [r[0] for r in c.fetchall()]

            btc_rate = get_cached_rate('BTC')
            ltc_rate = get_cached_rate('LTC')
            usdt_rate = get_cached_rate('USDT')

            sent = 0
            for uid in users:
                try:
                    await bot.send_message(
                        uid,
                        f"🟣 <b>ObsidianExchange — актуальные курсы</b>\n\n"
                        f"<blockquote>"
                        f"₿ BTC → {int(btc_rate * 0.81):,} ₽\n"
                        f"Ł LTC → {int(ltc_rate * 0.81):,} ₽\n"
                        f"💵 USDT → {int(usdt_rate * 0.98):,} ₽"
                        f"</blockquote>\n\n"
                        f"Готовы к обмену? Нажмите кнопку ниже 👇".replace(",", " "),
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="💱 Обменять", callback_data="menu_exchange")
                        ]]),
                        parse_mode="HTML"
                    )
                    # Записываем факт отправки (используем user_id как order_id для recall)
                    with db_conn(3) as conn:
                        conn.execute(
                            "INSERT OR IGNORE INTO sent_notifications (order_id, event) VALUES (?, 'recall')",
                            (uid,)
                        )
                        conn.commit()
                    sent += 1
                    await asyncio.sleep(0.05)  # не спамим TG API
                except Exception:
                    pass

            if sent:
                logger.info(f"recall_inactive_users: отправлено {sent} сообщений")

        except Exception as e:
            logger.error(f"recall_inactive_users error: {e}")
            await asyncio.sleep(3600)


async def montera_receipt_reminder():
    """Напоминание клиенту за 10 минут до истечения 30-минутного окна чека Montera."""
    while True:
        try:
            import datetime as _dt
            now = _dt.datetime.utcnow()
            # Окно: дедлайн через 8–12 минут, чек ещё не отправлен, заявка pending
            window_from = (now + _dt.timedelta(minutes=8)).strftime("%Y-%m-%d %H:%M:%S")
            window_to   = (now + _dt.timedelta(minutes=12)).strftime("%Y-%m-%d %H:%M:%S")
            with db_conn(5) as conn:
                c = conn.cursor()
                c.execute("""
                    SELECT o.order_id, o.user_id, o.montera_invoice_id, o.receipt_deadline
                    FROM orders o
                    WHERE o.receipt_deadline BETWEEN ? AND ?
                      AND o.receipt_sent_at IS NULL
                      AND o.status = 'pending'
                      AND NOT EXISTS (
                          SELECT 1 FROM sent_notifications sn
                          WHERE sn.order_id = o.order_id AND sn.event = 'receipt_reminder'
                      )
                """, (window_from, window_to))
                rows = c.fetchall()

            for oid, uid, inv_id, deadline in rows:
                if uid and uid > 0:
                    try:
                        await bot.send_message(
                            uid,
                            f"⏰ <b>Заявка #{oid} — осталось ~10 минут!</b>\n\n"
                            f"Пожалуйста, оплатите перевод и отправьте <b>PDF-чек</b> прямо сейчас.\n"
                            f"Если вы уже оплатили — просто перешлите чек сюда.",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                    await notify_admins(
                        f"⚠️ <b>Заявка #{oid}</b> — чек не отправлен, дедлайн через ~10 мин\n"
                        f"Montera ID: <code>{inv_id}</code>",
                        parse_mode="HTML"
                    )
                with db_conn(5) as conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO sent_notifications (order_id, event) VALUES (?, 'receipt_reminder')",
                        (oid,)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"montera_receipt_reminder error: {e}")
        await asyncio.sleep(60)


# ── Стоп-таймер: UUID сообщения для Montera-оператора при задержке чека ──────
# Если клиент явно оплатил, но не успевает прислать чек — форвардни это сообщение
# в чат Montera чтобы остановить таймер.
MONTERA_STOP_TIMER_MSG_ID = "7556e112-7438-440c-bf4b-e38a81f1d49e"
MONTERA_STOP_TIMER_IMG    = "https://postimg.cc/Wq2zpG4G"

@router.message(Command("stoptimer"))
async def stoptimer_cmd(message: Message):
    """Для тебя: /stoptimer ORDER_ID — отправляет напоминание себе с UUID для Montera."""
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    order_id = parts[1] if len(parts) > 1 else "?"
    with db_conn(5) as conn:
        c = conn.cursor()
        c.execute("SELECT montera_invoice_id, rub_amount FROM orders WHERE order_id=?", (order_id,))
        row = c.fetchone()
    inv_id = row[0] if row else "—"
    amt    = row[1] if row else "?"
    await message.answer(
        f"🛑 <b>Стоп-таймер — Заявка #{order_id}</b>\n\n"
        f"Montera Deal ID: <code>{inv_id}</code>\n"
        f"Сумма: {amt} ₽\n\n"
        f"Шаблонное сообщение для Montera:\n"
        f"<code>{MONTERA_STOP_TIMER_MSG_ID}</code>\n\n"
        f"Скопируй UUID выше и отправь в чат Montera — это остановит таймер на 30 минут.",
        parse_mode="HTML"
    )


async def main():
    asyncio.create_task(balance_monitor())
    asyncio.create_task(smart_monitor())
    asyncio.create_task(verify_backups())
    asyncio.create_task(ssl_healthcheck())
    asyncio.create_task(update_fees())
    # Авто-выплата готова (BTC/LTC), но отключена: PayoutWallet/PayoutLTC пусты.
    # Перед включением — пополнить горячие кошельки и проверить баланс через /balance,
    # затем раскомментировать строку ниже и перезапустить сервис.
    asyncio.create_task(auto_check_payments())
    asyncio.create_task(auto_check_usdt())
    asyncio.create_task(swap_status_monitor())
    asyncio.create_task(daily_post_scheduler())
    asyncio.create_task(rate_alert_scheduler())
    asyncio.create_task(montera_receipt_reminder())
    asyncio.create_task(limit_order_watcher())
    asyncio.create_task(recall_inactive_users())
    asyncio.create_task(dca_runner())
    asyncio.create_task(feature_broadcast_scheduler())
    asyncio.create_task(daily_report())
    # # asyncio.create_task(platega_healthcheck())
    asyncio.create_task(check_stuck_orders())
    asyncio.create_task(website_healthcheck())
    asyncio.create_task(disk_healthcheck())
    # Меню команд (кнопка «/» у пользователей)
    try:
        from aiogram.types import BotCommand
        await bot.set_my_commands([
            BotCommand(command="start",     description="🟣 Главное меню"),
            BotCommand(command="mystatus",  description="👤 Мой VIP-статус и скидка"),
            BotCommand(command="myhistory", description="📋 История заявок"),
            BotCommand(command="mydca",     description="📅 Мои DCA-планы"),
            BotCommand(command="redeem",    description="🎁 Активировать подарочный код"),
            BotCommand(command="offer",     description="📜 Пользовательское соглашение"),
        ])
    except Exception as e:
        logger.warning(f"set_my_commands: {e}")
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    finally:
        remove_pid()
