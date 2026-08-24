import asyncio
import logging
from dotenv import load_dotenv
import os

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

load_dotenv()

SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

support_bot = Bot(token=SUPPORT_BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

# message_id пересланного сообщения в чате админа -> chat_id пользователя
forwarded_messages = {}

@dp.message(Command("start"))
async def start_support(message: Message):
    await message.answer(
        "👨‍💼 Добро пожаловать в поддержку 1369 Exchange!\n\n"
        "Опишите вашу проблему или пришлите номер заявки.\n"
        "Мы ответим в ближайшее время."
    )

@dp.message(F.from_user.id == ADMIN_ID, F.reply_to_message)
async def reply_to_user(message: Message):
    original_chat_id = forwarded_messages.get(message.reply_to_message.message_id)
    if not original_chat_id:
        await message.answer("❌ Не удалось определить пользователя — отвечайте реплаем на пересланное сообщение.")
        return
    try:
        await support_bot.copy_message(chat_id=original_chat_id, from_chat_id=ADMIN_ID, message_id=message.message_id)
        await message.answer("✅ Ответ отправлен пользователю.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить ответ: {e}")

@dp.message()
async def forward_to_admin(message: Message):
    if message.from_user.id == ADMIN_ID:
        return
    try:
        fwd = await message.forward(ADMIN_ID)
        forwarded_messages[fwd.message_id] = message.chat.id
        await message.answer("✅ Ваше сообщение отправлено в поддержку. Ожидайте ответа.")
    except Exception:
        await message.answer("❌ Ошибка отправки. Попробуйте позже.")

async def main():
    print("🚀 Бот поддержки запущен")
    await dp.start_polling(support_bot)

if __name__ == "__main__":
    asyncio.run(main())
