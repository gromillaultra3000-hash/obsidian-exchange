"""Долговечный троттлинг алертов — «не чаще раза в N» переживает рестарт.

Зачем. Троттлинг жил в словаре внутри корутины (`last_sent` в
conversion_watch_task). Пока процесс работает сутками — это верно. Но
relay-fastapi перезапускается деплой-таймером, и после каждого рестарта словарь
пуст: 27.07.2026 один и тот же алерт «3 заявки оплачено, крипта не отправлена»
ушёл админам ~80 раз за 20 часов вместо 4. Одинаковые сообщения читать
перестают — и настоящая тревога про 13 947 ₽ клиентских денег утонула в них.
Троттлинг обязан жить там же, где факты, — в БД.

Ключ — не тип алерта, а его ОТПЕЧАТОК (тип + состав пострадавших заявок). Так
новая зависшая выплата пробивает окно молчания сразу, а повтор того же самого —
нет. Иначе «тихо 6 часов» означало бы и «тихо про новую беду 6 часов».
"""
from __future__ import annotations
import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

_DDL = ("CREATE TABLE IF NOT EXISTS alert_throttle ("
        " key TEXT PRIMARY KEY, last_sent TEXT NOT NULL)")


def should_send(key: str, min_interval_sec: int) -> bool:
    """True — отправлять; False — окно молчания ещё не истекло.

    Захват атомарный (UPDATE ... WHERE last_sent старее порога + rowcount),
    поэтому два процесса не отправят один алерт дважды.

    При сбое БД возвращает True. Это сознательный fail-OPEN: цена ошибки здесь —
    лишнее сообщение, а цена молчания — незамеченные деньги клиента.
    """
    if not key:
        return True
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute(_DDL)
        # запись-заглушка с заведомо старым временем: дальше единственный UPDATE
        # решает и «первый раз», и «окно истекло» одинаково.
        conn.execute("INSERT OR IGNORE INTO alert_throttle (key, last_sent) "
                     "VALUES (?, datetime('now', '-100 years'))", (key,))
        cur = conn.execute(
            "UPDATE alert_throttle SET last_sent=datetime('now') "
            "WHERE key=? AND last_sent <= datetime('now', ?)",
            (key, f"-{int(min_interval_sec)} seconds"))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        logger.error("alert_throttle недоступен (%s) — шлём без троттлинга", type(e).__name__)
        return True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def cleanup(older_than_days: int = 30) -> int:
    """Убирает отпечатки, о которых давно не вспоминали. Возвращает число строк."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute(_DDL)
        cur = conn.execute("DELETE FROM alert_throttle WHERE last_sent < datetime('now', ?)",
                           (f"-{int(older_than_days)} days",))
        conn.commit()
        return cur.rowcount
    except Exception:
        return 0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
