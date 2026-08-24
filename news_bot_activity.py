import sqlite3
import os
import json
import random
import requests

DB_PATH = "/root/exchange.db"
STATE_FILE = "/root/news_activity_state.json"
MILESTONE_STEP = 50

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")

ENGAGEMENT_POLLS = [
    {
        "question": "Какую валюту вы чаще меняете на ObsidianExchange?",
        "options": ["₿ BTC", "Ł LTC", "💵 USDT", "Другое"]
    },
    {
        "question": "Что для вас важнее при обмене?",
        "options": ["⚡ Скорость", "💱 Курс", "🔒 Анонимность", "🛟 Поддержка"]
    },
    {
        "question": "Пользуетесь ли реферальной программой ObsidianExchange?",
        "options": ["✅ Да, активно", "🤔 Слышал, но не пробовал", "❌ Нет", "Что это?"]
    },
    {
        "question": "Как часто вы меняете крипту?",
        "options": ["Каждый день", "Пару раз в неделю", "Раз в месяц", "Редко"]
    },
]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_order_id": 0, "last_milestone": 0, "last_review_id": 0}
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def get_db():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def send_message(text, reply_markup=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code != 200:
        print(f"Telegram error: {r.status_code} {r.text}")
        return False
    return True


def send_poll(question, options):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPoll"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "question": question,
        "options": json.dumps(options),
        "is_anonymous": True,
        "allows_multiple_answers": False,
        "type": "regular"
    }
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code != 200:
        print(f"Poll error: {r.status_code} {r.text}")
        return False
    return True


def try_trade_activity(state):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT order_id, rub_amount, currency FROM orders "
            "WHERE status='sent' AND order_id > ? ORDER BY order_id ASC",
            (state["last_order_id"],)
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return False

    state["last_order_id"] = max(r[0] for r in rows)
    order_id, rub_amount, currency = random.choice(rows)
    text = (
        f"✅ Обмен #{order_id}\n"
        f"💰 {rub_amount:,.0f} ₽ → {currency}\n"
        f"Выполнено автоматически за пару минут ⚡"
    ).replace(",", " ")
    return send_message(text)


def try_milestone(state):
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM orders WHERE status='sent'").fetchone()[0]
    finally:
        conn.close()

    threshold = (count // MILESTONE_STEP) * MILESTONE_STEP
    if threshold > 0 and threshold > state["last_milestone"]:
        state["last_milestone"] = threshold
        text = (
            f"🎉 Юбилей! ObsidianExchange выполнил уже {threshold}-й обмен.\n"
            f"Спасибо, что вы с нами! 🙌"
        )
        return send_message(text)
    return False


def try_engagement_poll():
    poll = random.choice(ENGAGEMENT_POLLS)
    return send_poll(poll["question"], poll["options"])


def try_review_of_day(state):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id, rating, comment FROM reviews "
            "WHERE status='published' AND id > ? "
            "ORDER BY rating DESC, id DESC LIMIT 1",
            (state["last_review_id"],)
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()

    if not row:
        return False

    review_id, rating, comment = row
    state["last_review_id"] = review_id
    stars = "⭐" * (rating or 5)
    comment_text = comment.strip() if comment and comment.strip() else "Без комментария"
    text = (
        f"💬 Отзыв дня\n{stars}\n\n\"{comment_text}\"\n\n"
        f"Больше отзывов: @ObsidianReviews"
    )
    return send_message(text)


def main():
    state = load_state()

    post_types = ["trade", "milestone", "poll", "review"]
    weights = [0.4, 0.15, 0.25, 0.2]
    choice = random.choices(post_types, weights=weights, k=1)[0]

    handlers = {
        "trade": lambda: try_trade_activity(state),
        "milestone": lambda: try_milestone(state),
        "poll": try_engagement_poll,
        "review": lambda: try_review_of_day(state),
    }

    fallback_order = ["trade", "poll"]

    ok = handlers[choice]()
    if not ok:
        for fb in fallback_order:
            if fb == choice:
                continue
            if handlers[fb]():
                ok = True
                break

    save_state(state)
    print(f"Тип поста: {choice}, успешно: {ok}")


if __name__ == "__main__":
    main()
