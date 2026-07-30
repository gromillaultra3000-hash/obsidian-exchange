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
  receipt_unresolved — чек ДОШЁЛ до провайдера, а решения так и нет: заявка не
                  стала ни paid, ни sent, ни cancelled. Такую заявку держит
                  Слой 0 (cleanup_expired_orders не истекает заявки с чеком —
                  и правильно делает), и в /review её видно. Но /review — это
                  витрина, куда надо прийти САМОМУ: единственное толкающее
                  уведомление даёт dispute_watch, а оно разовое (_mark_opened
                  навсегда убирает заявку из выборки). Не пришёл — тишина.
                  30.07.2026 так висели 22 заявки на 99 400 ₽ — до 13 часов,
                  с деньгами клиента.

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
# Сколько минут заявка с ДОШЕДШИМ чеком может стоять без решения. Порог больше
# срока автоспора (DISPUTE_AFTER_MIN=25) плюс время на ответ трейдера: раньше
# сигналить значит дублировать спор, который и так открывается сам.
RECEIPT_UNRESOLVED_MIN = int(os.getenv("CONV_WATCH_RECEIPT_UNRESOLVED_MIN", "90") or 90)
# Докуда назад смотрим по нерешённым чекам. Дольше суток такие заявки копятся
# (сделка у провайдера уже мертва), но деньги клиента реальны и решение по ним
# всё равно принимает человек — поэтому окно шире, чем у недоставленных.
RECEIPT_UNRESOLVED_DAYS = int(os.getenv("CONV_WATCH_RECEIPT_UNRESOLVED_DAYS", "7") or 7)


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def check_conversion(window_hours: int | None = None) -> dict:
    """Считает симптомы за окно. Ничего не шлёт — только факты."""
    h = window_hours or WINDOW_HOURS
    win = f"-{h} hours"
    out = {"window_hours": h, "alerts": [], "issued": 0, "paid": 0, "early_expiry": 0,
           "stuck_payouts": [], "undelivered_receipts": [], "unresolved_receipts": []}
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
            # Чек есть, а решения по заявке нет. Гоняться за доставкой чека — дело
            # соседнего симптома, и пока он этим занят (первые сутки), дублировать
            # его не нужно: одна беда, звучащая дважды, приучает игнорировать обе.
            # А вот ПОСЛЕ его окна недоставленный чек обязан всплыть здесь, иначе
            # худший случай — деньги у трейдера, чек у нас, сделка у провайдера
            # мертва — навсегда исчезал из обоих. Заявка в expired/cancelled тоже
            # берётся: закрытый статус не возвращает клиенту деньги.
            # Возраст считаем от чека: именно с этого момента клиент считает, что
            # заплатил.
            already = {p["order_id"] for p in out["undelivered_receipts"]}
            try:
                rows = [dict(r) for r in conn.execute(
                    "SELECT o.order_id, o.rub_amount, o.currency, o.status, "
                    "  (o.receipt_sent_at IS NOT NULL AND o.receipt_sent_at<>'') delivered, "
                    "  COALESCE(ps.provider,'?') provider, "
                    "  CAST((julianday('now')-julianday(r.created_at))*24*60 AS INT) age_min "
                    "FROM order_receipts r JOIN orders o ON o.order_id=r.order_id "
                    "LEFT JOIN payment_sessions ps ON ps.id=("
                    "  SELECT id FROM payment_sessions WHERE order_id=o.order_id ORDER BY id DESC LIMIT 1) "
                    "WHERE o.status NOT IN ('paid','sent') "
                    # Отклонённое оператором — решённое: тревожить о нём значит
                    # звать человека посмотреть на собственное решение.
                    "AND NOT EXISTS (SELECT 1 FROM sent_notifications sn "
                    "                WHERE sn.order_id=o.order_id AND sn.event='receipt_rejected') "
                    "AND r.created_at <= datetime('now', ?) "
                    "AND r.created_at >= datetime('now', ?) "
                    "ORDER BY r.created_at",
                    (f"-{RECEIPT_UNRESOLVED_MIN} minutes",
                     f"-{RECEIPT_UNRESOLVED_DAYS} days")).fetchall()]
                out["unresolved_receipts"] = [r for r in rows if r["order_id"] not in already]
            except sqlite3.OperationalError:
                out["unresolved_receipts"] = []
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    if out["issued"] >= MIN_ISSUED and out["paid"] == 0:
        out["alerts"].append({
            "kind": "no_payments",
            "fingerprint": "no_payments",
            "text": (f"Реквизиты выдавали {out['issued']} раз за {h} ч — оплат НЕТ ни одной. "
                     f"Проверить: доходит ли клиент до кнопки «я оплатил», живы ли сессии "
                     f"полный срок, не сломана ли страница оплаты."),
        })
    if out["early_expiry"] >= EARLY_EXPIRY_MIN:
        out["alerts"].append({
            "kind": "early_expiry",
            "fingerprint": "early_expiry",
            "text": (f"{out['early_expiry']} сессий закрылись РАНЬШЕ своего expires_at за {h} ч. "
                     f"Это регрессия бага от 19.07 (сессии убивались на 15-й минуте из 30)."),
        })
    if out["stuck_payouts"]:
        lst = ", ".join(f"#{p['order_id']} ({p['rub_amount']:g} ₽ → {p['currency']}, "
                        f"{p['age_min']} мин)" for p in out["stuck_payouts"][:8])
        out["alerts"].append({
            "kind": "stuck_payout",
            "fingerprint": _fingerprint("stuck_payout", out["stuck_payouts"]),
            "text": (f"{len(out['stuck_payouts'])} заявок оплачено, но крипта НЕ отправлена "
                     f">{STUCK_PAYOUT_MIN} мин: {lst}. Деньги у нас — выдать вручную "
                     f"(/worker) или проверить, не завис ли авто-payout."),
        })
    if out["undelivered_receipts"]:
        lst = ", ".join(f"#{p['order_id']} ({p['rub_amount']:g} ₽, {p['provider']}, "
                        f"{p['age_min']} мин)" for p in out["undelivered_receipts"][:8])
        out["alerts"].append({
            "kind": "receipt_undelivered",
            "fingerprint": _fingerprint("receipt_undelivered", out["undelivered_receipts"]),
            "text": (f"{len(out['undelivered_receipts'])} чеков залито клиентом, но "
                     f"провайдеру НЕ доставлено >{RECEIPT_UNDELIVERED_MIN} мин: {lst}. "
                     f"Передать чек трейдеру вручную в кабинете/группе провайдера, "
                     f"ПОКА сделка на их стороне жива — иначе оплату не подтвердят."),
        })
    if out["unresolved_receipts"]:
        rows = out["unresolved_receipts"]
        rub = sum(float(p.get("rub_amount") or 0) for p in rows)
        lst = ", ".join(
            f"#{p['order_id']} ({p['rub_amount']:g} ₽, {p['provider']}, "
            f"{p['age_min'] // 60} ч{'' if p.get('delivered') else ', чек НЕ у провайдера'})"
            for p in rows[:8])
        tail = f" и ещё {len(rows) - 8}" if len(rows) > 8 else ""
        out["alerts"].append({
            "kind": "receipt_unresolved",
            # Окно молчания — на весь симптом, а пробивает его водяной знак
            # (см. alert_throttle.high_water): очередь разбора живёт неделю, и
            # отпечаток по её составу сбрасывался бы от каждой заявки, которую
            # оператор закрыл, — работа сама порождала бы тревогу.
            "fingerprint": "receipt_unresolved",
            "watermark": _newest_id(rows),
            "text": (f"Заявок с чеком и без решения дольше "
                     f"{RECEIPT_UNRESOLVED_MIN} мин: {len(rows)} на {rub:,.0f} ₽".replace(",", " ") +
                     f" — {lst}{tail}. Клиент считает, что заплатил, а сама заявка "
                     f"не закроется: пока она pending, её держит Слой 0; если уже "
                     f"expired — деньги клиенту это всё равно не вернуло. Решает "
                     f"человек: /review — выдать или отклонить, /order ID — разбор."),
        })
    return out


