"""
Payout circuit-breaker: защита горячего кошелька от аномального оттока.

Дополняет fail-closed гейт (payout_guard): тот проверяет, что оплата РЕАЛЬНО прошла;
этот — что суммарный объём/скорость авто-выплат в пределах нормы. При аномалии
включает СТОП-КРАН (заморозка авто-выплат) и уводит всё в ручной разбор до снятия
оператором.

Лимиты (env, все опциональны — 0/пусто = выключено):
  PAYOUT_DAILY_CAP_RUB   — потолок суммы авто-выплат за скользящие 24ч (default 300000)
  PAYOUT_HOURLY_MAX      — макс. число авто-выплат за час (default 20)
  PAYOUT_ADDR_REPEAT_MAX — сколько раз один адрес может получать авто-выплату за 24ч
                           (default 3) — сверх → на ручной разбор (не заморозка)

Вердикты check_payout_allowed():
  action 'ok'     — можно авто-выплату
  action 'manual' — увести к работнику (повтор адреса / кошелёк-аномалия по адресу)
  action 'freeze' — превышен потолок/скорость: ВКЛЮЧИТЬ стоп-кран, всё в ручной разбор

Стоп-кран персистентен (таблица system_flags), снимается оператором командой бота.
"""
import os
import logging
from pathlib import Path
from repositories.ops_store import from_environment as _ops_store_from_environment

DB_PATH = Path(os.getenv("DB_PATH", "/root/exchange.db"))
logger = logging.getLogger(__name__)
def _store():return _ops_store_from_environment(sqlite_path=str(DB_PATH))

def _ensure_schema():
    try:
        _store().get_flag("payout_frozen")
    except Exception as e:
        logger.warning("payout_circuit schema init failed: %s", e)


def _int_env(name, default):
    try:
        v = int(os.getenv(name, ""))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def get_flag(key):
    try:
        return _store().get_flag(key)
    except Exception:
        return None


def set_flag(key, value):
    try:
        return _store().set_flags({key:value})
    except Exception as e:
        logger.error("payout_circuit set_flag failed: %s", e)
        return False


def is_frozen():
    return (get_flag("payout_frozen") or "0") == "1"


def freeze(reason=""):
    _store().set_flags({"payout_frozen":"1","payout_frozen_reason":reason[:300]})
    logger.warning("PAYOUT CIRCUIT BREAKER TRIPPED: %s", reason)


def unfreeze():
    _store().set_flags({"payout_frozen":"0","payout_frozen_reason":""})
    logger.info("payout circuit breaker reset (unfrozen)")


def _paid_last(hours):
    """(сумма RUB, число) авто-/ручных выплат (status='sent') за последние N часов."""
    try:
        return _store().payout_totals(hours)
    except Exception as e:
        logger.warning("payout_circuit _paid_last failed: %s", e)
        return 0.0, 0


def _account_key(address, currency=None) -> str:
    """Идентичность счёта из строки адреса. Общий источник — core.address."""
    try:
        import sys
        _relay = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _relay not in sys.path:
            sys.path.insert(0, _relay)
        from core.address import account_key
        return account_key(address, currency)
    except Exception:
        # Своей нормализации здесь быть не должно: разошлась бы с чужой.
        # Не смогли привести — сравниваем как есть, это прежнее поведение.
        return str(address or "").strip()


def _addr_payouts_24h(address, currency=None):
    """Сколько раз ЭТОТ СЧЁТ получал выплату за сутки.

    Считать по строке адреса нельзя: у XRPL один счёт с разными тегами даёт
    разные строки, и лимит `PAYOUT_ADDR_REPEAT_MAX` не сработал бы ни разу —
    страж выглядел бы установленным, а на деле его обходит смена тега. У EVM
    то же самое делает регистр. Поэтому сравниваем ключи счетов, а выборку
    держим маленькой: только выплаты за сутки.
    """
    if not address:
        return 0
    want = _account_key(address, currency)
    if not want:
        return 0
    try:
        rows = _store().recent_payout_destinations(24)
        return sum(1 for r in rows
                   if _account_key(r[0], r[1]) == want)
    except Exception:
        return 0


def check_payout_allowed(order_id, rub_amount, address, currency=None) -> dict:
    """Вызывать ПЕРЕД авто-выплатой. См. модульный docstring."""
    _ensure_schema()

    if is_frozen():
        return {"action": "manual", "reason": "авто-выплаты заморожены (circuit breaker) — "
                                              f"{get_flag('payout_frozen_reason') or 'ручной режим'}"}

    daily_cap = _int_env("PAYOUT_DAILY_CAP_RUB", 300000)
    hourly_max = _int_env("PAYOUT_HOURLY_MAX", 20)
    addr_max = _int_env("PAYOUT_ADDR_REPEAT_MAX", 3)

    try:
        amt = float(rub_amount or 0)
    except (TypeError, ValueError):
        amt = 0.0

    # часовая скорость
    _, cnt_1h = _paid_last(1)
    if cnt_1h >= hourly_max:
        return {"action": "freeze",
                "reason": f"превышена скорость выплат: {cnt_1h} за час ≥ лимита {hourly_max}"}

    # суточный объём (уже выплачено + текущая)
    sum_24h, _ = _paid_last(24)
    if sum_24h + amt > daily_cap:
        return {"action": "freeze",
                "reason": f"превышен суточный потолок: {sum_24h + amt:,.0f} > {daily_cap:,.0f} ₽".replace(",", " ")}

    # повтор адреса — мягко, на ручной разбор (не заморозка: может быть постоянный клиент)
    addr_cnt = _addr_payouts_24h(address, currency)
    if addr_cnt >= addr_max:
        return {"action": "manual",
                "reason": f"адрес получал выплату {addr_cnt}× за 24ч (≥ {addr_max}) — проверить вручную"}

    return {"action": "ok", "reason": ""}


def status() -> dict:
    """Сводка для админ-команды."""
    _ensure_schema()
    sum_24h, cnt_24h = _paid_last(24)
    _, cnt_1h = _paid_last(1)
    return {
        "frozen": is_frozen(),
        "frozen_reason": get_flag("payout_frozen_reason") or "",
        "sum_24h": sum_24h,
        "count_24h": cnt_24h,
        "count_1h": cnt_1h,
        "daily_cap": _int_env("PAYOUT_DAILY_CAP_RUB", 300000),
        "hourly_max": _int_env("PAYOUT_HOURLY_MAX", 20),
        "addr_repeat_max": _int_env("PAYOUT_ADDR_REPEAT_MAX", 3),
    }
