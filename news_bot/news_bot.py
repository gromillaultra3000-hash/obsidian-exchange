import feedparser
import requests
import os
import json

# Список RSS-лент
RSS_FEEDS = [
    "https://cointelegraph.com/feed",
    "https://decrypt.co/feed",
    "https://bitcoinmagazine.com/.rss"
]

# Переменные окружения (будут подставлены из GitHub Secrets)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Файл для хранения отправленных новостей
SENT_NEWS_FILE = "sent_news.json"

def load_sent_news():
    if not os.path.exists(SENT_NEWS_FILE):
        return set()
    with open(SENT_NEWS_FILE, 'r') as f:
        return set(json.load(f))

def save_sent_news(sent_ids):
    with open(SENT_NEWS_FILE, 'w') as f:
        json.dump(list(sent_ids), f)

def fetch_news():
    all_news = []
    for url in RSS_FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries[:5]:
            all_news.append({
                "title": entry.title,
                "link": entry.link
            })
    return all_news

def summarize_with_gemini(news_items):
    # Формируем промпт
    prompt = "Напиши краткий дайджест новостей в дружелюбном, экспертном тоне на русском языке. Используй эмодзи для разделения. Новости:\n\n"
    for item in news_items:
        prompt += f"* {item['title']} - {item['link']}\n"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"Gemini error: {e}")
        return None

def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def main():
    sent = load_sent_news()
    news = fetch_news()
    new_news = [n for n in news if n['link'] not in sent]
    if not new_news:
        print("No new news")
        return
    post = summarize_with_gemini(new_news)
    if post:
        send_to_telegram(post)
        new_ids = {n['link'] for n in new_news}
        save_sent_news(sent.union(new_ids))
        print(f"Published {len(new_news)} news")
    else:
        print("Failed to generate post")

if __name__ == "__main__":
    main()
