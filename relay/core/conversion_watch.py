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
from repositories.operational_read_store import from_environment as _read_store_from_environment

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
def _store():return _read_store_from_environment(sqlite_path=DB_PATH)
# Operational read model исключает отметку `receipt_rejected`, чтобы тревога не
# возвращала оператору уже решённый им чек.

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


def check_conversion(window_hours: int | None = None) -> dict:
    """Считает симптомы за окно. Ничего не шлёт — только факты."""
    h = window_hours or WINDOW_HOURS
    out = {"window_hours": h, "alerts": [], "issued": 0, "paid": 0, "early_expiry": 0,
           "stuck_payouts": [], "undelivered_receipts": [], "unresolved_receipts": []}
    try:
        snapshot = _store().conversion_snapshot(
            window_hours=h, stuck_minutes=STUCK_PAYOUT_MIN,
            undelivered_minutes=RECEIPT_UNDELIVERED_MIN,
            unresolved_minutes=RECEIPT_UNRESOLVED_MIN,
            unresolved_days=RECEIPT_UNRESOLVED_DAYS)
        out.update(snapshot)
        already = {p["order_id"] for p in out["undelivered_receipts"]}
        out["unresolved_receipts"] = [
            row for row in out["unresolved_receipts"] if row["order_id"] not in already]
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
