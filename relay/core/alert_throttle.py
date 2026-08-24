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
from core import db_runtime
from repositories.alert_store import from_environment as _alert_store_from_environment

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
def _store():return _alert_store_from_environment(sqlite_path=DB_PATH)

def should_send(key: str, min_interval_sec: int) -> bool:
    """True — отправлять; False — окно молчания ещё не истекло.

    Захват атомарный (UPDATE ... WHERE last_sent старее порога + rowcount),
    поэтому два процесса не отправят один алерт дважды.

    При сбое БД возвращает True. Это сознательный fail-OPEN: цена ошибки здесь —
    лишнее сообщение, а цена молчания — незамеченные деньги клиента.
    """
    if not key:
        return True
    try:
        return _store().should_send(key,min_interval_sec)
    except Exception as e:
        logger.error("alert_throttle недоступен (%s) — шлём без троттлинга", type(e).__name__)
        return True


def cleanup(older_than_days: int = 30) -> int:
    """Убирает отпечатки, о которых давно не вспоминали. Возвращает число строк."""
    try:
        return _store().cleanup(older_than_days)
    except Exception:
        return 0


def high_water(key: str, value) -> bool:
    """True — `value` выше всего, что по этому ключу видели раньше (и запоминает).

    Зачем отдельно от should_send. Окно молчания «раз в 6 часов» правильно молчит
    про ту же беду и обязано заговорить про НОВУЮ. Отпечаток по составу
    пострадавших заявок для этого не годится, когда очередь живёт неделю и
    меряется десятками: состав меняется и от новой жертвы, и от каждой заявки,
    которую разобрал оператор, — то есть работа оператора сама порождала бы
    тревогу. Максимум текущей выборки не годится тоже: разобрали самую свежую —
    максимум упал — ключ снова «новый».

    Водяной знак не падает никогда. Растёт он только тогда, когда пострадал
    кто-то, о ком мы ещё не тревожили, — а это ровно то событие, ради которого
    окно молчания пробивают.

    Сбой БД — True (fail-OPEN, как и у should_send): цена ошибки здесь лишнее
    сообщение, цена молчания — незамеченные деньги клиента.
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        return False
    if not key:
        return True
    try:
        return _store().high_water(key,v)
    except Exception as e:
        logger.error("alert_watermark недоступен (%s) — считаем беду новой", type(e).__name__)
        return True
