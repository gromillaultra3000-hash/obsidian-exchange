"""Fail-closed гейт ПРОДАЖИ: рубли уходят только когда монеты РЕАЛЬНО на адресе.

Зеркало логики relay/services/payout_guard.py (гейт покупки), но первоисточник
здесь — не провайдер, а сам блокчейн. Кнопка «Выплатить» деньги не двигает: она
лишь помечает sell_orders.status='paid'. До этого модуля единственной защитой
были глаза админа — заявка #1 (05.07.2026) была помечена paid, хотя на адрес не
приходило ни одной транзакции.

⚠️ Адрес приёма ОБЩИЙ для всех заявок (SELL_*_ADDRESS из bot/.env), поэтому
депозит нельзя привязать к заявке по адресу. Привязка = сумма + время + защита
от повторного зачёта: txid, уже записанный в другую sell_orders.tx_hash, второй
раз не засчитывается (иначе один депозит оплатил бы две заявки).

Вердикты verify_sell_deposit():
  - 'confirmed'   — депозит найден и подтверждён → можно платить
  - 'pending'     — депозит найден, но мало подтверждений → подождать
  - 'underpaid'   — пришло меньше заявленного (за вычетом допуска) → решает человек
  - 'not_found'   — подходящей транзакции нет → НЕ платить
  - 'unavailable' — эксплорер недоступен/ошибка → НЕ платить (fail-closed)
  - 'unsupported' — валюта без проверки / не задан адрес → НЕ платить

Никогда не «отпускает лишнего»: в сомнении — человек. Обойти гейт может только
главный админ отдельной кнопкой, и это пишется в admin_log.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

import requests

DB_PATH = Path("/root/exchange.db")
logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 12

# Сколько подтверждений считаем достаточным для необратимости.
MIN_CONFIRMATIONS = {"BTC": 1, "LTC": 2, "USDT": 19}

# Допуск по сумме: клиенты часто шлют с биржи, которая удерживает сетевую
# комиссию из суммы вывода → приходит чуть меньше заявленного.
AMOUNT_TOLERANCE = 0.005  # 0.5%

# Транзакция могла лечь в блок чуть раньше, чем клиент дожал форму заявки.
DEPOSIT_GRACE_SEC = 2 * 3600

# litecoinspace — форк mempool.space, API идентичен → один парсер на BTC и LTC.
_ESPLORA = {
    "BTC": "https://mempool.space/api",
    "LTC": "https://litecoinspace.org/api",
}

_TRONGRID = "https://api.trongrid.io"
_USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


class _ExplorerError(Exception):
    """Эксплорер недоступен/ответил мусором → вердикт 'unavailable' (не 'not_found')."""


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _claimed_txids(conn, exclude_sell_id: int) -> set:
    """txid, уже зачтённые другим заявкам — повторно засчитывать нельзя."""
    rows = conn.execute(
        "SELECT tx_hash FROM sell_orders WHERE tx_hash IS NOT NULL AND tx_hash != '' AND id != ?",
        (exclude_sell_id,),
    ).fetchall()
    return {r["tx_hash"] for r in rows}


def _get_json(url: str, params=None):
    try:
        r = requests.get(url, params=params, timeout=HTTP_TIMEOUT,
                         headers={"User-Agent": "ObsidianExchange/1.0"})
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        raise _ExplorerError(f"{type(exc).__name__}: {exc}") from exc


def _esplora_deposits(currency: str, address: str) -> list:
    """Входящие транзакции на address. → [{txid, amount, confirmations, ts}]"""
    base = _ESPLORA[currency]
    tip = _get_json(f"{base}/blocks/tip/height")
    try:
        tip = int(tip)
    except (TypeError, ValueError):
        raise _ExplorerError(f"нечисловая высота вершины: {tip!r}")

    txs = _get_json(f"{base}/address/{address}/txs")
    if not isinstance(txs, list):
        raise _ExplorerError(f"неожиданный ответ /address/txs: {type(txs).__name__}")

    out = []
    for tx in txs:
        sats = sum(
            v.get("value", 0) for v in tx.get("vout", [])
            if v.get("scriptpubkey_address") == address
        )
        if sats <= 0:
            continue  # исходящая/чужая — нам в неё ничего не пришло
        st = tx.get("status") or {}
        confs = 0
        if st.get("confirmed") and st.get("block_height"):
            confs = max(0, tip - int(st["block_height"]) + 1)
        out.append({
            "txid": tx.get("txid", ""),
            "amount": sats / 1e8,
            "confirmations": confs,
            "ts": st.get("block_time") or 0,  # 0 = ещё в мемпуле
        })
    return out


def _tron_deposits(address: str) -> list:
    """Входящие USDT TRC-20. TronGrid отдаёт только попавшие в блок переводы,
    счётчика подтверждений в ответе нет → возраст блока как прокси (блок ~3 с,
    19 блоков ≈ 1 мин)."""
    data = _get_json(
        f"{_TRONGRID}/v1/accounts/{address}/transactions/trc20",
        params={"only_to": "true", "limit": 50, "contract_address": _USDT_TRC20},
    )
    if not isinstance(data, dict) or not data.get("success", True):
        raise _ExplorerError(f"TronGrid ответил ошибкой: {str(data)[:200]}")

    now = time.time()
    out = []
    for t in data.get("data", []):
        try:
            decimals = int((t.get("token_info") or {}).get("decimals", 6))
            amount = int(t.get("value", 0)) / (10 ** decimals)
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        ts = int(t.get("block_timestamp", 0)) // 1000
        age = now - ts if ts else 0
        out.append({
            "txid": t.get("transaction_id", ""),
            "amount": amount,
            # в блоке и старше минуты → считаем необратимым
            "confirmations": MIN_CONFIRMATIONS["USDT"] if ts and age >= 60 else 0,
            "ts": ts,
        })
    return out


def _result(verdict, reason, txid=None, received=0.0, expected=0.0, confirmations=0):
    return {
        "verdict": verdict,
        "reason": reason,
        "txid": txid,
        "received": received,
        "expected": expected,
        "confirmations": confirmations,
    }


def verify_sell_deposit(sell_id: int) -> dict:
    """Ищет в блокчейне депозит под заявку sell_id. Блокирующий, звать в executor.

    При 'confirmed' пишет найденный txid в sell_orders.tx_hash (резервирует его
    за этой заявкой, чтобы тот же депозит не зачёлся второй раз)."""
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT currency, crypto_amount, receive_address, status, tx_hash, created_at "
                "FROM sell_orders WHERE id=?", (sell_id,)
            ).fetchone()
            if not row:
                return _result("not_found", f"заявка #{sell_id} не найдена в базе")

            currency = (row["currency"] or "").upper()
            expected = float(row["crypto_amount"] or 0)
            address = (row["receive_address"] or "").strip()
            claimed = _claimed_txids(conn, sell_id)

            created_ts = 0
            if row["created_at"]:
                try:
                    created_ts = int(time.mktime(time.strptime(
                        str(row["created_at"])[:19], "%Y-%m-%d %H:%M:%S")))
                except ValueError:
                    created_ts = 0
    except sqlite3.Error as exc:
        logger.exception("sell_guard: ошибка БД по заявке #%s", sell_id)
        return _result("unavailable", f"ошибка базы: {exc}")

    if not address:
        return _result("unsupported", "у заявки не сохранён адрес приёма")
    if expected <= 0:
        return _result("unsupported", "у заявки нулевая сумма")
    if currency not in _ESPLORA and currency != "USDT":
        return _result("unsupported", f"проверка блокчейна для {currency} не реализована")

    try:
        deposits = (_tron_deposits(address) if currency == "USDT"
                    else _esplora_deposits(currency, address))
    except _ExplorerError as exc:
        logger.warning("sell_guard: эксплорер %s недоступен: %s", currency, exc)
        return _result("unavailable", f"эксплорер {currency} недоступен ({exc})", expected=expected)

    min_conf = MIN_CONFIRMATIONS.get(currency, 1)
    # Окно двустороннее. Нижняя граница — сетевая комиссия биржи-отправителя.
    # Верхняя — обязательна: адрес ОБЩИЙ, и депозит заметно крупнее заявленного
    # почти наверняка принадлежит другой заявке, а не «щедрому» клиенту. Без неё
    # заявка на 0.0005 BTC зачла бы себе чужие 0.0042 BTC.
    floor_amount = expected * (1 - AMOUNT_TOLERANCE)
    ceil_amount = expected * (1 + AMOUNT_TOLERANCE)
    earliest = created_ts - DEPOSIT_GRACE_SEC if created_ts else 0

    best_pending = None    # сумма подходит, но мало подтверждений
    best_mismatch = None   # депозит есть, но сумма вне окна → решает человек

    for d in deposits:
        if not d["txid"] or d["txid"] in claimed:
            continue  # уже зачтён другой заявке — не наш
        if earliest and d["ts"] and d["ts"] < earliest:
            continue  # старее заявки → это чужой/прошлый депозит
        if not (floor_amount - 1e-12 <= d["amount"] <= ceil_amount + 1e-12):
            if (best_mismatch is None
                    or abs(d["amount"] - expected) < abs(best_mismatch["amount"] - expected)):
                best_mismatch = d
            continue
        if d["confirmations"] < min_conf:
            if best_pending is None or d["confirmations"] > best_pending["confirmations"]:
                best_pending = d
            continue

        # подошёл: сумма в допуске, подтверждений достаточно, txid свободен
        try:
            with _db() as conn:
                conn.execute("UPDATE sell_orders SET tx_hash=?, updated_at=datetime('now') WHERE id=?",
                             (d["txid"], sell_id))
                conn.commit()
        except sqlite3.Error:
            logger.exception("sell_guard: не удалось записать tx_hash для #%s", sell_id)
        return _result("confirmed",
                       f"депозит подтверждён ({d['confirmations']} подтв.)",
                       txid=d["txid"], received=d["amount"], expected=expected,
                       confirmations=d["confirmations"])

    if best_pending:
        return _result("pending",
                       f"транзакция найдена, но подтверждений {best_pending['confirmations']}/{min_conf} — подождите",
                       txid=best_pending["txid"], received=best_pending["amount"],
                       expected=expected, confirmations=best_pending["confirmations"])
    if best_mismatch:
        return _result("amount_mismatch",
                       f"на адрес пришло {best_mismatch['amount']:.8f} {currency}, "
                       f"а заявлено {expected:.8f} {currency} — сумма не сходится",
                       txid=best_mismatch["txid"], received=best_mismatch["amount"],
                       expected=expected, confirmations=best_mismatch["confirmations"])

    return _result("not_found",
                   f"на адрес не поступало {expected:.8f} {currency} по этой заявке",
                   expected=expected)


def describe_verdict(res: dict, currency: str = "") -> str:
    """Человекочитаемая строка для карточки заявки у админа."""
    icon = {
        "confirmed": "✅", "pending": "⏳", "amount_mismatch": "⚠️",
        "not_found": "⛔", "unavailable": "🌐", "unsupported": "❓",
    }.get(res["verdict"], "❓")
    head = {
        "confirmed": "Монеты на адресе",
        "pending": "Ждём подтверждений сети",
        "amount_mismatch": "Сумма не сходится",
        "not_found": "Монеты НЕ поступили",
        "unavailable": "Проверка недоступна",
        "unsupported": "Проверка невозможна",
    }.get(res["verdict"], res["verdict"])
    line = f"{icon} <b>{head}</b>\n{res['reason']}"
    if res.get("received"):
        line += f"\nПолучено: <b>{res['received']:.8f} {currency}</b>"
    if res.get("txid"):
        line += f"\nTX: <code>{res['txid']}</code>"
    return line
