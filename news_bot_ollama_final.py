import feedparser
import requests
import os
import json
import time
import random
import re
import html as html_module
from bs4 import BeautifulSoup

RSS_FEEDS = [
    "https://forklog.com/feed/",
    "https://coinspot.io/feed/",
    "https://incrypted.com/feed/",
    "https://ru.beincrypto.com/feed/",
    "https://bitnovosti.com/feed/",
    "https://news.bitcoin.com/feed/",
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://beincrypto.com/feed/",
]
FEEDS_PER_RUN = 5
ENTRIES_PER_FEED = 3
MAX_POSTS_PER_RUN = 3

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"
OLLAMA_TIMEOUT = 120
SENT_FILE = "/root/sent_news_final.json"

ALLOWED_TAGS = {"b", "i", "u", "s", "a", "code", "pre"}

PROMPT_TEMPLATES = [
    # Разбор новости
    """Ты — крипто-аналитик канала ObsidianExchange. Кратко разбери новость для аудитории трейдеров и разработчиков: что произошло и почему это важно. Тон — экспертный, без снобизма, можно с лёгким юмором. Эмодзи (🔥💎📉🧠) только для акцента. До 350 символов. Используй HTML-теги <b> и <a href='{link}'>...</a> для ссылки на источник.

Заголовок: {title}
Содержание: {summary}

Напиши только разбор новости, без приветствий, подписей и призывов к действию.""",
    # Хот-тейк
    """Ты — автор канала ObsidianExchange с резким, но уважительным мнением. Дай свой "хот-тейк" по новости — согласен ты с трендом или нет, и почему. Сленг в меру (хайп, памп, дамп, кошель), эмодзи для акцента. До 350 символов. HTML-теги <b> и <a href='{link}'>...</a>.

Заголовок: {title}
Содержание: {summary}

Напиши только мнение по новости, без приветствий и призывов к действию.""",
    # Факт дня
    """Ты ведёшь рубрику "Крипто-факт" в канале ObsidianExchange. Преврати новость в интересный факт или наблюдение для читателей. Стиль лаконичный, познавательный, эмодзи 🧠💡. До 300 символов. HTML-теги <b> и <a href='{link}'>...</a>.

Заголовок: {title}
Содержание: {summary}

Напиши только сам факт или наблюдение, без приветствий и призывов к действию.""",
    # Что это значит для трейдера
    """Ты — практик-трейдер, ведёшь канал ObsidianExchange. Объясни, что эта новость означает на практике для трейдера или держателя крипты — как это может повлиять на курс или стратегию. До 350 символов, по делу, эмодзи 📈📉. HTML-теги <b> и <a href='{link}'>...</a>.

Заголовок: {title}
Содержание: {summary}

Напиши только практический разбор, без приветствий и призывов к действию.""",
    # За и против
    """Ты ведёшь рубрику "За и против" в канале ObsidianExchange. По новости коротко опиши один плюс и один минус/риск для крипто-рынка или конкретного актива. Формат: строка с "✅ ..." и строка с "⚠️ ...". До 350 символов. HTML-теги <b> и <a href='{link}'>...</a>.

Заголовок: {title}
Содержание: {summary}

Напиши только "за" и "против", без приветствий и призывов к действию.""",
]

CTA_POOL = [
    "💱 Меняй крипту без KYC на ObsidianExchange — быстро и безопасно.",
    "⚡ На ObsidianExchange курс фиксируется на 15 минут — успей обменять по выгодному курсу.",
    "🔒 Без верификации, с автовыплатой за минуты — ObsidianExchange.",
    "👥 Загляни в реферальную программу ObsidianExchange — получай % с каждого приглашённого друга.",
]

QUESTION_POOL = [
    "Как вам новость — пишите в комментариях 👇",
    "Согласны с таким прогнозом? Обсудим в комментах!",
    "Какие темы хотите видеть в канале чаще?",
    "Бычий или медвежий сигнал, по-вашему?",
]


def load_sent():
    if not os.path.exists(SENT_FILE):
        return set()
    with open(SENT_FILE, 'r') as f:
        return set(json.load(f))


