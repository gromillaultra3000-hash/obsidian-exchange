import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data
    if data == "like":
        text = f"👍 Спасибо, {user.first_name}! Рады, что вам интересно. Подписывайтесь на наш канал и обменник!"
    elif data == "dispute":
        text = f"🤔 Спасибо за обратную связь, {user.first_name}! Напишите в поддержку @ObsidianExchangeBot, что именно вызвало сомнения."
    elif data == "idea":
        text = f"💡 Отличная идея, {user.first_name}! Пожалуйста, отправьте её в чат поддержки @ObsidianExchangeBot, и мы рассмотрим."
    else:
        text = "Спасибо за реакцию!"
    await context.bot.send_message(chat_id=user.id, text=text)

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CallbackQueryHandler(button_callback))
    print("Callback handler started...")
    app.run_polling()

if __name__ == "__main__":
    main()
