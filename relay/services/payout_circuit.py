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
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

DB_PATH = Path("/root/exchange.db")
logger = logging.getLogger(__name__)

_schema_ready = False


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    try:
        with _db() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS system_flags ("
                         "key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
            conn.commit()
        _schema_ready = True
    except Exception as e:
        logger.warning("payout_circuit schema init failed: %s", e)


def _int_env(name, default):
    try:
        v = int(os.getenv(name, ""))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def get_flag(key):
    _ensure_schema()
    try:
        with _db() as conn:
            row = conn.execute("SELECT value FROM system_flags WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
    except Exception:
        return None


def set_flag(key, value):
    _ensure_schema()
    try:
        with _db() as conn:
            conn.execute("INSERT INTO system_flags (key, value, updated_at) VALUES (?,?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                         (key, str(value), datetime.now().isoformat()))
            conn.commit()
        return True
    except Exception as e:
        logger.error("payout_circuit set_flag failed: %s", e)
        return False


def is_frozen():
    return (get_flag("payout_frozen") or "0") == "1"


def freeze(reason=""):
    set_flag("payout_frozen", "1")
    set_flag("payout_frozen_reason", reason[:300])
    logger.warning("PAYOUT CIRCUIT BREAKER TRIPPED: %s", reason)


def unfreeze():
    set_flag("payout_frozen", "0")
    set_flag("payout_frozen_reason", "")
    logger.info("payout circuit breaker reset (unfrozen)")


def _paid_last(hours):
    """(сумма RUB, число) авто-/ручных выплат (status='sent') за последние N часов."""
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(rub_amount),0) s, COUNT(*) n FROM orders "
                "WHERE status='sent' AND updated_at >= datetime('now', ?)",
                (f'-{hours} hours',)).fetchone()
        return float(row["s"] or 0), int(row["n"] or 0)
    except Exception as e:
        logger.warning("payout_circuit _paid_last failed: %s", e)
        return 0.0, 0


def _addr_payouts_24h(address):
    if not address:
        return 0
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) n FROM orders WHERE status='sent' AND crypto_address=? "
                "AND updated_at >= datetime('now','-1 day')", (address,)).fetchone()
        return int(row["n"] or 0)
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
    addr_cnt = _addr_payouts_24h(address)
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
