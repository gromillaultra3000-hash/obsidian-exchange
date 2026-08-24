import requests, os, logging, threading, time

logger = logging.getLogger(__name__)
BOT_TOKEN = os.getenv('BOT_TOKEN', '')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))

def send_admin_alert(text):
    if not BOT_TOKEN or not ADMIN_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_ID, "text": f"⚠️ ObsidianExchange Alert:\n{text}", "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")

def check_services():
    for name, url in [("WebApp", "https://obsidian-exchange.org/webapp"), ("API", "https://obsidian-exchange.org/api/history?user_id=0")]:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200: send_admin_alert(f"Сервис {name} недоступен! HTTP {r.status_code}")
        except Exception as e: send_admin_alert(f"Ошибка подключения к {name}: {str(e)}")

def start_monitoring():
    def loop():
        while True:
            check_services()
            time.sleep(300)
    threading.Thread(target=loop, daemon=True).start()
    logger.info("Мониторинг запущен")
