import asyncio, os, sys
from pathlib import Path
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command

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

if not TOKEN or not ADMIN_ID:
    print("Не заданы SUPPORT_BOT_TOKEN или ADMIN_ID")
    sys.exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Проблемы с оплатой", callback_data="faq_payment")],
        [InlineKeyboardButton(text="📈 Курс обмена", callback_data="faq_rate")],
        [InlineKeyboardButton(text="⏳ Где мои средства?", callback_data="faq_where")],
        [InlineKeyboardButton(text="👤 Связаться с админом", callback_data="faq_admin")],
    ])
    await message.answer("Привет! Я бот поддержки ObsidianExchange. Выберите вопрос или напишите его напрямую.", reply_markup=kb)

@dp.callback_query(F.data.startswith("faq_"))
async def faq_callback(callback: CallbackQuery):
    answers = {
        "faq_payment": "Если возникли проблемы с оплатой, проверьте:\n1. Правильность суммы.\n2. Достаточность средств.\n3. Не истекло ли время.\nЕсли всё верно, обратитесь к админу.",
        "faq_rate": "Курс зависит от суммы и обновляется каждые 5 минут. Точный курс вы видите при создании заявки.",
        "faq_where": "Средства отправляются автоматически после подтверждения оплаты. Обычно это занимает 2-5 минут. Если прошло больше 15 минут, свяжитесь с админом.",
        "faq_admin": "Напишите ваш вопрос, и администратор ответит в ближайшее время.",
    }
    answer = answers.get(callback.data, "Пожалуйста, уточните ваш вопрос.")
    await callback.message.answer(answer)
    await callback.answer()

@dp.message(F.text)
async def forward_to_admin(message: Message):
    user_info = f"Сообщение от @{message.from_user.username or 'нет юзернейма'} (ID {message.from_user.id}):\n\n{message.text}"
    try:
        await bot.send_message(ADMIN_ID, user_info)
        await message.answer("Ваше сообщение отправлено администратору. Ожидайте ответа.")
    except Exception as e:
        await message.answer("Произошла ошибка, попробуйте позже.")
        print(f"Ошибка отправки админу: {e}")

async def main():
    print("Бот поддержки запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот поддержки остановлен")
