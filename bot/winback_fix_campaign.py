#!/usr/bin/env python3
"""Разовая кампания: вернуть клиентов, пострадавших от бага сессий (19.07.2026).

Кому. Тем, у кого заявка истекла, а платёжная сессия была закрыта РАНЬШЕ срока
(подпись бага: updated_at == created_at — тот UPDATE не трогал updated_at).
Это люди, которые дошли до реквизитов и начали платить, а система убрала у них
кнопку «я оплатил» на половине срока.

Почему честно, а не «вот вам скидка». Часть этих людей МОГЛА перевести деньги в
мёртвом окне: провайдер платёж не увидел, крипту они не получили. Умолчать об
этом нельзя — в тексте прямо предлагается написать, если так вышло.

Запуск:
    python3 winback_fix_campaign.py            # сухой прогон, никому не пишет
    python3 winback_fix_campaign.py --send     # реальная отправка
Повторно тем же людям не пишет (sent_notifications, event='fix_apology_2607').
"""
import os
import sys
import asyncio
import sqlite3
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv

load_dotenv("/root/bot/.env")
DB = os.getenv("DB_PATH", "/root/exchange.db")
EVENT = "fix_apology_2607"
BOT_USERNAME = os.getenv("BOT_USERNAME", "Obsidian666999bot")

TEXT = (
    "🔧 <b>Мы нашли ошибку у себя — и починили её</b>\n\n"
    "Вы создавали заявку на обмен, но оплата не завершилась. "
    "Причина была на нашей стороне, не на вашей: страница оплаты закрывалась "
    "<b>вдвое раньше срока</b> — реквизиты выдавались на 30 минут, "
    "а кнопка подтверждения пропадала уже через 15.\n\n"
    "19 июля мы это исправили. Теперь окно оплаты работает полностью.\n\n"
    "❗️ <b>Если вы успели перевести деньги, но крипту не получили</b> — "
    "напишите нам прямо сейчас. Из-за той же ошибки платёж мог не дойти до "
    "подтверждения. Мы найдём его по чеку и разберёмся.\n\n"
    "Если просто не дошли до оплаты — можно попробовать снова, курс актуальный."
)


def segment(days: int = 45, max_age_days: int | None = None):
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    q = """
        SELECT o.user_id,
               COUNT(DISTINCT o.order_id) AS orders,
               MAX(o.created_at)          AS last_order,
               ROUND(SUM(o.rub_amount))   AS rub,
               CAST(julianday('now') - julianday(MAX(o.created_at)) AS INT) AS age_days
        FROM orders o
        JOIN payment_sessions s ON s.order_id = o.order_id
        WHERE o.status = 'expired' AND o.user_id > 0
          AND s.status = 'expired' AND s.updated_at = s.created_at
          AND o.created_at > date('now', ?)
          AND NOT EXISTS (SELECT 1 FROM sent_notifications sn
                          WHERE sn.order_id = o.order_id AND sn.event = ?)
        GROUP BY o.user_id
        ORDER BY age_days ASC
    """
    rows = [dict(r) for r in conn.execute(q, (f"-{days} days", EVENT)).fetchall()]
    conn.close()
    if max_age_days is not None:
        rows = [r for r in rows if r["age_days"] <= max_age_days]
    return rows


def mark_sent(user_id):
    """Метим ВСЕ подходящие заявки юзера, чтобы не написать ему дважды."""
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("""
        INSERT OR IGNORE INTO sent_notifications (order_id, event)
        SELECT o.order_id, ? FROM orders o
        JOIN payment_sessions s ON s.order_id = o.order_id
        WHERE o.user_id = ? AND o.status='expired'
          AND s.status='expired' AND s.updated_at = s.created_at
    """, (EVENT, user_id))
    conn.commit()
    conn.close()


async def run(send: bool, max_age: int | None, limit: int | None):
    people = segment(max_age_days=max_age)
    if limit:
        people = people[:limit]
    total_rub = sum(p["rub"] or 0 for p in people)
    print(f"Получателей: {len(people)} | заявок: {sum(p['orders'] for p in people)} "
          f"| упущено: {total_rub:,.0f} ₽".replace(",", " "))
    buckets = {"≤7 дней": 0, "8-21": 0, "22+": 0}
    for p in people:
        buckets["≤7 дней" if p["age_days"] <= 7 else
                ("8-21" if p["age_days"] <= 21 else "22+")] += 1
    print("По свежести:", buckets)

    if not send:
        print("\n--- СУХОЙ ПРОГОН, никому не отправлено ---")
        print("Текст сообщения:\n")
        print(TEXT.replace("<b>", "").replace("</b>", ""))
        print("\nЗапустить реально: --send")
        return

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    bot = Bot(os.getenv("BOT_TOKEN"), default=DefaultBotProperties(parse_mode="HTML"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Обменять снова",
                              url=f"https://t.me/{BOT_USERNAME}?start=fixed")],
        [InlineKeyboardButton(text="💬 Я платил, но не получил",
                              url=f"https://t.me/{os.getenv('SUPPORT_BOT', 'ObsidianSupport').lstrip('@')}")],
    ])
    ok = blocked = failed = 0
    for i, p in enumerate(people, 1):
        try:
            await bot.send_message(p["user_id"], TEXT, reply_markup=kb)
            mark_sent(p["user_id"])
            ok += 1
        except Exception as e:
            msg = str(e).lower()
            if "blocked" in msg or "chat not found" in msg or "deactivated" in msg:
                mark_sent(p["user_id"])   # писать больше некому
                blocked += 1
            else:
                failed += 1
                print(f"  ошибка user={p['user_id']}: {type(e).__name__}: {e}")
        if i % 20 == 0:
            print(f"  отправлено {i}/{len(people)}…")
        await asyncio.sleep(0.5)          # бережём лимиты Telegram
    await bot.session.close()
    print(f"\nИтог: доставлено {ok}, заблокировали бота {blocked}, ошибок {failed}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="реально отправить")
    ap.add_argument("--max-age", type=int, default=None, help="только заявки не старше N дней")
    ap.add_argument("--limit", type=int, default=None, help="ограничить число получателей")
    a = ap.parse_args()
    asyncio.run(run(a.send, a.max_age, a.limit))
