import asyncio, os, sys, sqlite3, time
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from secret_guard import contains_secret, secret_reason

env_path = Path('/root/support_bot/.env')
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

TOKEN = os.getenv('SUPPORT_BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
ADMIN_ID_2 = int(os.getenv('ADMIN_ID_2', 0))
ADMIN_IDS = {a for a in (ADMIN_ID, ADMIN_ID_2) if a}
# Общая БД обменника — оттуда берём операторов (таблицу ведёт основной бот)
EXCHANGE_DB = os.getenv('EXCHANGE_DB', '/root/exchange.db')

if not TOKEN or not ADMIN_ID:
    print("Не заданы SUPPORT_BOT_TOKEN или ADMIN_ID")
    sys.exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "support.db")


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS support_messages (
        admin_msg_id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    # маппинг для нескольких сотрудников: (чат сотрудника, id сообщения) -> клиент
    conn.execute("""CREATE TABLE IF NOT EXISTS staff_messages (
        staff_id INTEGER NOT NULL,
        msg_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (staff_id, msg_id))""")
    conn.commit()
    conn.close()


init_db()

# Кеш операторов из exchange.db (60 сек)
_operators_cache = {"ids": set(), "ts": 0.0}

def get_staff_ids() -> set[int]:
    """Админы + активные операторы из общей БД обменника."""
    now = time.time()
    if now - _operators_cache["ts"] > 60:
        try:
            conn = sqlite3.connect(EXCHANGE_DB, timeout=5)
            rows = conn.execute("SELECT user_id FROM operators WHERE is_active=1").fetchall()
            conn.close()
            _operators_cache["ids"] = {r[0] for r in rows}
        except Exception as e:
            print(f"operators fetch: {e}")
        _operators_cache["ts"] = now
    return ADMIN_IDS | _operators_cache["ids"]


def save_staff_msg(staff_id: int, msg_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("INSERT OR REPLACE INTO staff_messages (staff_id, msg_id, user_id) VALUES (?,?,?)",
                 (staff_id, msg_id, user_id))
    conn.commit()
    conn.close()


def lookup_user(staff_id: int, msg_id: int):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    c = conn.cursor()
    c.execute("SELECT user_id FROM staff_messages WHERE staff_id=? AND msg_id=?", (staff_id, msg_id))
    row = c.fetchone()
    if not row and staff_id == ADMIN_ID:
        # старый маппинг (до многосотрудникового режима)
        c.execute("SELECT user_id FROM support_messages WHERE admin_msg_id=?", (msg_id,))
        row = c.fetchone()
    conn.close()
    return row[0] if row else None


@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id in get_staff_ids():
        await message.answer(
            "🎧 Вы сотрудник поддержки ObsidianExchange.\n\n"
            "Обращения клиентов приходят сюда — отвечайте реплаем на сообщение "
            "клиента, ответ уйдёт ему напрямую."
        )
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Проблемы с оплатой", callback_data="faq_payment")],
        [InlineKeyboardButton(text="📈 Курс обмена", callback_data="faq_rate")],
        [InlineKeyboardButton(text="⏳ Где мои средства?", callback_data="faq_where")],
        [InlineKeyboardButton(text="👤 Связаться с оператором", callback_data="faq_admin")],
    ])
    await message.answer("Привет! Я бот поддержки ObsidianExchange. Выберите вопрос или напишите его напрямую.", reply_markup=kb)

@dp.callback_query(F.data.startswith("faq_"))
async def faq_callback(callback: CallbackQuery):
    answers = {
        "faq_payment": "Если возникли проблемы с оплатой, проверьте:\n1. Правильность суммы.\n2. Достаточность средств.\n3. Не истекло ли время.\nЕсли всё верно, обратитесь к оператору.",
        "faq_rate": "Курс зависит от суммы и обновляется каждые 5 минут. Точный курс вы видите при создании заявки.",
        "faq_where": "Средства отправляются автоматически после подтверждения оплаты. Обычно это занимает 2-5 минут. Если прошло больше 15 минут, свяжитесь с оператором.",
        "faq_admin": "Напишите ваш вопрос, и оператор ответит в ближайшее время.",
    }
    answer = answers.get(callback.data, "Пожалуйста, уточните ваш вопрос.")
    await callback.message.answer(answer)
    await callback.answer()

@dp.message(F.reply_to_message)
async def reply_to_user(message: Message):
    staff = get_staff_ids()
    if message.from_user.id not in staff:
        await forward_to_staff(message)
        return
    user_id = lookup_user(message.chat.id, message.reply_to_message.message_id)
    if not user_id:
        await message.reply("⚠️ Не найдено обращение для этого сообщения (слишком старое?)")
        return
    try:
        # copy_message — чтобы можно было отвечать и текстом, и фото/документом
        await bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
        await message.reply("✅ Доставлено")
        for sid in staff - {message.from_user.id}:
            try:
                await bot.send_message(
                    sid,
                    f"ℹ️ @{message.from_user.username or message.from_user.id} ответил клиенту ID {user_id}.")
            except Exception:
                pass
    except Exception as e:
        await message.reply(f"❌ Не удалось доставить ответ: {e}")


@dp.message()
async def forward_to_staff(message: Message):
    staff = get_staff_ids()
    if message.from_user.id in staff:
        return
    # Fail-closed по приватным данным: не пересылаем и не сохраняем сообщения с секретами.
    _blob = message.text or message.caption or ""
    _reason = secret_reason(_blob)
    if _reason:
        print(f"secret_guard: заблокировано сообщение от {message.from_user.id} ({_reason})")
        await message.answer(
            "🔒 В сообщении обнаружены приватные данные (приватный ключ, seed-фраза или пароль).\n\n"
            "Мы НЕ передали его в поддержку и не сохранили — ради вашей безопасности. "
            "Никогда и никому не отправляйте seed-фразу и приватные ключи: у кого они есть — "
            "у того полный доступ к вашим средствам. Поддержке они НИКОГДА не нужны.\n\n"
            "Опишите проблему без секретных данных — и мы поможем."
        )
        return
    header = (f"Сообщение от @{message.from_user.username or 'нет юзернейма'} "
              f"(ID {message.from_user.id}):"
              + (f"\n\n{message.text}" if message.text else ""))
    delivered = 0
    for sid in staff:
        try:
            sent = await bot.send_message(sid, header)
            save_staff_msg(sid, sent.message_id, message.from_user.id)
            if not message.text:
                # медиа (фото/документ/войс) — пересылаем оригинал следом
                fwd = await message.forward(sid)
                save_staff_msg(sid, fwd.message_id, message.from_user.id)
            delivered += 1
        except Exception as e:
            print(f"Ошибка отправки сотруднику {sid}: {e}")
    if delivered:
        await message.answer("Ваше сообщение отправлено в поддержку. Ожидайте ответа.")
    else:
        await message.answer("Произошла ошибка, попробуйте позже.")

async def main():
    print("Бот поддержки запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот поддержки остановлен")
