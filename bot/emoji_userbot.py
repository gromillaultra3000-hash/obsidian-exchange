#!/usr/bin/env python3
"""Юзербот (премиум-аккаунт): накладывает кастом-эмодзи ObsidanEmoji на посты бота в канале.

Bot API вырезает custom_emoji entities у ботов без Fragment-юзернейма, поэтому бот
публикует пост с обычными fallback-эмодзи, а этот скрипт от премиум-аккаунта
(админ канала с правом редактирования) редактирует пост и добавляет
MessageEntityCustomEmoji ПОВЕРХ тех же символов — текст и остальное
форматирование (bold, blockquote) не меняются.

Ищется брендовая строка-последовательность (O B S I D I A N EX фолбэками):
🔮💜💎⚡🌑⚡🟣✨💫 — она строится из /root/bot/images/stickers/emoji_ids.json,
та же строка должна стоять в тексте поста бота (см. _PROMO_POST_HTML в main_bot.py).

Команды:
  python3 emoji_userbot.py login        первичная авторизация (интерактивно: телефон + код)
  python3 emoji_userbot.py edit <id>    разово отредактировать пост <id> в CHANNEL_ID
  python3 emoji_userbot.py watch        демон: авто-редактирование новых постов канала

Ключи в /root/bot/.env: TG_API_ID / TG_API_HASH (my.telegram.org, аккаунт с Premium),
CHANNEL_ID. Сессия: /root/bot/premium_userbot.session
"""
import asyncio
import json
import pathlib
import sys

from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityCustomEmoji

BASE = pathlib.Path(__file__).resolve().parent
SESSION = str(BASE / "premium_userbot")
EMOJI_IDS = BASE / "images" / "stickers" / "emoji_ids.json"

# Порядок букв бренд-строки (I используется дважды: OBSIDIAN)
LETTER_SEQ = ["O", "B", "S", "I", "D", "I", "A", "N", "EX"]


def load_env(path=BASE / ".env"):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def load_brand_sequence():
    """Возвращает (строка fallback-эмодзи, [custom_emoji_id, ...]) в порядке LETTER_SEQ."""
    data = json.loads(EMOJI_IDS.read_text())
    chars, ids = [], []
    for letter in LETTER_SEQ:
        item = data[letter]
        chars.append(item["fallback"])
        ids.append(int(item["emoji_id"]))
    return "".join(chars), ids


def utf16_units(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def build_entities(text: str):
    """Ищет бренд-строку в text, возвращает список MessageEntityCustomEmoji или []."""
    seq, ids = load_brand_sequence()
    idx = text.find(seq)
    if idx < 0:
        return []
    offset = utf16_units(text[:idx])
    entities = []
    for ch, emoji_id in zip(seq, ids):
        ln = utf16_units(ch)
        entities.append(MessageEntityCustomEmoji(offset=offset, length=ln, document_id=emoji_id))
        offset += ln
    return entities


async def apply_emoji(client, channel, msg):
    if any(isinstance(e, MessageEntityCustomEmoji) for e in (msg.entities or [])):
        return "уже с кастом-эмодзи, пропуск"
    new = build_entities(msg.message or "")
    if not new:
        return "бренд-строка не найдена, пропуск"
    combined = list(msg.entities or []) + new
    await client.edit_message(channel, msg.id, msg.message,
                              formatting_entities=combined, link_preview=False)
    return f"OK: наложено {len(new)} кастом-эмодзи"


async def main():
    env = load_env()
    api_id = int(env.get("TG_API_ID") or 0)
    api_hash = env.get("TG_API_HASH") or ""
    channel_id = int(env.get("CHANNEL_ID") or 0)
    if not api_id or not api_hash:
        sys.exit("Заполни TG_API_ID и TG_API_HASH в /root/bot/.env (my.telegram.org → API development tools)")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "watch"
    client = TelegramClient(SESSION, api_id, api_hash)

    if cmd == "login":
        await client.start()  # интерактивно спросит телефон и код
        me = await client.get_me()
        print(f"Авторизован: {me.first_name} (@{me.username}, id={me.id}, premium={me.premium})")
        if not me.premium:
            print("⚠️ У аккаунта НЕТ Premium — кастом-эмодзи отправить не получится!")
        await client.disconnect()
        return

    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Сессия не авторизована — сначала: python3 emoji_userbot.py login")

    channel = await client.get_entity(channel_id)

    if cmd == "edit":
        msg_id = int(sys.argv[2])
        msg = await client.get_messages(channel, ids=msg_id)
        if not msg:
            sys.exit(f"Сообщение {msg_id} не найдено в {channel_id}")
        print(await apply_emoji(client, channel, msg))
        await client.disconnect()
        return

    if cmd == "watch":
        print(f"Слежу за каналом {channel_id}, жду посты с бренд-строкой…")

        @client.on(events.NewMessage(chats=channel))
        async def handler(event):
            try:
                await asyncio.sleep(1)  # дать Telegram доставить пост целиком
                result = await apply_emoji(client, channel, event.message)
                print(f"пост {event.message.id}: {result}")
            except Exception as e:
                print(f"пост {event.message.id}: ошибка {e}")

        await client.run_until_disconnected()
        return

    sys.exit(f"Неизвестная команда: {cmd} (login | edit <id> | watch)")


if __name__ == "__main__":
    asyncio.run(main())
