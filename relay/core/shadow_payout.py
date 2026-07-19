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
import sqlite3
import logging

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
AUTO_PAYOUT_LIMIT = float(os.getenv("AUTO_PAYOUT_LIMIT", "5000") or 5000)


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payout_shadow (
                order_id       INTEGER PRIMARY KEY,
                decided_at     TEXT DEFAULT CURRENT_TIMESTAMP,
                verdict        TEXT,
                detail         TEXT,
                provider       TEXT,
                circuit_action TEXT,
                would_auto_pay INTEGER,
                rub_amount     REAL,
                currency       TEXT,
                outcome        TEXT,
                outcome_at     TEXT
            )""")
        conn.commit()


def record_pending(limit: int = 25) -> dict:
    """Выносит вердикт по оплаченным заявкам, которых ещё нет в журнале."""
    ensure_schema()
    import sys
    if "/root/relay" not in sys.path:
        sys.path.insert(0, "/root/relay")
    from core.safety import verify_payment_settled, check_payout_allowed

    stats = {"checked": 0, "recorded": 0, "errors": 0}
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT o.order_id, o.rub_amount, o.currency, o.crypto_address
                FROM orders o
                WHERE o.status IN ('paid','sent')
                  AND o.created_at >= datetime('now','-14 days')
                  AND NOT EXISTS (SELECT 1 FROM payout_shadow s WHERE s.order_id=o.order_id)
                ORDER BY o.order_id DESC LIMIT ?""", (limit,)).fetchall()
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
            with _db() as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO payout_shadow
                    (order_id, verdict, detail, provider, circuit_action,
                     would_auto_pay, rub_amount, currency)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (oid, v.get("verdict"), (v.get("detail") or "")[:300],
                     v.get("provider"), cb.get("action"), would,
                     r["rub_amount"], r["currency"]))
                conn.commit()
            stats["recorded"] += 1
        except Exception as e:
            stats["errors"] += 1
            logger.warning("shadow: заявка %s: %s", oid, e)
    return stats


def sync_outcomes() -> int:
    """Проставляет фактический исход: что человек сделал с заявкой."""
    ensure_schema()
    try:
        with _db() as conn:
            cur = conn.execute("""
                UPDATE payout_shadow SET
                    outcome = (SELECT CASE
                        WHEN o.status='sent' AND o.paid_btc_tx LIKE 'manual%' THEN 'отправлено вручную'
                        WHEN o.status='sent' THEN 'отправлено (авто/txid)'
                        WHEN o.status='paid' THEN 'ещё не отправлено'
                        ELSE o.status END FROM orders o WHERE o.order_id=payout_shadow.order_id),
                    outcome_at = datetime('now')
                WHERE outcome IS NULL
                   OR outcome = 'ещё не отправлено'""")
            conn.commit()
            return cur.rowcount
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
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM payout_shadow WHERE decided_at >= datetime('now', ?)",
                (f"-{days} days",)).fetchall()
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
