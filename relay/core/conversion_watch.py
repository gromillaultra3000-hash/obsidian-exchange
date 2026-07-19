"""Сторож конверсии: ловит «реквизиты выдаём, а денег нет».

Зачем. 19.07.2026 выяснилось, что фоновый поток убивал платёжные сессии на 15-й
минуте из 30: клиент терял кнопку «я оплатил», оплата уходила трейдеру, провайдер
её не видел. Так утекло 260 сессий из 426 за месяц — и никто не заметил, потому
что всё выглядело штатно: заявки создаются, реквизиты выдаются, ошибок в логах нет.
Тишина — самый дорогой вид сбоя, поэтому её нужно измерять отдельно.

Сигналы (каждый — свой независимый симптом):
  no_payments   — реквизиты выдавали, оплат нет вообще (главный)
  early_expiry  — сессии закрываются раньше своего expires_at (регрессия того бага)

Порог намеренно по КОЛИЧЕСТВУ выдач, а не по проценту: при 2-3 заявках ноль оплат
статистически нормален, при 8 — уже нет.
"""
from __future__ import annotations
import os
import sqlite3

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

WINDOW_HOURS = int(os.getenv("CONV_WATCH_WINDOW_HOURS", "3") or 3)
MIN_ISSUED = int(os.getenv("CONV_WATCH_MIN_ISSUED", "8") or 8)
EARLY_EXPIRY_MIN = int(os.getenv("CONV_WATCH_EARLY_EXPIRY_MIN", "3") or 3)


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def check_conversion(window_hours: int | None = None) -> dict:
    """Считает симптомы за окно. Ничего не шлёт — только факты."""
    h = window_hours or WINDOW_HOURS
    win = f"-{h} hours"
    out = {"window_hours": h, "alerts": [], "issued": 0, "paid": 0, "early_expiry": 0}
    try:
        with _db() as conn:
            out["issued"] = conn.execute(
                "SELECT COUNT(*) c FROM payment_sessions WHERE created_at >= datetime('now', ?)",
                (win,)).fetchone()["c"]
            # оплату считаем по orders: payment_sessions.status в 'paid' не переводится
            out["paid"] = conn.execute(
                "SELECT COUNT(*) c FROM orders WHERE status IN ('paid','sent') "
                "AND updated_at >= datetime('now', ?)", (win,)).fetchone()["c"]
            # сессия закрыта раньше собственного срока — признак возврата бага
            out["early_expiry"] = conn.execute(
                "SELECT COUNT(*) c FROM payment_sessions WHERE status='expired' "
                "AND created_at >= datetime('now', ?) AND expires_at IS NOT NULL "
                "AND updated_at IS NOT NULL AND updated_at < expires_at", (win,)).fetchone()["c"]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    if out["issued"] >= MIN_ISSUED and out["paid"] == 0:
        out["alerts"].append({
            "kind": "no_payments",
            "text": (f"Реквизиты выдавали {out['issued']} раз за {h} ч — оплат НЕТ ни одной. "
                     f"Проверить: доходит ли клиент до кнопки «я оплатил», живы ли сессии "
                     f"полный срок, не сломана ли страница оплаты."),
        })
    if out["early_expiry"] >= EARLY_EXPIRY_MIN:
        out["alerts"].append({
            "kind": "early_expiry",
            "text": (f"{out['early_expiry']} сессий закрылись РАНЬШЕ своего expires_at за {h} ч. "
                     f"Это регрессия бага от 19.07 (сессии убивались на 15-й минуте из 30)."),
        })
    return out


def format_alert(res: dict) -> str:
    """Готовое сообщение для Telegram или '' — если поводов нет."""
    if not res.get("alerts"):
        return ""
    head = (f"🚨 <b>Конверсия: тихий сбой</b>\n\n"
            f"<blockquote>Окно: {res['window_hours']} ч\n"
            f"Выдано реквизитов: <b>{res['issued']}</b>\n"
            f"Оплачено: <b>{res['paid']}</b></blockquote>\n")
    return head + "\n" + "\n\n".join("• " + a["text"] for a in res["alerts"])