def _newest_id(rows: list) -> int:
    """Наибольший order_id в выборке — для водяного знака тревоги.

    Сравнение ЧИСЛОВОЕ: на строках max() лексикографический, и «99» осталось бы
    новее всех заявок от «100» до «199» — новая жертва попала бы в чужое окно
    молчания ровно на переходе через разрядность. Нечисловые id пропускаем: знак
    должен расти от реальных заявок, а не от мусора.
    """
    best = -1
    for r in rows:
        try:
            best = max(best, int(r.get("order_id")))
        except (TypeError, ValueError):
            continue
    return best


def _fingerprint(kind: str, rows: list) -> str:
    """Отпечаток алерта = тип + состав пострадавших заявок.

    Возраст в минутах намеренно НЕ входит: он меняется каждый прогон, и алерт
    выглядел бы новым бесконечно. А вот появление ещё одной заявки в списке —
    новая беда, и молчать про неё нельзя (см. core/alert_throttle).
    """
    ids = sorted(str(r.get("order_id")) for r in rows)
    return f"{kind}:{','.join(ids)}"


def format_alert(res: dict) -> str:
    """Готовое сообщение для Telegram или '' — если поводов нет."""
    if not res.get("alerts"):
        return ""
    head = (f"🚨 <b>Конверсия: тихий сбой</b>\n\n"
            f"<blockquote>Окно: {res['window_hours']} ч\n"
            f"Выдано реквизитов: <b>{res['issued']}</b>\n"
            f"Оплачено: <b>{res['paid']}</b></blockquote>\n")
    return head + "\n" + "\n\n".join("• " + a["text"] for a in res["alerts"])
