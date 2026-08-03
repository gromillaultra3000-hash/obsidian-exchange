"""Очередь разбора: деньги клиента у нас, обещанное ему — нет.

Зачем отдельный модуль. Оплаченных заявок без выдачи копилось до 99 часов, и
видели их три разных места по-своему: `/pending` брал только `status='paid'`,
`/review` — только заявки с чеком, сторож конверсии считал третьим запросом. Ни
одно из них не показывало ВОЗРАСТ, а без возраста очередь неразбираема: сорок
строк выглядят одинаково, и человек берёт верхнюю, а не самую больную.

Здесь одна выборка на всех. Два повода попасть в очередь — оба означают «деньги
приняты, обещанное не выдано»:

  payout  — оплата подтверждена, крипта не отправлена. Долг наш, измеряется в
            деньгах клиента, и растёт молча: маркер `payout_triggered` защищает
            от двойной выплаты, но он же означает, что авто-движок к заявке уже
            не вернётся. Не выдаст человек — не выдаст никто.
  receipt — клиент прислал чек, решения нет. Долг — решение: выдать или
            отклонить. Заявку держит Слой 0 (cleanup_expired_orders не истекает
            заявки с чеком), и сама она не закроется никогда.

SLA здесь — не обещание клиенту, а признак «этой строкой пора заняться»:
    ok     — возраст в норме;
    warn   — просрочено (по умолчанию 45 мин, как порог сторожа конверсии);
    breach — просрочено грубо (4 часа): в этой точке клиент уже написал в
             поддержку, а если не написал — ушёл.

Тот же возраст видит и КЛИЕНТ: пока строка висит в очереди, ему честно говорят
«выплата задерживается, разбираем», а не показывают «Оплачена» и тишину.
"""
from __future__ import annotations

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Пороги. Warn совпадает с CONV_WATCH_STUCK_PAYOUT_MIN не случайно: сторож
# тревожит ровно про то, что в очереди помечено как просроченное. Разъедутся —
# алерт будет про одни заявки, а очередь про другие.
SLA_WARN_MIN = int(os.getenv("PAYOUT_SLA_WARN_MIN", "45") or 45)
SLA_BREACH_MIN = int(os.getenv("PAYOUT_SLA_BREACH_MIN", "240") or 240)

KIND_PAYOUT = "payout"
KIND_RECEIPT = "receipt"

_SLA_ICON = {"ok": "🟢", "warn": "🟠", "breach": "🔴"}


def sla_level(age_min) -> str:
    """Насколько строка просрочена. Неизвестный возраст — худший случай.

    Возраст берётся из updated_at, который у древних заявок бывает пуст. Считать
    такую строку свежей — значит спрятать самую старую беду в конец списка.
    """
    try:
        age = int(age_min)
    except (TypeError, ValueError):
        return "breach"
    if age >= SLA_BREACH_MIN:
        return "breach"
    if age >= SLA_WARN_MIN:
        return "warn"
    return "ok"


def sla_icon(level: str) -> str:
    return _SLA_ICON.get(level, "🟠")


def human_age(age_min) -> str:
    """«18 мин», «3 ч 40 мин», «2 сут 5 ч» — возраст должен читаться мгновенно."""
    try:
        m = int(age_min)
    except (TypeError, ValueError):
        return "возраст неизвестен"
    if m < 0:
        m = 0
    if m < 60:
        return f"{m} мин"
    if m < 60 * 24:
        return f"{m // 60} ч {m % 60:02d} мин"
    return f"{m // (60 * 24)} сут {(m % (60 * 24)) // 60} ч"


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


_PAYOUT_SQL = """
    SELECT o.order_id, o.user_id, o.username, o.rub_amount, o.currency,
           o.crypto_address, o.network, o.status,
           CAST((julianday('now')-julianday(COALESCE(NULLIF(o.updated_at,''),o.created_at)))
                *24*60 AS INT) age_min
    FROM orders o
    WHERE o.status='paid' AND (o.paid_btc_tx IS NULL OR o.paid_btc_tx='')
"""

