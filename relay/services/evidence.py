"""Evidence-фреймворк «заявлено ≠ доказано» (перенос идеи LUMI OutcomeTruthEvaluator,
профиль trading_exchange_app: «paid без ledger-реконсиляции не считается доказанным»).

Формализует то, что payout_guard/sell_guard делают ad-hoc: присваивает завершённой
заявке УРОВЕНЬ ДОКАЗАТЕЛЬНОСТИ и «потолок» доверия. Статус 'paid' сам по себе —
лишь claimed (заявлено); доказано = подтверждение провайдера ИЛИ блокчейна.

Уровни (по возрастанию силы):
    none              — нет сигналов
    claimed           — помечено paid/sent, но без независимого подтверждения
    provider_confirmed— провайдер подтвердил get_status (RUB реально получены)
    chain_confirmed   — есть tx в блокчейне (крипта реально ушла/пришла)

API:
    assess(status, provider_confirmed=False, chain_tx=None) -> dict
    order_evidence(order_row) -> dict          # оценка по строке orders
    evidence_summary(days=30) -> dict          # advisory: доля доказанных
"""
from __future__ import annotations
import sqlite3

DB_PATH = "/root/exchange.db"
PAID_STATUSES = ("paid", "sent")

LEVELS = {"none": 0, "claimed": 1, "provider_confirmed": 2, "chain_confirmed": 3}
# «потолок доверия» по уровню — как в LUMI core.py: без доказательств доверие ограничено
CEILING = {"none": 0.2, "claimed": 0.45, "provider_confirmed": 0.8, "chain_confirmed": 1.0}


def assess(status: str, provider_confirmed: bool = False, chain_tx: str | None = None) -> dict:
    """Уровень доказательности одного исхода."""
    if chain_tx:
        level = "chain_confirmed"
    elif provider_confirmed:
        level = "provider_confirmed"
    elif status in PAID_STATUSES:
        level = "claimed"
    else:
        level = "none"
    proven = LEVELS[level] >= LEVELS["provider_confirmed"]
    missing = []
    if not proven:
        missing.append("provider reconciliation ИЛИ blockchain tx")
    return {
        "level": level,
        "level_num": LEVELS[level],
        "proven": proven,
        "trust_ceiling": CEILING[level],
        "missing_evidence": missing,
    }


def order_evidence(order_row: dict) -> dict:
    """Оценка по строке orders (dict). chain-доказательство = наличие paid_btc_tx."""
    status = str(order_row.get("status") or "")
    chain_tx = order_row.get("paid_btc_tx") or None
    # provider_confirmed пока не хранится отдельным флагом — по мере интеграции payout_guard
    res = assess(status, provider_confirmed=False, chain_tx=chain_tx)
    res["order_id"] = order_row.get("order_id")
    return res


def evidence_summary(days: int = 30, db_path: str = DB_PATH) -> dict:
    """Advisory: среди завершённых (paid/sent) заявок — сколько доказаны блокчейном."""
    paid_set = ",".join("'%s'" % s for s in PAID_STATUSES)
    sql = f"""
        SELECT order_id, status, paid_btc_tx
        FROM orders
        WHERE status IN ({paid_set}) AND created_at > datetime('now', ?)
    """
    rows = []
    try:
        with sqlite3.connect(db_path, timeout=5) as c:
            c.row_factory = sqlite3.Row
            rows = [dict(r) for r in c.execute(sql, (f"-{int(days)} days",)).fetchall()]
    except Exception as e:
        return {"error": str(e), "total": 0}

    assessed = [order_evidence(r) for r in rows]
    total = len(assessed)
    chain = sum(1 for a in assessed if a["level"] == "chain_confirmed")
    claimed_only = sum(1 for a in assessed if a["level"] == "claimed")
    return {
        "days": days,
        "total_completed": total,
        "chain_confirmed": chain,
        "claimed_only": claimed_only,
        "proven_pct": round(100 * chain / total, 1) if total else 0.0,
        "note": ("Доля завершённых заявок с доказательством в блокчейне. "
                 "claimed_only = помечены оплаченными, но без tx-подтверждения — "
                 "кандидаты на ручную сверку."),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(evidence_summary(30), ensure_ascii=False, indent=2))
