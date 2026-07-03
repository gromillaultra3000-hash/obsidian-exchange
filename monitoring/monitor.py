#!/usr/bin/env python3
"""
ObsidianExchange monitoring daemon.
Runs every 5 minutes, checks order health and provider status,
alerts admin via Telegram if anomalies detected.
"""
import asyncio
import sqlite3
import logging
import os
import sys
import httpx
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/root/relay')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
logger = logging.getLogger("monitor")

DB_PATH = "/root/exchange.db"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = os.getenv("ADMIN_ID", "")
CHECK_INTERVAL = int(os.getenv("MONITOR_INTERVAL", "300"))  # 5 min


def load_env():
    """Load variables from bot .env file."""
    env_path = Path("/root/bot/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    global BOT_TOKEN, ADMIN_ID
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    ADMIN_ID = os.environ.get("ADMIN_ID", "")


def db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


async def send_alert(text: str, level: str = "warning"):
    """Send Telegram alert to admin."""
    if not BOT_TOKEN or not ADMIN_ID:
        logger.warning("No BOT_TOKEN/ADMIN_ID configured for alerts")
        return
    emoji = {"warning": "⚠️", "critical": "🚨", "ok": "✅", "info": "ℹ️"}.get(level, "📢")
    msg = (
        f"{emoji} <b>ObsidianExchange Monitor</b>\n\n"
        f"{text}\n\n"
        f"<i>{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</i>"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": ADMIN_ID, "text": msg, "parse_mode": "HTML"},
            )
            if resp.status_code != 200:
                logger.error("Telegram API error %d: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("Alert send failed: %s", e)


async def check_stuck_orders():
    """Find pending orders older than 30 minutes."""
    issues = []
    try:
        with db() as conn:
            stuck = conn.execute("""
                SELECT order_id, currency, rub_amount, created_at FROM orders
                WHERE status='pending'
                AND datetime(created_at) < datetime('now', '-30 minutes')
                AND datetime(created_at) > datetime('now', '-24 hours')
            """).fetchall()
            if stuck:
                issues.append(f"<b>Зависшие заявки ({len(stuck)}):</b>")
                for o in stuck[:5]:
                    try:
                        age_min = int(
                            (datetime.now() - datetime.fromisoformat(o['created_at']))
                            .total_seconds() / 60
                        )
                    except Exception:
                        age_min = "?"
                    issues.append(
                        f"  #{o['order_id']} · {o['currency']} · {o['rub_amount']:.0f}₽ · {age_min} мин"
                    )
                if len(stuck) > 5:
                    issues.append(f"  ... и ещё {len(stuck) - 5}")
    except Exception as e:
        logger.error("check_stuck_orders error: %s", e)
    return issues


async def check_provider_health():
    """Check provider health scores from smart_router."""
    issues = []
    try:
        from services.smart_router import get_health_scores
        scores = get_health_scores()
        unhealthy = [(p, s) for p, s in scores.items() if not s.get("is_healthy")]
        if unhealthy:
            issues.append(f"<b>Нездоровые провайдеры ({len(unhealthy)}):</b>")
            for p, s in unhealthy:
                cooldown_str = " (cooldown)" if s.get("in_cooldown") else ""
                issues.append(f"  {p}: {s['failed_count']} ошибок{cooldown_str}")
    except Exception as e:
        logger.warning("Provider health check failed: %s", e)
    return issues


async def check_conversion_rate():
    """Alert if conversion rate drops below 5% in last hour (min 5 orders)."""
    issues = []
    try:
        with db() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END) as paid
                FROM orders
                WHERE datetime(created_at) > datetime('now', '-1 hour')
            """).fetchone()
            total = row['total'] or 0
            paid = row['paid'] or 0
            if total >= 5:
                rate = paid / total * 100
                if rate < 5:
                    issues.append(
                        f"<b>Низкая конверсия за последний час:</b> {rate:.1f}% ({paid}/{total})"
                    )
    except Exception as e:
        logger.error("check_conversion_rate error: %s", e)
    return issues


async def check_payout_queue():
    """Alert if payout queue has items stuck longer than 20 minutes."""
    issues = []
    try:
        with db() as conn:
            # Check if payout_queue table exists
            tbl = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='payout_queue'"
            ).fetchone()
            if not tbl:
                return issues
            stuck = conn.execute("""
                SELECT COUNT(*) as cnt FROM payout_queue
                WHERE status='new'
                AND datetime(created_at) < datetime('now', '-20 minutes')
            """).fetchone()
            if stuck and stuck['cnt'] > 0:
                issues.append(
                    f"<b>Очередь выплат заморожена:</b> {stuck['cnt']} ждут > 20 мин"
                )
    except Exception as e:
        logger.error("check_payout_queue error: %s", e)
    return issues


async def daily_stats():
    """Send daily summary."""
    try:
        with db() as conn:
            stats = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status IN ('paid','sent') THEN 1 ELSE 0 END) as paid,
                    SUM(CASE WHEN status IN ('paid','sent') THEN rub_amount ELSE 0 END) as volume,
                    COUNT(DISTINCT user_id) as users
                FROM orders
                WHERE date(created_at) = date('now')
            """).fetchone()
            total = stats['total'] or 0
            paid = stats['paid'] or 0
            volume = stats['volume'] or 0
            users = stats['users'] or 0
            conv = (paid / total * 100) if total else 0
            msg = (
                f"<b>Итоги дня</b>\n\n"
                f"Заявок: {total} (успешных: {paid})\n"
                f"Объём: {volume:,.0f} ₽\n"
                f"Конверсия: {conv:.1f}%\n"
                f"Уникальных юзеров: {users}"
            )
        await send_alert(msg, "info")
    except Exception as e:
        logger.error("daily_stats error: %s", e)


_last_daily = None


async def run_checks():
    global _last_daily
    all_issues = []
    all_issues += await check_stuck_orders()
    all_issues += await check_provider_health()
    all_issues += await check_conversion_rate()
    all_issues += await check_payout_queue()

    if all_issues:
        await send_alert("\n".join(all_issues), "warning")
    else:
        logger.info("All checks passed")

    # Daily stats at 09:00 Moscow time (UTC+3)
    now = datetime.utcnow()
    now_msk_hour = (now.hour + 3) % 24
    if now_msk_hour == 9 and now.minute < 10 and _last_daily != now.date():
        _last_daily = now.date()
        await daily_stats()


async def main():
    load_env()
    logger.info("ObsidianExchange Monitor started (interval=%ds)", CHECK_INTERVAL)
    await send_alert("Monitor started", "ok")
    while True:
        try:
            await run_checks()
        except Exception as e:
            logger.error("Check cycle error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
