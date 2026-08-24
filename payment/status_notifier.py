import time, logging, sys, requests, os, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'relay'))
from repositories.engagement_store import from_environment as _engagement_from_environment
from repositories.status_notification_store import from_environment as _notification_from_environment
env_path = PROJECT_ROOT / 'bot' / '.env'
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

BOT_TOKEN  = os.getenv('BOT_TOKEN')
DB_PATH    = os.getenv('DB_PATH', '/root/exchange.db')
CHANNEL_ID = os.getenv('CHANNEL_ID', '')
CHECK_INTERVAL = 20
IMG_SUCCESS = str(PROJECT_ROOT / 'bot' / 'images' / 'success.png')
_engagement = _engagement_from_environment(sqlite_path=DB_PATH)
_notifications = _notification_from_environment(sqlite_path=DB_PATH)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[logging.FileHandler(os.getenv('NOTIFIER_LOG_PATH',
                                            str(Path(__file__).resolve().parent / 'notifier.log'))),
              logging.StreamHandler(sys.stdout)]
)

def notify_user(user_id, text, reply_markup=None):
    if not BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Failed to notify user {user_id}: {e}")

def notify_user_photo(user_id, photo_path, caption, reply_markup=None):
    if not BOT_TOKEN:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        data = {"chat_id": user_id, "caption": caption, "parse_mode": "HTML"}
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        with open(photo_path, 'rb') as photo:
            resp = requests.post(url, data=data, files={'photo': photo}, timeout=20)
        if not resp.ok:
            logging.error(f"sendPhoto failed for user {user_id}: {resp.text}")
            return False
        return True
    except Exception as e:
        logging.error(f"Failed to send photo to user {user_id}: {e}")
        return False

def _post_deal_to_channel(order_id, rub_amount, currency):
    """Публикует анонимную запись о завершённом обмене в канал."""
    if not BOT_TOKEN or not CHANNEL_ID:
        return
    cur_emoji = {'BTC': '₿', 'LTC': 'Ł', 'USDT': '💵'}.get(currency, currency)
    amt_fmt = f"{int(rub_amount):,}".replace(',', ' ')
    text = (
        f"✅ <b>Обмен выполнен</b>\n"
        f"{amt_fmt} ₽ → {cur_emoji} {currency}\n\n"
        f"🟣 @Obsidian666999bot"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        logging.warning(f"Не удалось запостить сделку #{order_id} в канал: {e}")


def process_notifications():
    cur_emoji = {'BTC': '₿', 'LTC': 'Ł', 'USDT': '💵 USDT'}

    # ── paid: оплата подтверждена провайдером ──────────────────────────────
    for row in _notifications.pending("paid", limit=10):
        oid, uid = row["order_id"], row["user_id"]
        amt, curr = row["rub_amount"], row["currency"]
        icon = cur_emoji.get(curr, curr)
        amt_fmt = f"{int(amt):,}".replace(',', ' ')
        text = (
            f"✅ <b>Оплата по заявке #{oid} подтверждена</b>\n\n"
            f"Сумма: <b>{amt_fmt} ₽</b> → {icon} {curr}\n\n"
            f"⏳ Заявка принята в обработку. Отправим {curr} в течение 5–15 минут."
        )
        notify_user(uid, text)
        _notifications.complete(oid, "paid")
        logging.info(f"Sent paid notification for order #{oid}")

    # ── sent: выплата выполнена ────────────────────────────────────────────
    for row in _notifications.pending("sent", limit=10):
        oid, uid = row["order_id"], row["user_id"]
        amt, curr, tx = row["rub_amount"], row["currency"], row["paid_btc_tx"]
        icon = cur_emoji.get(curr, curr)
        amt_fmt = f"{int(amt):,}".replace(',', ' ')
        text = (
            f"🚀 <b>Заявка #{oid} выполнена!</b>\n\n"
            f"{amt_fmt} ₽ → {icon} {curr} отправлен на ваш адрес."
        )
        if tx and not tx.startswith("http"):
            text += f"\n\n🔗 TXID: <code>{tx}</code>"
        elif tx and tx.startswith("http"):
            text += f"\n\n🔗 <a href=\"{tx}\">Транзакция в блокчейне</a>"
        text += "\n\n<b>Оцените, пожалуйста, качество обслуживания:</b>"
        _engagement.ensure_review(oid, uid)
        rate_kb = {
            "inline_keyboard": [[
                {"text": "😞 1", "callback_data": f"rate_{oid}_1"},
                {"text": "😐 2", "callback_data": f"rate_{oid}_2"},
                {"text": "🙂 3", "callback_data": f"rate_{oid}_3"},
                {"text": "😊 4", "callback_data": f"rate_{oid}_4"},
                {"text": "🤩 5", "callback_data": f"rate_{oid}_5"},
            ]]
        }
        if os.path.exists(IMG_SUCCESS) and len(text) <= 1024:
            if not notify_user_photo(uid, IMG_SUCCESS, text, reply_markup=rate_kb):
                notify_user(uid, text, reply_markup=rate_kb)
        else:
            notify_user(uid, text, reply_markup=rate_kb)
        _notifications.complete(oid, "sent")
        logging.info(f"Sent sent notification for order #{oid}")
        # Пост в публичный канал (анонимно)
        if CHANNEL_ID:
            _post_deal_to_channel(oid, amt, curr)

if __name__ == "__main__":
    logging.info("Status notifier started")
    while True:
        try:
            process_notifications()
        except Exception as e:
            logging.exception("Error in notifier loop")
        time.sleep(CHECK_INTERVAL)
