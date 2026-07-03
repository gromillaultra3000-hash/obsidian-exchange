import httpx, json, asyncio

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2:1.5b"

SYSTEM_PROMPT = """Ты — помощник криптовалютного обменника ObsidianExchange.
Отвечай СТРОГО по теме обменника. Будь краток (2-4 предложения). Отвечай на том же языке, что и вопрос.

Факты об ObsidianExchange:
- Обмен: RUB → BTC, LTC, USDT (TRC20)
- Оплата: СБП, карта (без KYC, без документов)
- Комиссия: 27% (до 10к), 25% (10-30к), 23% (30-100к), 19% (от 100к). USDT: 2%
- Минимум: 1000 ₽, максимум: 500 000 ₽
- Время выплаты: 5-15 минут после оплаты
- Поддержка: @ObsidianExchangeSupport
- Бот: @Obsidian666999bot
- Реферальная программа: 0.5% от каждого обмена реферала

Если вопрос не касается обменника — вежливо откажись отвечать."""

async def ask_ai(question: str, stream: bool = False):
    """Returns answer string or async generator for streaming"""
    payload = {
        "model": MODEL,
        "prompt": question,
        "system": SYSTEM_PROMPT,
        "stream": stream,
        "options": {"temperature": 0.3, "num_predict": 200}
    }
    if not stream:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(OLLAMA_URL, json=payload)
            r.raise_for_status()
            return r.json().get("response", "")
    else:
        async def gen():
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream("POST", OLLAMA_URL, json=payload) as r:
                    async for line in r.aiter_lines():
                        if line:
                            try:
                                d = json.loads(line)
                                if d.get("response"):
                                    yield d["response"]
                                if d.get("done"):
                                    break
                            except Exception:
                                pass
        return gen()