_RECEIPT_SQL = """
    SELECT o.order_id, o.user_id, o.username, o.rub_amount, o.currency,
           o.crypto_address, o.network, o.status,
           (o.receipt_sent_at IS NOT NULL AND o.receipt_sent_at<>'') delivered,
           CAST((julianday('now')-julianday(r.created_at))*24*60 AS INT) age_min
    FROM order_receipts r JOIN orders o ON o.order_id=r.order_id
    WHERE o.status NOT IN ('paid','sent')
      -- Оператор посмотрел чек и отказал — решение принято, долга больше нет.
      -- Статуса для этого мало: `cancelled` ставит и сам клиент, и тогда
      -- решения по его деньгам как раз НЕ было. Различает след отклонения.
      AND NOT EXISTS (SELECT 1 FROM sent_notifications sn
                      WHERE sn.order_id=o.order_id AND sn.event='receipt_rejected')
"""


# «Без потолка»: явная константа вместо магического числа у вызывающего. Потолок
# в выборке долгов опасен тем, что срабатывает ровно тогда, когда долгов много —
# и часть из них исчезает из итогов и из клиентских отметок.
NO_LIMIT = 10 ** 9


def queue(limit: int = 30, kind: str | None = None) -> list:
    """Строки очереди, самые старые первыми. Пустой список при сбое БД.

    Пустой список на сбое — сознательно: очередь читают показывающие
    поверхности, и «показать пусто» честнее, чем уронить весь экран. О самой
    беде тревожит сторож конверсии, у него отдельный путь к данным.
    """
    out = []
    try:
        with _db() as conn:
            if kind in (None, KIND_PAYOUT):
                for r in conn.execute(_PAYOUT_SQL).fetchall():
                    d = dict(r)
                    d["kind"] = KIND_PAYOUT
                    out.append(d)
            if kind in (None, KIND_RECEIPT):
                # Таблица чеков создаётся лениво — на базе без единого чека
                # эта половина просто пуста, а не роняет очередь целиком.
                try:
                    for r in conn.execute(_RECEIPT_SQL).fetchall():
                        d = dict(r)
                        d["kind"] = KIND_RECEIPT
                        out.append(d)
                except sqlite3.OperationalError as e:
                    # Молчать здесь нельзя: пропадает ПОЛОВИНА очереди, и
                    # выглядит это как «долгов такого рода нет».
                    logger.warning("payout_queue: половина очереди (чеки) "
                                   "недоступна: %s", e)
    except Exception as e:
        logger.error("payout_queue недоступна (%s)", type(e).__name__)
        return []
    for d in out:
        d["sla"] = sla_level(d.get("age_min"))
        d["age_human"] = human_age(d.get("age_min"))
    # Неизвестный возраст — В НАЧАЛО, а не в конец: это заявки без отметок
    # времени, то есть самые древние из всех. Ключ должен быть меньше любого
    # реального (-inf), иначе такая строка оказывается «свежее» всех и прячется
    # там, где её никто не листает.
    out.sort(key=lambda d: (float("-inf") if d.get("age_min") is None
                            else -float(d["age_min"])))
    return out[:limit]


def summary(rows: list) -> dict:
    """Шапка очереди: сколько, на сколько денег, сколько просрочено, самая старая."""
    rub = 0.0
    for r in rows:
        try:
            rub += float(r.get("rub_amount") or 0)
        except (TypeError, ValueError):
            pass
    breach = sum(1 for r in rows if r.get("sla") == "breach")
    warn = sum(1 for r in rows if r.get("sla") == "warn")
    oldest = rows[0] if rows else None
    return {
        "count": len(rows),
        "rub": rub,
        "breach": breach,
        "warn": warn,
        "oldest_age": (oldest or {}).get("age_human", ""),
        "oldest_id": (oldest or {}).get("order_id"),
    }


def client_state(order_id) -> dict:
    """Что честно сказать КЛИЕНТУ об этой заявке прямо сейчас.

    {'delayed': bool, 'age_min': int|None, 'kind': str}. Пороги те же, что у
    персонала: расхождение здесь означало бы, что клиенту говорят «всё идёт по
    плану» ровно тогда, когда у оператора строка горит красным.
    """
    try:
        with _db() as conn:
            r = conn.execute(_PAYOUT_SQL + " AND o.order_id=?", (order_id,)).fetchone()
    except Exception:
        return {"delayed": False, "age_min": None, "kind": ""}
    if not r:
        return {"delayed": False, "age_min": None, "kind": ""}
    age = r["age_min"]
    return {"delayed": sla_level(age) != "ok", "age_min": age, "kind": KIND_PAYOUT}
