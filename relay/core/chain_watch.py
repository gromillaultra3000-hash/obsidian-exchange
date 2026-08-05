"""Остаток и операции ЧУЖОГО адреса в цепи: BTC и LTC.

Зачем. Клиент доказал владение адресом подписью (`core/sig_proof`) — и увидел
в кошельке слово «подтверждено» вместо суммы. Половина обещания: кошелёк, в
котором нет баланса, кошельком не выглядит.

Кого можно спрашивать. Адрес сюда приходит ТОЛЬКО из таблицы подтверждённых
связей (`core/wallet_link`): показывать остаток по адресу из запроса — значит
сделать обменник бесплатным пробником чужих кошельков от нашего IP. Модуль
принимает адрес аргументом, потому что иначе его нечем позвать, — но зовёт его
единственный вызывающий, который берёт адрес из связей. Правило живёт там.

Два обещания этого модуля:

1. «Не знаем» — не ноль. Обозреватель молчит, отвечает 429 или отдаёт мусор —
   статус ERROR с причиной, а не спокойный нулевой остаток. Клиент, у которого
   на счету деньги, не должен увидеть пустой кошелёк из-за чужого сбоя.
2. Подтверждённое и ожидающее — разные числа. В остаток идёт только
   подтверждённое; то, что висит в мемпуле, показывается отдельно. Сложить их
   значило бы объявить своим то, что ещё может не состояться, а спрятать —
   ответить «ноль» человеку, который только что получил перевод.

Кеш на минуту. Один и тот же адрес спрашивают бот, сайт и Mini App подряд, а
у публичных обозревателей есть предел запросов; выбитый лимит выглядит как
«баланс недоступен» ровно тогда, когда клиент смотрит чаще всего.
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

# Публичные esplora-совместимые обозреватели. Переопределяются переменными
# окружения: если публичный упрётся в лимиты, владелец подставит свой узел,
# не трогая код.
BASES = {
    "BTC": os.getenv("BTC_EXPLORER_API", "https://mempool.space/api"),
    "LTC": os.getenv("LTC_EXPLORER_API", "https://litecoinspace.org/api"),
}

CACHE_TTL = int(os.getenv("CHAIN_WATCH_TTL", "60") or 60)
_cache: dict = {}
_lock = threading.Lock()

SATS = 100_000_000


def _cached(key, build):
    """Значение из кеша или свежее. Ошибки НЕ кешируем: сбой обозревателя
    длится секунды, а закешированный отказ пережил бы восстановление сети и
    держал бы клиента без баланса всю минуту."""
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    value = build()
    if value.get("status") == "OK":
        with _lock:
            _cache[key] = (now, value)
            if len(_cache) > 500:
                for k in sorted(_cache, key=lambda k: _cache[k][0])[:200]:
                    _cache.pop(k, None)
    return value


def _get_json(url: str, timeout: int = 12):
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _sats(stats, key):
    try:
        return int((stats or {}).get(key) or 0)
    except (TypeError, ValueError):
        return 0


def account_state(coin: str, address: str) -> dict:
    """{'balance', 'pending', 'status', 'reason'} — остаток адреса в монете.

    `balance` — только подтверждённое. `pending` — движение в мемпуле, может
    быть отрицательным (уходящий перевод ещё не в блоке).
    """
    coin = str(coin or "").upper()
    addr = str(address or "").strip()
    base = BASES.get(coin)
    if not base or not addr:
        return {"balance": None, "pending": None, "status": "UNSUPPORTED",
                "reason": f"сеть {coin or '?'} не поддержана"}

    def build():
        try:
            d = _get_json(f"{base}/address/{addr}") or {}
        except Exception as e:
            logger.warning("chain_watch: %s баланс не прочитан: %s", coin, e)
            return {"balance": None, "pending": None, "status": "ERROR",
                    "reason": type(e).__name__}
        chain = d.get("chain_stats")
        if not isinstance(chain, dict):
            # Ответ пришёл, но не тот, что мы умеем читать. Считать его нулём
            # нельзя: изменившийся формат выглядел бы как пустой кошелёк.
            return {"balance": None, "pending": None, "status": "ERROR",
                    "reason": "обозреватель ответил в незнакомом виде"}
        conf = _sats(chain, "funded_txo_sum") - _sats(chain, "spent_txo_sum")
        mem = d.get("mempool_stats") or {}
        pend = _sats(mem, "funded_txo_sum") - _sats(mem, "spent_txo_sum")
        return {"balance": conf / SATS, "pending": pend / SATS,
                "status": "OK", "reason": None}

    return _cached(("bal", coin, addr), build)


def history(coin: str, address: str, limit: int = 20) -> dict:
    """{'items', 'status', 'reason'} — последние операции адреса.

    Элемент повторяет форму TON-истории (direction/amount/counterparty/ts/txid),
    чтобы поверхности рисовали любую сеть одним кодом.
    """
    coin = str(coin or "").upper()
    addr = str(address or "").strip()
    base = BASES.get(coin)
    if not base or not addr:
        return {"items": [], "status": "UNSUPPORTED",
                "reason": f"история сети {coin or '?'} не поддержана"}
    try:
        lim = max(1, min(int(limit), 50))
    except (TypeError, ValueError):
        lim = 20

    def build():
        try:
            txs = _get_json(f"{base}/address/{addr}/txs") or []
        except Exception as e:
            logger.warning("chain_watch: %s история не прочитана: %s", coin, e)
            return {"items": [], "status": "ERROR", "reason": type(e).__name__}
        if not isinstance(txs, list):
            return {"items": [], "status": "ERROR",
                    "reason": "обозреватель ответил в незнакомом виде"}
        items = []
        for t in txs:
            vout = t.get("vout") or []
            vin = t.get("vin") or []
            got = sum(int(v.get("value") or 0) for v in vout
                      if v.get("scriptpubkey_address") == addr)
            spent = sum(int((v.get("prevout") or {}).get("value") or 0) for v in vin
                        if (v.get("prevout") or {}).get("scriptpubkey_address") == addr)
            net = got - spent
            if net == 0:
                continue          # адрес мелькнул, но остаток не изменился
            if net > 0:
                others = [(v.get("prevout") or {}).get("scriptpubkey_address")
                          for v in vin]
            else:
                others = [v.get("scriptpubkey_address") for v in vout]
            other = next((o for o in others if o and o != addr), "")
            st = t.get("status") or {}
            items.append({
                "direction": "in" if net > 0 else "out",
                "amount": abs(net) / SATS,
                "counterparty": other,
                "ts": st.get("block_time") or 0,
                "txid": t.get("txid") or "",
                "confirmed": bool(st.get("confirmed")),
            })
        return {"items": items[:lim], "status": "OK", "reason": None}

    return _cached(("hist", coin, addr, lim), build)


# ── переходники под реестр источников wallet_link ────────────────────────────
# Реестр зовёт функцию ОДНОГО адреса и ничего не знает про монету — она задана
# самой записью реестра. Отсюда пары тонких обёрток вместо параметра.
def btc_account_state(address: str) -> dict:
    return account_state("BTC", address)


def ltc_account_state(address: str) -> dict:
    return account_state("LTC", address)


def btc_history(address: str, limit: int = 20) -> dict:
    return history("BTC", address, limit)


def ltc_history(address: str, limit: int = 20) -> dict:
    return history("LTC", address, limit)
