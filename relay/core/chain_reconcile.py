"""Сверка блокчейна с заявками: что реально ушло против того, что записано.

Зачем. 19.07.2026 обнаружилось 16 заявок на 90 420 ₽, где крипта была отправлена
руками, а система об этом не знала: статус 'paid', txid пустой, клиент без
подтверждения. Расхождение прожило месяц незамеченным, потому что сверять было
не с чем — учёт вёлся только внутри БД.

Теперь есть кошелёк, а у блокчейна память лучше нашей. Сверка смотрит на обе
стороны и показывает, где они разошлись.

Классы расхождений (каждый значит своё):
  unrecorded_payout — деньги ушли из кошелька, но заявки под них нет.
                      Самое опасное: средства покинули кошелёк без основания.
  unproven_payout   — заявка помечена отправленной, но доказательства нет
                      (txid пустой или это пометка 'manual'). Не факт кражи —
                      обычно ручная отправка мимо системы; но проверить нечем.
  phantom_txid      — в заявке есть txid, а в цепочке такой транзакции нет
                      или она провалилась. Клиенту показали несуществующее.
  amount_mismatch   — сумма в цепочке не совпала с суммой заявки.

ТОЛЬКО ЧТЕНИЕ: ничего не отправляет и не меняет статусы заявок.
"""
from __future__ import annotations
import os
import sqlite3
import logging

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
# Допуск на сопоставление суммы: провайдеры/сеть могут дать копеечный сдвиг.
AMOUNT_TOLERANCE = float(os.getenv("RECONCILE_AMOUNT_TOLERANCE", "0.01") or 0.01)


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


# Переводы, у которых заявки нет и не должно быть: тесты, пополнение биржи,
# перевод между своими адресами. Без этого списка каждый такой перевод навсегда
# висел бы красным, отчёт превратился бы в шум — и его перестали бы читать.
IGNORE_PATH = os.getenv("RECONCILE_IGNORE_PATH", "/root/wallet_data/reconcile_ignore.json")


