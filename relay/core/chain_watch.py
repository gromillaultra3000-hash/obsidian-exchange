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


# ── TRON: остаток и история USDT-TRC20 ───────────────────────────────────────
# Отдельно от Esplora: у TRON другой обозреватель, другая форма ответа и — что
# важнее — в цепи живут РАЗНЫЕ активы на одном счёте. Показывать «баланс TRON»
# без указания актива нельзя: клиент решит, что видит свои USDT, а увидит TRX.
TRON_API = os.getenv("TRON_EXPLORER_API", "https://api.trongrid.io")
# Контракт USDT в TRON. Единственный актив, который мы в этой цепи торгуем;
# захардить его безопаснее, чем брать из ответа: подставной контракт с тем же
# символом «USDT» — известный способ показать человеку чужие деньги.
USDT_TRC20_CONTRACT = os.getenv("USDT_TRC20_CONTRACT",
                                "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
USDT_DECIMALS = 6


def _tron_account(addr: str):
    d = _get_json(f"{TRON_API}/v1/accounts/{addr}") or {}
    data = d.get("data")
    if not isinstance(data, list):
        return None
    # Пустой список у TronGrid означает «счёт не активирован» — это НЕ сбой и
    # честный ноль: адрес существует, переводов на него не было.
    return (data[0] if data else {}) or {}


def tron_account_state(address: str) -> dict:
    """Остаток USDT-TRC20 по адресу. Актив назван явно (`asset`)."""
    addr = str(address or "").strip()
    if not addr:
        return {"balance": None, "pending": None, "status": "UNSUPPORTED",
                "reason": "адрес не задан", "asset": "USDT"}

    def build():
        try:
            acc = _tron_account(addr)
        except Exception as e:
            logger.warning("chain_watch: TRON баланс не прочитан: %s", e)
            return {"balance": None, "pending": None, "status": "ERROR",
                    "reason": type(e).__name__, "asset": "USDT"}
        if acc is None:
            return {"balance": None, "pending": None, "status": "ERROR",
                    "reason": "обозреватель ответил в незнакомом виде",
                    "asset": "USDT"}
        raw = 0
        for entry in (acc.get("trc20") or []):
            if isinstance(entry, dict) and USDT_TRC20_CONTRACT in entry:
                try:
                    raw = int(entry[USDT_TRC20_CONTRACT])
                except (TypeError, ValueError):
                    return {"balance": None, "pending": None, "status": "ERROR",
                            "reason": "остаток пришёл не числом", "asset": "USDT"}
                break
        # У TRON нет мемпула в том смысле, в каком он есть у биткойна: перевод
        # либо в блоке, либо его нет. `pending` = 0, а не None — «неизвестно»
        # здесь было бы неправдой.
        return {"balance": raw / (10 ** USDT_DECIMALS), "pending": 0.0,
                "status": "OK", "reason": None, "asset": "USDT"}

    return _cached(("bal", "TRON", addr), build)


def tron_history(address: str, limit: int = 20) -> dict:
    """Последние переводы USDT-TRC20 по адресу."""
    addr = str(address or "").strip()
    lim = max(1, min(int(limit or 20), 50))
    if not addr:
        return {"items": [], "status": "UNSUPPORTED", "reason": "адрес не задан"}

    def build():
        try:
            d = _get_json(f"{TRON_API}/v1/accounts/{addr}/transactions/trc20"
                          f"?limit={lim}&contract_address={USDT_TRC20_CONTRACT}") or {}
        except Exception as e:
            logger.warning("chain_watch: TRON история не прочитана: %s", e)
            return {"items": [], "status": "ERROR", "reason": type(e).__name__}
        rows = d.get("data")
        if not isinstance(rows, list):
            return {"items": [], "status": "ERROR",
                    "reason": "обозреватель ответил в незнакомом виде"}
        items = []
        for t in rows:
            if not isinstance(t, dict):
                continue
            # Знаки берём из ответа, но верим только известному контракту:
            # у подставного токена decimals может быть какой угодно.
            info = t.get("token_info") or {}
            if (info.get("address") or "") != USDT_TRC20_CONTRACT:
                continue
            try:
                val = int(t.get("value") or 0)
            except (TypeError, ValueError):
                continue
            to = (t.get("to") or "").strip()
            items.append({
                "direction": "in" if to == addr else "out",
                "amount": val / (10 ** USDT_DECIMALS),
                "counterparty": (t.get("from") if to == addr else to) or "",
                "ts": int(t.get("block_timestamp") or 0) // 1000,
                "txid": t.get("transaction_id") or "",
                "confirmed": True,      # TronGrid отдаёт уже включённые в блок
                "asset": "USDT",
            })
        return {"items": [i for i in items if i["txid"]][:lim],
                "status": "OK", "reason": None}

    return _cached(("hist", "TRON", addr, lim), build)


# ── Ethereum ─────────────────────────────────────────────────────────────────
# Обозреватель тот же, что уже читает сверка выдачи (`core/payout_discovery`), и
# та же переменная окружения: два разных источника правды по одной цепи означали
# бы, что баланс и сверка спорят друг с другом, а разобраться нечем.
#
# Зачем это вообще понадобилось. Клиент подписывал сообщение своим ETH-адресом
# (`core/sig_proof` умеет EIP-191), мы отвечали «владение подтверждено» — и тут
# же показывали «баланс: не поддерживается», потому что в реестре источников
# ETH не было. Просить доказательство и не уметь показать результат — обещание
# наполовину, ровно то, против чего написан заголовок этого модуля.
EVM_API = os.getenv("EVM_EXPLORER_API", "https://eth.blockscout.com/api")
WEI = 10 ** 18


# Обозреватели в стиле Etherscan отвечают «ничего не найдено» тем же
# `status: "0"`, что и настоящим отказом, различая их только текстом. Пустая
# история нового адреса — нормальный ответ, а не сбой; спутать их значит
# сказать клиенту «история недоступна» там, где честный ответ «операций нет».
# Нашёл codex.
_EVM_EMPTY = ("no transactions found", "no records found",
              "no token transfers found", "no internal transactions found")


def _evm_call(params: dict):
    """Запрос к обозревателю в стиле Etherscan. Возвращает поле result.

    Настоящий отказ («NOTOK», превышен лимит) обязан стать исключением: иначе
    клиент с деньгами на счету увидит ноль. А «записей нет» — это ответ.
    """
    from urllib.parse import urlencode
    d = _get_json(f"{EVM_API}?{urlencode(params)}") or {}
    res = d.get("result")
    if str(d.get("status", "1")) == "0":
        # Список (в том числе пустой) — уже ответ, разбирать текст незачем.
        if isinstance(res, list):
            return res
        msg = str(d.get("message") or "").strip().lower()
        if any(m in msg for m in _EVM_EMPTY):
            return []
        if not res:
            raise ValueError(str(d.get("message") or "NOTOK"))
    return res


def _usdt_erc20_contract() -> str:
    """Адрес контракта USDT в Ethereum — из единственного объявления в проекте.

    Второй литерал здесь был бы копией, которая однажды разойдётся с той, по
    которой реально уходят выплаты. Импорт ленивый: `wallet.evm_wallet` тянет
    вольт и криптобиблиотеки, а нам нужна одна строка. Не получилось ни импорта,
    ни переменной окружения — честно возвращаем пусто, и токен просто не
    показывается. Показать «0 USDT» человеку, у которого они есть, хуже.
    """
    try:
        from wallet.evm_wallet import USDT_ERC20
        return str(USDT_ERC20 or "").strip()
    except Exception:
        return str(os.getenv("EVM_USDT_CONTRACT", "") or "").strip()


def evm_account_state(address: str) -> dict:
    """Остаток по ETH-адресу: сам ETH и USDT-ERC20 на том же счёте.

    Как и у TRON, на одном счёте живут разные активы, и назвать одно число
    «балансом Ethereum» нельзя. Заглавным (`balance`/`asset`) остаётся ETH —
    это родная монета сети; остальное перечислено в `assets`, и портфель
    считает именно по нему.
    """
    addr = str(address or "").strip()
    if not addr:
        return {"balance": None, "pending": None, "status": "UNSUPPORTED",
                "reason": "адрес не задан", "asset": "ETH", "assets": []}

    def build():
        # Два НЕЗАВИСИМЫХ запроса: у обозревателя это разные действия, и падение
        # одного ничего не говорит о другом. Прежде сбой родного баланса уводил
        # функцию из ветки целиком, и клиент с USDT-ERC20 на счету не видел их
        # только потому, что молчал эндпоинт про ETH. Нашёл codex.
        eth, eth_err = None, None
        try:
            raw = _evm_call({"module": "account", "action": "balance",
                             "address": addr, "tag": "latest"})
            eth = int(str(raw).strip()) / WEI
        except Exception as e:
            logger.warning("chain_watch: ETH баланс не прочитан: %s", e)
            eth_err = type(e).__name__

        assets = [{"asset": "ETH", "balance": eth,
                   "status": "OK" if eth_err is None else "ERROR",
                   "reason": eth_err}]

        contract = _usdt_erc20_contract()
        if contract:
            try:
                t = _evm_call({"module": "account", "action": "tokenbalance",
                               "contractaddress": contract, "address": addr,
                               "tag": "latest"})
                assets.append({"asset": "USDT",
                               "balance": int(str(t).strip()) / (10 ** USDT_DECIMALS),
                               "status": "OK", "reason": None})
            except Exception as e:
                logger.warning("chain_watch: USDT-ERC20 не прочитан: %s", e)
                assets.append({"asset": "USDT", "balance": None,
                               "status": "ERROR", "reason": type(e).__name__})

        # Заглавное число — про родную монету сети, и его статус про неё же.
        # Правду про весь счёт несёт `assets`: недоступный ETH не отменяет
        # прочитанный USDT и не превращается в ноль ни тот, ни другой.
        # `pending` = None: обозреватель отдаёт остаток последнего блока и про
        # мемпул молчит. Ноль здесь был бы утверждением, что ничего не летит.
        return {"balance": eth, "pending": None,
                "status": "OK" if eth_err is None else "ERROR",
                "reason": eth_err, "asset": "ETH", "assets": assets}

    return _cached(("bal", "ETH", addr), build)


def _evm_rows(action: str, addr: str, lim: int, extra: dict = None) -> list:
    params = {"module": "account", "action": action, "address": addr,
              "sort": "desc", "page": 1, "offset": lim}
    params.update(extra or {})
    rows = _evm_call(params)
    if not isinstance(rows, list):
        raise ValueError("обозреватель ответил в незнакомом виде")
    return rows


def evm_history(address: str, limit: int = 20) -> dict:
    """Последние переводы по ETH-адресу: сам ETH и USDT-ERC20.

    Два запроса, потому что у обозревателя это два разных списка: `txlist`
    токен-переводов не содержит ВООБЩЕ. Показывать остаток USDT и не показывать
    ни одного перевода USDT — ровно та половинчатость, из-за которой раздел
    выглядит сломанным. Нашёл codex.
    """
    addr = str(address or "").strip()
    lim = max(1, min(int(limit or 20), 50))
    if not addr:
        return {"items": [], "status": "UNSUPPORTED", "reason": "адрес не задан"}
    low = addr.lower()

    def build():
        contract = _usdt_erc20_contract()

        def _row(t, asset, unit):
            """Строка истории из записи обозревателя или None, если это не
            движение денег."""
            if not isinstance(t, dict):
                return None
            # Сорвавшаяся транзакция денег не двигает. Показать её строкой
            # «получено 0.5 ETH» — соврать о приходе, которого не было.
            if str(t.get("isError") or "0") != "0":
                return None
            try:
                raw = int(str(t.get("value") or "0"))
            except (TypeError, ValueError):
                return None
            # Нулевые — вызовы контрактов, а не переводы.
            if raw == 0:
                return None
            to = (t.get("to") or "").strip()
            inc = to.lower() == low
            return {"direction": "in" if inc else "out", "amount": raw / unit,
                    "counterparty": (t.get("from") if inc else to) or "",
                    "ts": int(t.get("timeStamp") or 0),
                    "txid": t.get("hash") or "", "confirmed": True, "asset": asset}

        def _native(t):
            return _row(t, "ETH", WEI)

        def _token(t):
            # Решает АДРЕС контракта, а не символ: любой может выпустить свой
            # «USDT» и прислать перевод, который в списке выглядел бы как
            # настоящие деньги.
            if (t or {}).get("contractAddress", "").lower() != contract.lower():
                return None
            return _row(t, "USDT", 10 ** USDT_DECIMALS)

        # Три РАЗНЫХ списка у обозревателя, и ни один не включает остальные:
        #  • txlist — переводы, отправленные людьми;
        #  • txlistinternal — ETH, сдвинутый контрактом (так приходит вывод с
        #    большинства бирж и выплаты мультиподписи). Без него операция,
        #    изменившая баланс, просто исчезает из истории — нашёл codex;
        #  • tokentx — переводы токенов, которых в txlist нет вовсе.
        plan = [("ETH", "txlist", None, _native),
                ("ETH-внутренние", "txlistinternal", None, _native)]
        if contract:
            plan.append(("USDT", "tokentx", {"contractaddress": contract}, _token))

        seen, items, missing = set(), [], []
        for label, action, extra, parse in plan:
            try:
                rows = _evm_rows(action, addr, lim, extra)
            except Exception as e:
                logger.warning("chain_watch: %s история не прочитана: %s", label, e)
                missing.append(label)
                continue
            for t in rows:
                row = parse(t)
                if not row or not row["txid"]:
                    continue
                # Одна транзакция попадает и в txlist, и в txlistinternal, если
                # двигала ETH и напрямую, и через контракт. Дубль в истории
                # клиент прочитает как два перевода.
                key = (row["txid"], row["asset"], row["direction"],
                       round(row["amount"], 12))
                if key in seen:
                    continue
                seen.add(key)
                items.append(row)

        # Молчат ВСЕ источники — это отказ. Молчит часть — отдаём что есть, но
        # НЕ выдаём неполный список за полный: пропажа операций выглядит для
        # клиента как потерянный перевод.
        if len(missing) >= len(plan):
            return {"items": [], "status": "ERROR",
                    "reason": "обозреватель не ответил"}
        items.sort(key=lambda i: i.get("ts") or 0, reverse=True)
        out = {"items": items[:lim], "status": "OK", "reason": None}
        if missing:
            out["partial"] = True
            out["reason"] = f"часть операций недоступна ({', '.join(missing)})"
        return out

    return _cached(("hist", "ETH", addr, lim), build)


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
