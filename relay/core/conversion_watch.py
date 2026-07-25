"""Сторож конверсии: ловит «реквизиты выдаём, а денег нет».

Зачем. 19.07.2026 выяснилось, что фоновый поток убивал платёжные сессии на 15-й
минуте из 30: клиент терял кнопку «я оплатил», оплата уходила трейдеру, провайдер
её не видел. Так утекло 260 сессий из 426 за месяц — и никто не заметил, потому
что всё выглядело штатно: заявки создаются, реквизиты выдаются, ошибок в логах нет.
Тишина — самый дорогой вид сбоя, поэтому её нужно измерять отдельно.

Сигналы (каждый — свой независимый симптом):
  no_payments   — реквизиты выдавали, оплат нет вообще (главный)
  early_expiry  — сессии закрываются раньше своего expires_at (регрессия того бага)
  stuck_payout  — клиент оплатил (status=paid), а крипта не отправлена дольше
                  порога: деньги у нас, выдача зависла в ручной очереди
  receipt_undelivered — клиент прислал чек (файл сохранён в order_receipts), но
                  провайдеру он так и НЕ ушёл (receipt_sent_at пуст) дольше
                  порога. Это ядро гарантии «чек обязательно дойдёт до трейдера»:
                  если доставка молча сорвалась (API отказал, группа споров
                  недоступна, у метода нет канала) — сигнал делает сбой громким,
                  пока сделка у провайдера ещё жива и её можно подтвердить.

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
# Сколько минут заявка может лежать оплаченной без отправки крипты, прежде чем
# это считается зависшей выплатой (ручная очередь встала / воркер офлайн).
STUCK_PAYOUT_MIN = int(os.getenv("CONV_WATCH_STUCK_PAYOUT_MIN", "45") or 45)
# Сколько минут чек может лежать доставленным-в-никуда (файл есть, receipt_sent_at
# пуст), прежде чем это тревога. Доставка штатно занимает секунды; 20 минут =
# что-то сорвалось молча, а сделка у провайдера ещё может быть жива.
RECEIPT_UNDELIVERED_MIN = int(os.getenv("CONV_WATCH_RECEIPT_UNDELIVERED_MIN", "20") or 20)


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def check_conversion(window_hours: int | None = None) -> dict:
    """Считает симптомы за окно. Ничего не шлёт — только факты."""
    h = window_hours or WINDOW_HOURS
    win = f"-{h} hours"
    out = {"window_hours": h, "alerts": [], "issued": 0, "paid": 0, "early_expiry": 0,
           "stuck_payouts": [], "undelivered_receipts": []}
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
            # оплачено клиентом, но крипта не отправлена дольше порога — деньги у
            # нас, клиент ждёт выдачу. Окно тут НЕ применяем: зависшая выплата
            # опасна независимо от того, когда была оплата.
            # updated_at IS NULL = древняя оплата без отметки времени: сравнение
            # NULL <= datetime(...) даёт NULL (строка молча выпадает), поэтому такую
            # выплату считаем ЗАВИСШЕЙ безусловно, а возраст меряем от created_at.
            out["stuck_payouts"] = [dict(r) for r in conn.execute(
                "SELECT order_id, rub_amount, currency, "
                "  CAST((julianday('now')-julianday(COALESCE(updated_at,created_at)))*24*60 AS INT) age_min "
                "FROM orders WHERE status='paid' "
                "AND (paid_btc_tx IS NULL OR paid_btc_tx='') "
                "AND (updated_at IS NULL OR updated_at <= datetime('now', ?)) "
                "ORDER BY COALESCE(updated_at, created_at)",
                (f"-{STUCK_PAYOUT_MIN} minutes",)).fetchall()]
            # Чек залит, но провайдеру НЕ ушёл (receipt_sent_at пуст) дольше
            # порога. Только по сделкам, что ещё требуют подтверждения — по
            # выданной крипте (sent) и отменённым оператором (cancelled) уже
            # неважно. order_receipts/receipt_sent_at могут отсутствовать в
            # совсем старой БД — оборачиваем отдельно, чтобы не глушить весь чек.
            try:
                out["undelivered_receipts"] = [dict(r) for r in conn.execute(
                    "SELECT o.order_id, o.rub_amount, o.currency, o.status, "
                    "  COALESCE(ps.provider,'?') provider, "
                    "  CAST((julianday('now')-julianday(r.created_at))*24*60 AS INT) age_min "
                    "FROM order_receipts r JOIN orders o ON o.order_id=r.order_id "
                    "LEFT JOIN payment_sessions ps ON ps.id=("
                    "  SELECT id FROM payment_sessions WHERE order_id=o.order_id ORDER BY id DESC LIMIT 1) "
                    "WHERE (o.receipt_sent_at IS NULL OR o.receipt_sent_at='') "
                    "AND o.status NOT IN ('sent','cancelled') "
                    "AND r.created_at <= datetime('now', ?) "
                    # только пока случай ещё actionable: сделка у провайдера жива
                    # часы, не дни. Древние expired-жертвы уже не спасти — не нудим.
                    "AND r.created_at >= datetime('now','-24 hours') "
                    "ORDER BY r.created_at",
                    (f"-{RECEIPT_UNDELIVERED_MIN} minutes",)).fetchall()]
            except sqlite3.OperationalError:
                out["undelivered_receipts"] = []
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
    if out["stuck_payouts"]:
        lst = ", ".join(f"#{p['order_id']} ({p['rub_amount']:g} ₽ → {p['currency']}, "
                        f"{p['age_min']} мин)" for p in out["stuck_payouts"][:8])
        out["alerts"].append({
            "kind": "stuck_payout",
            "text": (f"{len(out['stuck_payouts'])} заявок оплачено, но крипта НЕ отправлена "
                     f">{STUCK_PAYOUT_MIN} мин: {lst}. Деньги у нас — выдать вручную "
                     f"(/worker) или проверить, не завис ли авто-payout."),
        })
    if out["undelivered_receipts"]:
        lst = ", ".join(f"#{p['order_id']} ({p['rub_amount']:g} ₽, {p['provider']}, "
                        f"{p['age_min']} мин)" for p in out["undelivered_receipts"][:8])
        out["alerts"].append({
            "kind": "receipt_undelivered",
            "text": (f"{len(out['undelivered_receipts'])} чеков залито клиентом, но "
                     f"провайдеру НЕ доставлено >{RECEIPT_UNDELIVERED_MIN} мин: {lst}. "
                     f"Передать чек трейдеру вручную в кабинете/группе провайдера, "
                     f"ПОКА сделка на их стороне жива — иначе оплату не подтвердят."),
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