def save_sent(sent):
    with open(SENT_FILE, 'w') as f:
        json.dump(list(sent), f)


def clean_html(text):
    """Убирает HTML-теги/сущности из текста RSS (например <img>, <a>) перед отправкой в промпт."""
    if not text:
        return ""
    text = html_module.unescape(text)
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_telegram_html(text):
    """Вырезает все HTML-теги, кроме разрешённых Telegram, чтобы sendMessage не падал с 400."""
    if not text:
        return text

    def repl(m):
        inner = m.group(1)
        tag_name = inner.lstrip('/').split()[0].lower() if inner.strip() else ''
        if tag_name in ALLOWED_TAGS:
            return m.group(0)
        return ""

    return re.sub(r"<(/?[a-zA-Z][^>]*)>", repl, text)


def fetch_news():
    news = []
    feeds = random.sample(RSS_FEEDS, min(FEEDS_PER_RUN, len(RSS_FEEDS)))
    for url in feeds:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"Feed error {url}: {e}")
            continue
        for entry in feed.entries[:ENTRIES_PER_FEED]:
            news.append({
                "title": clean_html(entry.get("title", "")),
                "link": entry.get("link", ""),
                "summary": clean_html(entry.get("summary", ""))[:400]
            })
    random.shuffle(news)
    return news


def summarize_ollama(title, summary, link):
    template = random.choice(PROMPT_TEMPLATES)
    prompt = template.format(title=title, summary=summary, link=link)
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        text = r.json()["response"].strip()
        return sanitize_telegram_html(text)
    except Exception as e:
        print(f"Ollama error: {e}")
        return None


def send_telegram_with_buttons(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "👍 Полезно", "callback_data": "like"},
                {"text": "🤔 Спорно", "callback_data": "dispute"},
                {"text": "💡 Идея", "callback_data": "idea"}
            ]
        ]
    }
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Telegram error: {r.status_code} {r.text}")
            return False
        return True
    except Exception as e:
        print(f"Telegram error: {e}")
        return False


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
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"Poll error: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Poll error: {e}")


def main():
    sent = load_sent()
    news = fetch_news()
    new = [n for n in news if n['link'] and n['link'] not in sent]
    if not new:
        print("Новых новостей нет")
        return

    poll_questions = [
        "Как тебе эта новость?",
        "Что думаешь о перспективах?",
        "Твой настрой на текущую ситуацию?",
        "Какое влияние окажет эта новость на рынок?"
    ]
    poll_options = [
        ["🔥 Позитивно", "📉 Негативно", "🤔 Нейтрально", "💎 Ждём пампа"],
        ["🐂 Бычий", "🐻 Медвежий", "🦀 Консолидация", "🤷‍♂️ Всё равно"],
        ["👍 Инсайт", "👎 Фейк", "😎 Ожидаемо", "🚀 Только вверх"],
        ["Сильное", "Слабое", "Никакого", "Пока не ясно"]
    ]

    posted = 0
    for item in new:
        if posted >= MAX_POSTS_PER_RUN:
            break
        print(f"Обрабатываю: {item['title']}")
        body = summarize_ollama(item['title'], item['summary'], item['link'])
        if not body:
            body = (f"<b>{item['title']}</b>\n\n{item['summary']}\n\n"
                    f"👉 <a href='{item['link']}'>Читать полностью</a>")
        question = random.choice(QUESTION_POOL)
        cta = random.choice(CTA_POOL)
        post = f"{body}\n\n{question}\n{cta}"

        if send_telegram_with_buttons(post):
            posted += 1
            sent.add(item['link'])
            if random.random() < 0.3:
                q = random.choice(poll_questions)
                opts = random.choice(poll_options)
                time.sleep(4)
                send_poll(q, opts)
            time.sleep(2)
        else:
            # Не получилось отправить — не помечаем как отправленное, попробуем в следующий раз
            continue

    save_sent(sent)
    print(f"Опубликовано {posted} новостей")


if __name__ == "__main__":
    main()
