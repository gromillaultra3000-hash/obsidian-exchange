import feedparser
import requests
import os
import json
import time

# ----- НАСТРОЙКИ -----
RSS_FEEDS = [
    "https://bits.media/feed/",
    "https://cryptonnews.ru/feed/",
    "https://forklog.com/feed/",
    "https://vc.ru/crypto/rss"
]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2:7b"  # измените на свою модель

SENT_FILE = "/root/sent_news.json"
# --------------------

def load_sent():
    if not os.path.exists(SENT_FILE):
        return set()
    with open(SENT_FILE, 'r') as f:
        return set(json.load(f))

def save_sent(sent):
    with open(SENT_FILE, 'w') as f:
        json.dump(list(sent), f)

def fetch_news():
    news = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:2]:  # по 2 свежие с каждого источника
            news.append({
                "title": entry.title,
                "link": entry.link,
                "summary": entry.get("summary", "")[:300]
            })
    return news

def summarize_with_ollama(title, summary, link):
    prompt = f"""
Ты — крипто-журналист для канала ObsidianExchange.
Аудитория — зумеры и программисты. Напиши краткий пост (до 200 символов) в стиле "пацанские криптоновости" с эмодзи.
Новость: {title}
Подробности: {summary}
Ссылка: {link}
Напиши пост:
"""
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["response"].strip()
    except Exception as e:
        print(f"Ollama error: {e}")
        return None

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram error: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    sent = load_sent()
    news = fetch_news()
    new = [n for n in news if n['link'] not in sent]
    if not new:
        print("Новых новостей нет")
        return
    for item in new:
        print(f"Обрабатываю: {item['title']}")
        post = summarize_with_ollama(item['title'], item['summary'], item['link'])
        if post:
            send_telegram(post)
            sent.add(item['link'])
            time.sleep(3)
    save_sent(sent)
    print(f"Опубликовано {len(new)} новостей")

if __name__ == "__main__":
    main()