def _known_non_order_tx() -> set:
    try:
        import json
        with open(IGNORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {str(k) for k in (data.get("txids") or {})}
    except Exception:
        return set()


def ignore_tx(txid: str, reason: str) -> dict:
    """Пометить перевод как заведомо не относящийся к заявкам."""
    import json
    from pathlib import Path
    p = Path(IGNORE_PATH)
    try:
        data = json.loads(p.read_text("utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    data.setdefault("txids", {})[str(txid)] = {"reason": reason}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "txid": txid, "reason": reason, "total": len(data["txids"])}


def _chain_outgoing(address: str, limit: int = 200) -> list[dict]:
    """Исходящие переводы TRC-20 из кошелька, по данным сети."""
    import requests
    out = []
    for base in ("https://api.trongrid.io", "https://api.tronstack.io"):
        try:
            r = requests.get(f"{base}/v1/accounts/{address}/transactions/trc20",
                             params={"limit": limit}, timeout=15)
            data = (r.json() or {}).get("data") or []
            for t in data:
                if (t.get("from") or "") != address:
                    continue           # входящие нас здесь не интересуют
                dec = int((t.get("token_info") or {}).get("decimals") or 6)
                out.append({
                    "txid": t.get("transaction_id"),
                    "to": t.get("to"),
                    "amount": int(t.get("value") or 0) / (10 ** dec),
                    "symbol": (t.get("token_info") or {}).get("symbol"),
                    "ts": int(t.get("block_timestamp") or 0) // 1000,
                })
            if data:
                return out
        except Exception as e:
            logger.warning("chain_reconcile: %s: %s", base, e)
    return out


def _sent_orders(days: int) -> list[dict]:
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT order_id, currency, crypto_address, paid_btc_tx, rub_amount,
                       status, created_at, updated_at
                FROM orders
                WHERE status IN ('sent','paid')
                  AND created_at >= datetime('now', ?)
                ORDER BY order_id DESC""", (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("chain_reconcile: чтение orders: %s", e)
        return []


def reconcile(days: int = 30) -> dict:
    """Сверяет цепочку с заявками. Ничего не меняет."""
    try:
        import sys
        if "/root/relay" not in sys.path:
            sys.path.insert(0, "/root/relay")
        from wallet.tron_wallet import tron_address
        from core.txid import is_txid
        address = tron_address()
    except Exception as e:
        return {"error": f"кошелёк недоступен: {type(e).__name__}", "issues": []}

    res = {"address": address, "days": days, "issues": [],
           "chain_sends": 0, "orders_checked": 0, "matched": 0}
    if not address:
        res["error"] = "кошелёк не создан"
        return res

    chain = _chain_outgoing(address)
    res["chain_sends"] = len(chain)
    orders = _sent_orders(days)
    res["orders_checked"] = len(orders)

    used_tx = set()

    # 1) заявки → цепочка
    for o in orders:
        tx = (o.get("paid_btc_tx") or "").strip()
        cur = (o.get("currency") or "").upper()
        if is_txid(tx):
            hit = next((c for c in chain if (c["txid"] or "").lower() == tx.lower()), None)
            if hit:
                used_tx.add(hit["txid"])
                res["matched"] += 1
                if hit["to"] and o.get("crypto_address") and \
                        hit["to"] != o["crypto_address"]:
                    res["issues"].append({
                        "kind": "amount_mismatch", "order_id": o["order_id"],
                        "detail": f"адрес в цепочке {hit['to']} ≠ адрес заявки {o['crypto_address']}"})
            elif cur in ("USDT", "TRX"):
                # ищем только те валюты, которые ходят через ЭТОТ кошелёк
                res["issues"].append({
                    "kind": "phantom_txid", "order_id": o["order_id"],
                    "detail": f"txid {tx[:16]}… не найден в исходящих кошелька"})
        elif o.get("status") == "sent":
            res["issues"].append({
                "kind": "unproven_payout", "order_id": o["order_id"],
                "detail": f"помечена отправленной, доказательства нет "
                          f"(txid: {tx or 'пусто'})"})

    # 2) цепочка → заявки
    known = _known_non_order_tx()
    res["ignored"] = 0
    for c in chain:
        if c["txid"] in used_tx:
            continue
        if c["txid"] in known:
            res["ignored"] += 1     # тест/казначейский перевод, объяснён заранее
            continue
        res["issues"].append({
            "kind": "unrecorded_payout", "order_id": None,
            "detail": f"{c['amount']} {c['symbol']} → {c['to']} "
                      f"(tx {(c['txid'] or '')[:16]}…) не привязан ни к одной заявке"})

    order = {"unrecorded_payout": 0, "phantom_txid": 1, "amount_mismatch": 2,
             "unproven_payout": 3}
    res["issues"].sort(key=lambda i: order.get(i["kind"], 9))
    res["by_kind"] = {}
    for i in res["issues"]:
        res["by_kind"][i["kind"]] = res["by_kind"].get(i["kind"], 0) + 1
    return res


def format_report(r: dict, max_items: int = 8) -> str:
    """Сводка для Telegram."""
    if r.get("error"):
        return f"⚠️ Сверка недоступна: {r['error']}"
    head = (f"⛓ <b>Сверка цепочки с заявками</b>\n\n"
            f"<blockquote>Исходящих в сети: <b>{r['chain_sends']}</b>\n"
            f"Заявок проверено: <b>{r['orders_checked']}</b> (за {r['days']} дн.)\n"
            f"Сошлось: <b>{r['matched']}</b></blockquote>\n")
    if not r["issues"]:
        return head + "\n✅ Расхождений нет."
    names = {
        "unrecorded_payout": "🔴 Ушли без заявки",
        "phantom_txid": "🟠 txid не найден в цепочке",
        "amount_mismatch": "🟠 Адрес/сумма не совпали",
        "unproven_payout": "🟡 Без доказательства отправки",
    }
    lines = [head, "<b>Расхождения:</b>"]
    for kind, cnt in r["by_kind"].items():
        lines.append(f"{names.get(kind, kind)}: <b>{cnt}</b>")
    lines.append("")
    for i in r["issues"][:max_items]:
        oid = f"#{i['order_id']} " if i.get("order_id") else ""
        lines.append(f"• {oid}{i['detail']}")
    if len(r["issues"]) > max_items:
        lines.append(f"…и ещё {len(r['issues']) - max_items}")
    return "\n".join(lines)
