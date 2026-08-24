"""Режим наблюдения за стражем выплат: вердикты пишутся, но НИЧЕГО не делают.

Зачем. Владелец обходил авто-выплату и отправлял крипту руками, потому что не
доверял проверке оплаты — и был прав: вебхуки ставили paid по одному полю status,
не сверяя сумму, а сессии умирали на половине срока. Доверие деньгам нельзя
выдать авансом, его надо заработать данными.

Здесь страж выносит вердикт по каждой оплаченной заявке и складывает его в журнал.
Через пару недель сравниваем: что решил бы автомат против того, что сделал человек.
Совпадения = основание доверять. Расхождения = точный адрес проблемы.

ГАРАНТИЯ: модуль только читает. Ни отправки крипты, ни смены статусов заявок.
"""
from __future__ import annotations
import os
import logging
from repositories.shadow_payout_store import from_environment as _store_from_environment

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
AUTO_PAYOUT_LIMIT = float(os.getenv("AUTO_PAYOUT_LIMIT", "5000") or 5000)


_store = _store_from_environment(sqlite_path=DB_PATH)


def _storage():
    if hasattr(_store, "path") and _store.path != DB_PATH:
        return _store_from_environment(sqlite_path=DB_PATH)
    return _store


def ensure_schema():
    _storage().ensure_schema()


def record_pending(limit: int = 25) -> dict:
    """Выносит вердикт по оплаченным заявкам, которых ещё нет в журнале."""
    ensure_schema()
    import sys
    # путь к relay — от себя, а не от боевого каталога (мина «зашитый боевой путь»)
    _relay = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _relay not in sys.path:
        sys.path.insert(0, _relay)
    from core.safety import verify_payment_settled, check_payout_allowed

    stats = {"checked": 0, "recorded": 0, "errors": 0}
    try:
        rows = _storage().pending_orders(limit)
    except Exception as e:
        logger.warning("shadow: выборка заявок: %s", e)
        return stats

    for r in rows:
        stats["checked"] += 1
        oid = r["order_id"]
        try:
            v = verify_payment_settled(oid) or {}
            cb = check_payout_allowed(oid, r["rub_amount"], r["crypto_address"],
                                      r["currency"]) or {}
            would = int(v.get("verdict") == "confirmed"
                        and cb.get("action") == "ok"
                        and float(r["rub_amount"] or 0) <= AUTO_PAYOUT_LIMIT)
            _storage().record(oid, v.get("verdict"), (v.get("detail") or "")[:300],
                          v.get("provider"), cb.get("action"), would,
                          r["rub_amount"], r["currency"])
            stats["recorded"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.warning("shadow: заявка %s: %s", oid, e)
    return stats


def sync_outcomes() -> int:
    """Проставляет фактический исход: что человек сделал с заявкой."""
    ensure_schema()
    try:
        return _storage().sync_outcomes()
    except Exception as e:
        logger.warning("shadow: sync_outcomes: %s", e)
        return 0


def summary(days: int = 14) -> dict:
    """Сводка: сходились ли решения автомата с действиями человека."""
    ensure_schema()
    sync_outcomes()
    out = {"days": days, "total": 0, "by_verdict": {}, "agree": 0,
           "would_pay_but_human_didnt": 0, "human_paid_but_guard_refused": 0,
           "pending": 0}
    try:
        rows = _storage().recent(days)
    except Exception as e:
        out["error"] = str(e)
        return out

    for r in rows:
        out["total"] += 1
        v = r["verdict"] or "?"
        out["by_verdict"][v] = out["by_verdict"].get(v, 0) + 1
        sent = (r["outcome"] or "").startswith("отправлено")
        if not sent and (r["outcome"] or "") == "ещё не отправлено":
            out["pending"] += 1
            continue
        if r["would_auto_pay"] and sent:
            out["agree"] += 1                      # автомат заплатил бы — человек заплатил
        elif r["would_auto_pay"] and not sent:
            out["would_auto_pay_but_human_didnt"] = \
                out.get("would_auto_pay_but_human_didnt", 0) + 1
            out["would_pay_but_human_didnt"] += 1  # ОПАСНО: автомат заплатил бы зря
        elif not r["would_auto_pay"] and sent:
            out["human_paid_but_guard_refused"] += 1  # автомат был бы избыточно строг
        else:
            out["agree"] += 1                      # оба воздержались
    return out
