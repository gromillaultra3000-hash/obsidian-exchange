"""Поиск доказательств выплаты в блокчейне по адресу назначения заявки.

Зачем. Выплата «мимо бота» — из личного кошелька владельца, а не из горячего —
оставляет заявку в статусе 'paid' навсегда: клиент не получает уведомление и
TXID, реф-бонус и VIP-объём не начисляются, сторож конверсии вечно считает
заявку зависшей. 27.07.2026 так висели три заявки на 13 947 ₽, две из которых
были УЖЕ оплачены; факт оплаты пришлось искать руками через обозреватели.

Отличие от core/chain_reconcile: тот смотрит на ИСХОДЯЩИЕ из нашего кошелька
(и только TRON). Здесь наоборот — ВХОДЯЩИЕ на адрес клиента, поэтому находятся
и переводы из кошельков, о которых система не знает.

## Главное правило: закрываем только по неподделываемому доказательству

Совпадение суммы на адресе клиента — доказательство СЛАБОЕ: адрес принадлежит
клиенту, и туда может прийти что угодно откуда угодно. Хуже того, клиент может
подстроить совпадение сам (перевести себе ожидаемую сумму со второго кошелька)
и получить закрытую заявку без выплаты. Поэтому отправитель обязан быть НАШИМ:
адрес горячего кошелька или адрес, заранее внесённый владельцем через
/paysrc. Такой перевод подделать нельзя — ключи только у нас.

Всё остальное (сумма сошлась, но отправитель неизвестен) закрытием НЕ считается
и уходит человеку как подсказка. Ошибка здесь стоит дороже, чем ручной клик:
закрытая по ошибке заявка означает клиента, который заплатил и не получил ничего,
а система считает, что всё в порядке.

ЧТЕНИЕ + вердикт. Модуль ничего не пишет в orders — решение исполняет вызывающий.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Насколько фактическая сумма может отличаться от ожидаемой. Комиссию сети
# платит отправитель, поэтому расхождение обычно нулевое; допуск нужен на
# округление и на ручной ввод «примерно столько».
AMOUNT_TOLERANCE_PCT = float(os.getenv("DISCOVERY_AMOUNT_TOLERANCE_PCT", "1.0") or 1.0)
# Насколько далеко от ожидаемой суммы перевод ещё СТОИТ ПОКАЗАТЬ человеку.
# Это НЕ второй допуск: в кандидаты такой перевод не попадает и кнопки закрытия
# не получает. Он существует потому, что «подходящих переводов не найдено» —
# самый вредный ответ, какой можно дать, когда перевод лежит на адресе первым в
# списке: по нему перестают искать. 04.08.2026 так замолчали две выплаты
# (#99955118 и #99955141), сделанные владельцем руками.
NEAR_TOLERANCE_PCT = float(os.getenv("DISCOVERY_NEAR_TOLERANCE_PCT", "15.0") or 15.0)
# Заявку моложе этого возраста не трогаем: авто-выплата ещё могла не отработать.
MIN_AGE_MIN = int(os.getenv("DISCOVERY_MIN_AGE_MIN", "45") or 45)
# Глубже в прошлое не смотрим — старые совпадения уже неактуальны.
MAX_AGE_DAYS = int(os.getenv("DISCOVERY_MAX_AGE_DAYS", "14") or 14)

SOURCES_PATH = os.getenv("DISCOVERY_SOURCES_PATH",
                         "/root/wallet_data/payout_sources.json")


# ─────────────────────────────────────────────────────────────────
# Доверенные отправители
# ─────────────────────────────────────────────────────────────────
def _norm(addr) -> str:
    """Адреса сравниваем без регистра: bech32 допускает верхний регистр целиком,
    а EVM-адрес несёт контрольную сумму именно в регистре. Для СРАВНЕНИЯ это
    неважно — важно не потерять совпадение из-за разного написания."""
    return str(addr or "").strip().lower()


def _norm_account(currency, addr) -> str:
    """Ключ СЧЁТА, а не строки адреса.

    У TON один счёт записывается тремя способами (`0:…`, `UQ…`, `EQ…`), и
    обозреватель отдаёт не ту форму, что лежит в настройках владельца. Приведение
    к нижнему регистру их не роднит — наоборот, у base64 оно ломает разбор.
    Своя выплата TON выглядела бы чужой и не закрывала заявку никогда; нашёл
    codex. Для остальных валют правило прежнее.
    """
    if str(currency or "").upper() == "TON":
        try:
            from core.address import ton_account_key
            key = ton_account_key(addr)
            if key:
                return key
        except Exception:
            pass
    return _norm(addr)


def _registered_sources() -> dict:
    try:
        p = Path(SOURCES_PATH)
        if not p.exists():
            return {}
        data = json.loads(p.read_text("utf-8"))
        return data.get("sources") or {}
    except Exception as e:
        logger.warning("payout_discovery: список источников нечитаем: %s", e)
        return {}


def add_source(currency: str, address: str, note: str = "") -> dict:
    """Внести кошелёк, из которого владелец платит клиентам, в доверенные."""
    cur = str(currency or "").upper()
    addr = str(address or "").strip()
    if not cur or not addr:
        return {"ok": False, "error": "нужны валюта и адрес"}
    p = Path(SOURCES_PATH)
    try:
        data = json.loads(p.read_text("utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    src = data.setdefault("sources", {})
    src.setdefault(cur, {})[_norm_account(cur, addr)] = {"note": note, "raw": addr}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "currency": cur, "address": addr,
            "total": sum(len(v) for v in src.values())}


def remove_source(currency: str, address: str) -> dict:
    cur = str(currency or "").upper()
    p = Path(SOURCES_PATH)
    try:
        data = json.loads(p.read_text("utf-8")) if p.exists() else {}
    except Exception:
        return {"ok": False, "error": "список нечитаем"}
    removed = (data.get("sources") or {}).get(cur, {}).pop(_norm_account(cur, address), None)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": bool(removed), "currency": cur, "address": address}


# Имена легаси-кошельков bitcoinlib (watch-only после Фазы 3) — по ним берётся
# ПОЛНЫЙ список адресов, включая адреса сдачи.
_LEGACY_WALLETS = {"BTC": "PayoutWallet", "LTC": "PayoutLTC"}


# Кеш своих адресов. Список кошелька меняется только когда мы сами тратим, а
# читается он через bitcoinlib, чей SQLite привязан к потоку-создателю: дёргать
# его из нового потока executor'а каждые полчаса — лишняя нагрузка и лишний
# риск. Просроченный кеш максимум отправит СВОЮ выплату человеку на
# подтверждение (новый адрес сдачи ещё не попал в список) — направление
# безопасное, ошибочного закрытия он вызвать не может.
_OWN_CACHE: dict[str, tuple[float, set]] = {}
OWN_CACHE_TTL = int(os.getenv("DISCOVERY_OWN_CACHE_TTL", "3600") or 3600)


def _own_wallet_addresses(currency: str) -> set:
    """Все адреса наших собственных кошельков — доверенные по определению.

    ⚠️ Одного «основного» адреса НЕДОСТАТОЧНО. Кошелёк BTC/LTC — иерархический:
    трата уходит с того адреса, где лежали монеты, а сдача садится на новый.
    Живая проверка 27.07.2026: выплата #99955120 ушла с bc1qnaqa9gz…, которого
    нет ни в primaryAddress, ни в списке addresses из меты вольта (11 записей
    против 23 фактических). Если брать только основной адрес, СВОЯ ЖЕ выплата
    выглядит чужой и заявка никогда не закроется — сбой тихий, без ошибки.
    Поэтому спрашиваем сам кошелёк (watch-only, пароль не нужен).
    """
    import time
    cur = str(currency or "").upper()
    hit = _OWN_CACHE.get(cur)
    if hit and (time.time() - hit[0]) < OWN_CACHE_TTL:
        return hit[1]
    out = set()
    try:
        import sys
        # путь к relay — от себя, а не от боевого каталога (мина «зашитый боевой путь»)
        _relay = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _relay not in sys.path:
            sys.path.insert(0, _relay)
        if cur in _LEGACY_WALLETS:
            from wallet import btc_wallet as bw
            a = bw.address(cur)
            if a:
                out.add(_norm(a))
            meta = bw._meta(cur) or {}
            out |= {_norm(x) for x in (meta.get("addresses") or []) if x}
            try:
                from bitcoinlib.wallets import Wallet
                out |= {_norm(x) for x in Wallet(_LEGACY_WALLETS[cur]).addresslist() if x}
            except Exception as e:
                # bitcoinlib есть только в bot/venv; без него остаётся мета —
                # список неполный, поэтому часть своих выплат уйдёт человеку
                # на подтверждение. Это медленнее, но не опаснее.
                logger.warning("payout_discovery: полный список адресов %s недоступен: %s",
                               cur, type(e).__name__)
        elif cur == "USDT":
            from wallet.tron_wallet import tron_address
            a = tron_address()
            if a:
                out.add(_norm(a))
        elif cur == "XRP":
            # У XRPL адрес один (не иерархический), поэтому меты достаточно.
            from wallet import xrp_wallet as xw
            a = (xw.status() or {}).get("address")
            if a:
                out.add(_norm(a))
        elif cur == "ETH":
            from wallet import evm_wallet as ew
            a = ew.address()
            if a:
                out.add(_norm(a))
        elif cur == "TON":
            # Своего вольта TON пока нет — выдача ручная, как была у XRP.
            # Адрес кошелька, с которого владелец платит, задаётся в окружении:
            # без него своя же выплата выглядит чужой и не закрывает заявку.
            a = os.getenv("TON_PAYOUT_ADDRESS", "").strip()
            if a:
                out.add(_norm_account("TON", a))
    except Exception as e:
        logger.warning("payout_discovery: адрес своего кошелька %s: %s", cur, e)
    out = {a for a in out if a}
    # Пустой результат НЕ кешируем: это признак сбоя, а не «своих адресов нет».
    # Закешировать пустоту значит на час лишить сверку возможности закрывать.
    if out:
        _OWN_CACHE[cur] = (time.time(), out)
    return out


def trusted_senders(currency: str) -> set:
    """Наши кошельки + внесённые владельцем. Пусто = закрывать нечем."""
    cur = str(currency or "").upper()
    # Ключ в файле мог быть записан старым правилом (просто нижний регистр),
    # поэтому берём исходную строку из «raw» — по ней счёт восстанавливается.
    reg = set()
    for key, meta in (_registered_sources().get(cur) or {}).items():
        reg.add(_norm_account(cur, (meta or {}).get("raw") or key))
    return _own_wallet_addresses(cur) | reg


# ─────────────────────────────────────────────────────────────────
# Чтение цепочек
# ─────────────────────────────────────────────────────────────────
def _get_json(url: str, params=None, timeout: int = 15):
    import requests
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _int_or_none(value):
    """Целое или None. None означает «источник не сообщил», и это НЕ ноль."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tip_height(base: str):
    """Высота вершины цепи — чтобы посчитать подтверждения. None при сбое.

    Отдельный запрос на всю выборку, а не на каждый перевод: обозреватель
    отдаёт в транзакции высоту БЛОКА, а подтверждения — это расстояние до
    вершины, и без неё их не узнать. Сбой → None: тогда честнее сказать
    «подтверждений не знаем», чем выдумать число.
    """
    try:
        import requests
        r = requests.get(f"{base}/blocks/tip/height", timeout=10)
        if r.status_code == 200:
            return int(r.text.strip())
    except Exception as e:
        logger.warning("payout_discovery: вершина цепи %s недоступна: %s",
                       base, type(e).__name__)
    return None


def _evm_tip_block(base: str):
    """Номер последнего блока EVM. None при сбое.

    Обозреватель ОБЫЧНО кладёт `confirmations` в каждую строку, но полагаться на
    это нельзя: набор полей у Blockscout меняется от версии к версии, а порог в
    Ethereum — двенадцать подтверждений. Пропадёт поле — и сверка, честно
    отказывая по каждому переводу, замолчит целиком: путь ETH будет всегда
    находить ноль и выглядеть исправным. Поэтому расстояние до вершины умеем
    считать сами, как в BTC.
    """
    try:
        data = _get_json(base, {"module": "proxy", "action": "eth_blockNumber"}) or {}
        raw = data.get("result")
        if isinstance(raw, str) and raw.strip().lower().startswith("0x"):
            return int(raw, 16)
        return _int_or_none(raw)
    except Exception as e:
        logger.warning("payout_discovery: вершина EVM %s недоступна: %s",
                       base, type(e).__name__)
    return None


def _evm_confirmations(row: dict, tip):
    """Подтверждения строки EVM: из поля обозревателя, иначе от вершины цепи.

    None означает «узнать не удалось» — и это не ноль: решение о том, что делать
    с молчанием источника, принимает `chain_confirm`, а не читатель.
    """
    confs = _int_or_none(row.get("confirmations"))
    if confs is not None:
        return confs
    height = _int_or_none(row.get("blockNumber"))
    if tip is None or height is None:
        return None
    return max(0, tip - height + 1)


def _evm_tip_if_needed(rows, base: str):
    """Вершина цепи — одним запросом на всю выборку и только если она нужна."""
    if any(isinstance(r, dict) and _int_or_none(r.get("confirmations")) is None
           for r in rows):
        return _evm_tip_block(base)
    return None


def _incoming_btc_like(address: str, coin: str) -> list[dict]:
    """Входящие переводы BTC/LTC. Отправителями считаем адреса всех входов."""
    base = ("https://mempool.space/api" if coin == "BTC"
            else "https://litecoinspace.org/api")
    txs = _get_json(f"{base}/address/{address}/txs") or []
    tip = _tip_height(base) if txs else None
    out = []
    for t in txs:
        value = sum(v.get("value", 0) for v in (t.get("vout") or [])
                    if v.get("scriptpubkey_address") == address)
        if value <= 0:
            continue          # адрес мог быть только сдачей/входом — не приход
        senders = {_norm((v.get("prevout") or {}).get("scriptpubkey_address"))
                   for v in (t.get("vin") or [])}
        st = t.get("status") or {}
        # Подтверждения = расстояние до вершины цепи. Одно подтверждение здесь
        # не финал: короткая развилка отменяет блок, а вместе с ним и перевод.
        height = st.get("block_height")
        confs = None
        if tip is not None and st.get("confirmed") and height:
            confs = max(0, int(tip) - int(height) + 1)
        out.append({
            "txid": t.get("txid"),
            "senders": {s for s in senders if s},
            "amount": value / 1e8,
            "ts": st.get("block_time") or 0,
            "confirmed": bool(st.get("confirmed")),
            "confirmations": confs,
        })
    return out


def _incoming_trc20(address: str) -> list[dict]:
    """Входящие USDT (TRC-20). Только необратимые переводы.

    ⚠️ Возраст блока — НЕ доказательство необратимости, хотя блок у TRON и идёт
    раз в 3 секунды. «Прошла минута» значит лишь, что прошла минута: если
    производство блоков встало, за неё их выпустили меньше девятнадцати, и
    перевод всё ещё откатывается. Расчёт по часам был здесь до 04.08.2026 и мог
    закрыть заявку по обратимому переводу — забраковал codex, и по делу.
    Спрашиваем у самой цепи: `only_confirmed=true` возвращает переводы из
    несократимых (solid) блоков, то есть решение принимает TRON, а не наши часы.
    Цена — перевод не виден первую минуту; она несопоставима с ценой ошибки.
    """
    data = _get_json("https://api.trongrid.io/v1/accounts/"
                     f"{address}/transactions/trc20",
                     {"limit": 50, "only_to": "true",
                      "only_confirmed": "true"}) or {}
    out = []
    for t in data.get("data") or []:
        info = t.get("token_info") or {}
        if (info.get("symbol") or "").upper() != "USDT":
            continue          # на адрес могли прийти другие токены
        dec = int(info.get("decimals") or 6)
        out.append({
            "txid": t.get("transaction_id"),
            "senders": {_norm(t.get("from"))},
            "amount": int(t.get("value") or 0) / (10 ** dec),
            "ts": int(t.get("block_timestamp") or 0) // 1000,
            # trongrid отдаёт только попавшие в блок переводы
            "confirmed": True,
            # Числа подтверждений в этом ответе нет вовсе, но оно и не нужно:
            # выборка ограничена несократимыми блоками, то есть сама цепь
            # говорит «откатить нельзя». Считать подтверждения по часам,
            # подменяя это утверждение своей оценкой, мы не будем.
            "irreversible": True,
        })
    return out


def _incoming_xrpl(address: str, dest_tag=None) -> list[dict]:
    """Входящие XRP на адрес клиента.

    Зачем именно здесь. Авто-выплаты XRP нет вовсе: `process_payout` его не
    знает, `/payout` честно отвечает «отправлять вручную». То есть у XRP ручная
    выдача — ЕДИНСТВЕННЫЙ путь, и до этого момента сверка, которая ловит ручные
    выдачи, про XRP не знала ничего. Монету открыли, а способа заметить выплату
    не завели: заявка оставалась `paid` навсегда с нулевым шансом закрыться.

    XRPL отвечает по JSON-RPC (`account_tx`). Берём только доставленные платежи
    в НАШУ сторону: XRPL пишет фактически доставленное в `delivered_amount`, и
    именно оно, а не заявленный `Amount`, считается полученным.

    `dest_tag` обязателен, если он был в адресе заявки. Классический адрес биржи
    ОДИН на всех её клиентов, а различаются они тегом: без сверки тега перевод
    нужного размера на ЧУЖОЙ тег закрыл бы не ту заявку — деньги ушли одному
    клиенту, закрыли другого, и оба остались недовольны по-своему.
    """
    import requests
    rpc = os.getenv("XRP_RPC_URL", "https://xrplcluster.com/")
    body = {"method": "account_tx", "params": [{
        "account": address, "ledger_index_min": -1, "ledger_index_max": -1,
        "binary": False, "limit": 60, "forward": False}]}
    try:
        r = requests.post(rpc, json=body, timeout=15)
        r.raise_for_status()
        rows = ((r.json() or {}).get("result") or {}).get("transactions") or []
    except Exception as e:
        logger.warning("payout_discovery: XRPL %s: %s", address[:12], type(e).__name__)
        return []
    out = []
    for row in rows:
        tx = row.get("tx") or row.get("tx_json") or {}
        meta = row.get("meta") or row.get("metaData") or {}
        if tx.get("TransactionType") != "Payment":
            continue
        if tx.get("Destination") != address:
            continue
        if (meta.get("TransactionResult") or "") != "tesSUCCESS":
            continue
        # tesSUCCESS в НЕвалидированной строке — предварительный исход: такую
        # транзакцию реестр ещё может не принять. Засчитать её как выплату
        # значит закрыть заявку до того, как деньги окончательно ушли
        # (замечание codex 03.08). Ждём подтверждения реестра — «пока не
        # знаем» здесь безопаснее, чем «уже да»: строка появится в следующем
        # проходе через полчаса.
        if row.get("validated") is not True:
            continue
        # delivered_amount — то, что реально дошло. У частичных платежей оно
        # МЕНЬШЕ Amount, и брать Amount значило бы засчитать недоплату полной.
        amt = meta.get("delivered_amount")
        if amt is None:
            amt = tx.get("Amount")
        if not isinstance(amt, str):
            continue          # выпуски токенов (dict) — не наш XRP
        try:
            value = int(amt) / 1_000_000.0   # дропы → XRP
        except (TypeError, ValueError):
            continue
        # Тег назначения. Ждали конкретный — берём только его: адрес биржи
        # общий, тег и есть «кому именно».
        if dest_tag is not None:
            try:
                if int(tx.get("DestinationTag")) != int(dest_tag):
                    continue
            except (TypeError, ValueError):
                continue        # тега в платеже нет вовсе — это не наш клиент
        out.append({
            "txid": tx.get("hash") or row.get("hash") or "",
            "amount": value,
            "ts": int(tx.get("date", 0)) + 946684800 if tx.get("date") else 0,
            "senders": [tx.get("Account")] if tx.get("Account") else [],
            # Сюда попадают только tesSUCCESS — валидированный реестром платёж.
            # Без этого поля judge() молча отбрасывает КАЖДЫЙ перевод, и весь
            # добытчик выглядит работающим, не находя ничего никогда.
            "confirmed": True,
        })
    return [t for t in out if t["txid"]]


def _incoming_evm(address: str) -> list[dict]:
    """Входящие ETH на адрес клиента — через публичный обозреватель.

    Ключа Etherscan у проекта нет, поэтому берём Blockscout: у него открытый
    API без ключа. Нет ответа — пустой список, а не исключение: сверка не должна
    падать целиком из-за одной недоступной сети.
    """
    base = os.getenv("EVM_EXPLORER_API", "https://eth.blockscout.com/api")
    try:
        data = _get_json(base, {"module": "account", "action": "txlist",
                                "address": address, "sort": "desc", "page": 1,
                                "offset": 50}) or {}
        rows = data.get("result") or []
        if not isinstance(rows, list):
            return []
    except Exception as e:
        logger.warning("payout_discovery: EVM %s: %s", address[:12], type(e).__name__)
        return []
    tip = _evm_tip_if_needed(rows, base)
    out = []
    for t in rows:
        try:
            if _norm(t.get("to")) != _norm(address):
                continue
            # Неуспешные транзакции: у Blockscout isError='1'. Засчитать
            # провалившийся перевод значило бы закрыть заявку по деньгам,
            # которые никуда не ушли.
            if str(t.get("isError", "0")) == "1":
                continue
            if str(t.get("txreceipt_status", "1")) == "0":
                continue
            value = int(t.get("value") or 0) / 1e18
            if value <= 0:
                continue        # вызовы контрактов без перевода
            out.append({
                "txid": t.get("hash") or "",
                "amount": value,
                "ts": int(t.get("timeStamp") or 0),
                "senders": [_norm(t.get("from"))] if t.get("from") else [],
                # Провалившиеся отсеяны выше, значит эти — исполненные. Без
                # поля judge() отбрасывает их все, и путь ETH мёртв молча.
                "confirmed": True,
                # Подтверждения: поле обозревателя, а если его нет — расстояние
                # до вершины. В Ethereum порог двенадцать, и «в блоке» про него
                # не говорит ничего.
                "confirmations": _evm_confirmations(t, tip),
            })
        except (TypeError, ValueError):
            continue
    return [t for t in out if t["txid"]]


def _incoming_erc20(address: str, token="USDT") -> list[dict]:
    """Входящие USDT в сети Ethereum — это ТОКЕН, а не сам ETH.

    Отдельный читатель, потому что `txlist` (обычные транзакции) токен-переводов
    не содержит вовсе: выплата USDT-ERC20 была бы невидима, даже когда ETH в той
    же сети виден. Нужен `tokentx`, и суммы там в единицах токена (у USDT шесть
    знаков, а не восемнадцать, как у ETH) — делить на 1e18 значило бы увидеть
    вместо 25 USDT ноль и решить, что выплаты не было.
    """
    base = os.getenv("EVM_EXPLORER_API", "https://eth.blockscout.com/api")
    try:
        data = _get_json(base, {"module": "account", "action": "tokentx",
                                "address": address, "sort": "desc",
                                "page": 1, "offset": 50}) or {}
        rows = data.get("result") or []
        if not isinstance(rows, list):
            return []
    except Exception as e:
        logger.warning("payout_discovery: ERC-20 %s: %s", address[:12], type(e).__name__)
        return []
    want = str(token or "USDT").upper()
    # Символ токена — это просто строка, которую контракт себе выбрал. Любой
    # может выпустить свой «USDT» и отправить с него Transfer с нужными нам
    # получателем, суммой и даже нашим адресом в поле отправителя: сверка
    # признала бы заявку выплаченной, хотя настоящих USDT никто не переводил.
    # Поэтому решает АДРЕС КОНТРАКТА, а символ остаётся вторичной проверкой.
    want_contract = ""
    if want == "USDT":
        try:
            from wallet.evm_wallet import USDT_ERC20 as _usdt
            want_contract = _norm(_usdt)
        except Exception:
            logger.warning("payout_discovery: адрес контракта USDT недоступен — "
                           "ERC-20 сверка отключена (фейл-клоуз)")
            return []
    if not want_contract:
        # Неизвестный токен: сверять не по чему, а «по имени» — нельзя.
        return []
    tip = _evm_tip_if_needed(rows, base)
    out = []
    for t in rows:
        try:
            if _norm(t.get("contractAddress")) != want_contract:
                continue
            if (t.get("tokenSymbol") or "").upper() != want:
                continue
            if _norm(t.get("to")) != _norm(address):
                continue
            # Знаков у токена столько, сколько он объявил, а не сколько у ETH.
            dec = int(t.get("tokenDecimal") or 6)
            value = int(t.get("value") or 0) / (10 ** dec)
            if value <= 0:
                continue
            out.append({
                "txid": t.get("hash") or "",
                "amount": value,
                "ts": int(t.get("timeStamp") or 0),
                "senders": [_norm(t.get("from"))] if t.get("from") else [],
                # В tokentx попадают только исполненные переводы.
                "confirmed": True,
                "confirmations": _evm_confirmations(t, tip),
            })
        except (TypeError, ValueError):
            continue
    return [t for t in out if t["txid"]]


def _incoming_ton(address: str, memo=None) -> list[dict]:
    """Входящие TON на адрес клиента — через публичный toncenter.

    Как и у XRP, у TON есть «кому именно» внутри одного адреса: комментарий
    (memo). Биржи дают всем клиентам ОДИН адрес и различают их комментарием, так
    что без сверки memo перевод нужного размера закрыл бы чужую заявку.

    Ключ toncenter необязателен, но без него сервис жёстко ограничивает частоту;
    TONCENTER_API_KEY задаётся владельцем, когда проходов станет много.
    """
    # Адрес сервиса и ключ — из модуля кошелька TON, одной точкой на проект:
    # разойдясь, сверка смотрела бы один узел, а баланс другой, и это две
    # разные правды об одном счёте.
    from wallet import ton_wallet as _tw
    base = _tw.api_url("getTransactions")
    params = _tw.api_params({"address": address, "limit": 50, "archival": "true"})
    try:
        data = _get_json(base, params) or {}
        rows = data.get("result") or []
        if not isinstance(rows, list):
            return []
    except Exception as e:
        logger.warning("payout_discovery: TON %s: %s", str(address)[:12], type(e).__name__)
        return []
    out = []
    for t in rows:
        try:
            # Откатившаяся транзакция — не выплата: сумма во входящем
            # сообщении положительна, но монеты вернулись отправителю.
            # Признак берём у модуля кошелька, чтобы правило было одно на все
            # чтения TON (сверка и страж продажи). Нашёл codex.
            if _tw.tx_failed(t):
                continue
            inp = t.get("in_msg") or {}
            # Нас интересуют только ВХОДЯЩИЕ с суммой: исходящие и служебные
            # сообщения к выплате отношения не имеют.
            val = int(inp.get("value") or 0)
            if val <= 0:
                continue
            if memo not in (None, ""):
                if (inp.get("message") or "").strip() != str(memo).strip():
                    continue
            # toncenter отдаёт хеш в base64, а весь остальной проект (проверка
            # is_txid, дедупликация занятых переводов, ссылка в обозреватель)
            # работает с hex64. Приводим здесь, чтобы форма была одна на всех:
            # иначе выплата TON не пройдёт даже проверку «это вообще хеш» и
            # клиент останется без доказательства.
            raw_hash = (t.get("transaction_id") or {}).get("hash") or ""
            out.append({
                "txid": _ton_hash_hex(raw_hash),
                "amount": val / 1e9,          # нанотоны → TON
                "ts": int(t.get("utime") or 0),
                "senders": [_norm_account("TON", inp.get("source"))] if inp.get("source") else [],
                # toncenter отдаёт уже включённые в блок транзакции.
                "confirmed": True,
            })
        except (TypeError, ValueError):
            continue
    return [t for t in out if t["txid"]]


def incoming_transfers(currency: str, address: str, network=None) -> list[dict]:
    cur = str(currency or "").upper()
    if cur in ("BTC", "LTC"):
        return _incoming_btc_like(address, cur)
    if cur == "USDT":
        # У USDT две сети, и монеты в них разные по своей природе: TRC-20 живёт
        # в TRON, ERC-20 — токен в Ethereum. Искать по одной сети обе — значит
        # не найти половину выплат и при этом считать, что искали.
        net = str(network or "").upper()
        if net in ("ERC20", "ETH", "ETHEREUM"):
            return _incoming_erc20(address, "USDT")
        return _incoming_trc20(address)
    if cur == "XRP":
        # У XRP адрес заявки может быть X-адресом (тег внутри) — на цепи платёж
        # идёт на classic-адрес, поэтому ищем по нему. Но тег НЕ отбрасываем:
        # classic-адрес биржи общий на всех её клиентов, и без сверки тега
        # перевод подходящего размера закрыл бы чужую заявку.
        classic, tag = _xrp_destination(address)
        return _incoming_xrpl(classic, tag)
    if cur == "ETH":
        return _incoming_evm(address)
    if cur == "TON":
        # Комментарий хранится в заявке отдельным полем; сюда он приходит
        # приклеенным к адресу тем же способом, что и тег XRP.
        addr, memo = _ton_destination(address)
        return _incoming_ton(addr, memo)
    return []


def _ton_hash_hex(value: str) -> str:
    """Хеш транзакции TON в общей для проекта форме («» — не хеш).

    Своего приведения здесь нет намеренно: правило одно на весь проект и живёт
    в core.txid. Копия разошлась бы с проверкой is_txid, и сверка признавала бы
    выплату, ссылку на которую бот показать отказывается.
    """
    from core.txid import normalize_txid
    return normalize_txid(value, "TON") or ""


def _ton_destination(address: str):
    """(адрес, memo) из того, что лежит в заявке. Разделитель — '#'.

    В адресе TON его быть не может: дружественная форма — base64url (буквы,
    цифры, '-', '_'), сырая — 'workchain:hex'. Значит склейка однозначна и
    обратно разбирается без догадок.
    """
    s = str(address or "").strip()
    if "#" in s:
        addr, _, memo = s.partition("#")
        return addr.strip(), memo.strip()
    return s, None


def _xrp_destination(address: str):
    """(classic-адрес, тег) из того, что лежит в заявке — X-адрес или classic.

    Тег возвращается отдельно и обязателен к сверке: он и есть «кому именно»,
    когда classic-адрес общий на всех клиентов биржи.
    """
    try:
        import sys
        _relay = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _relay not in sys.path:
            sys.path.insert(0, _relay)
        from wallet.xrp_wallet import parse_destination
        classic, tag = parse_destination(address)
        return (classic or str(address or "")), tag
    except Exception:
        return str(address or ""), None


# ─────────────────────────────────────────────────────────────────
# Вердикт по одной заявке
# ─────────────────────────────────────────────────────────────────
def judge(order: dict, transfers: list[dict], used_txids: set,
          trusted: set, tolerance_pct: float | None = None) -> dict:
    """Чистая логика: какой перевод закрывает заявку и можно ли закрыть.

    Вынесена отдельно от сети, чтобы проверяться тестами без обозревателей.
    """
    from core import chain_confirm
    tol = AMOUNT_TOLERANCE_PCT if tolerance_pct is None else float(tolerance_pct)
    expected = float(order.get("expected_amount") or 0)
    paid_ts = int(order.get("paid_ts") or 0)
    cur_for_net = order.get("currency")
    net_for_net = order.get("network")
    fixed = bool(order.get("expected_fixed", True))
    res = {"order_id": order.get("order_id"), "action": "none",
           "candidates": [], "near": [], "expected": expected,
           "expected_fixed": fixed, "reason": ""}
    immature = []          # подошли всем, кроме окончательности
    if expected <= 0:
        res["reason"] = "неизвестен ожидаемый объём выплаты"
        return res

    lo = expected * (1 - tol / 100.0)
    hi = expected * (1 + tol / 100.0)
    for t in transfers:
        txid = t.get("txid")
        # Сравниваем нормализованно: занятые txid приходят приведёнными, и
        # разный регистр здесь означал бы «перевод свободен» — то есть один
        # перевод закрыл бы две заявки.
        if not txid or _norm(txid) in {_norm(u) for u in used_txids}:
            continue
        # Перевод обязан быть ПОСЛЕ оплаты заявки: приход на адрес клиента
        # до неё — его собственные деньги, а не наша выплата.
        if paid_ts and int(t.get("ts") or 0) < paid_ts:
            continue
        amount = float(t.get("amount") or 0)
        if not (lo <= amount <= hi):
            # Мимо допуска — но, может быть, рядом. Такой перевод НЕ становится
            # кандидатом и кнопки закрытия не получает: денежное правило не
            # смягчается ни на процент. Он только перестаёт быть невидимым.
            off = abs(amount - expected) / expected * 100.0 if expected else 0.0
            if (amount > 0 and off <= NEAR_TOLERANCE_PCT
                    and chain_confirm.is_final(t, cur_for_net, net_for_net)):
                res["near"].append({
                    "txid": txid, "amount": amount, "ts": t.get("ts"),
                    "off_pct": round(off, 2),
                    "senders": sorted({_norm(s) for s in (t.get("senders") or set()) if s}),
                })
            continue
        # Окончательность проверяем ПОСЛЕДНЕЙ, уже среди подходящих. Порядок
        # тут не косметика: на адрес клиента прилетает пыль и его собственные
        # переводы, и если спрашивать порог первым, любой чужой незрелый перевод
        # попадёт в `immature` — оператору скажут «ваш перевод найден, но ещё не
        # окончателен», хотя нашего перевода там нет вовсе. Ложное «уже нашли»
        # хуже честного «не нашли»: по нему перестают искать. Забраковал codex.
        if not chain_confirm.is_final(t, cur_for_net, net_for_net):
            # Сам флаг «в блоке» здесь НЕ читаем: решение об окончательности
            # целиком за chain_confirm — иначе рядом с ним заводится второе,
            # своё правило.
            immature.append(chain_confirm.finality_note(
                t, cur_for_net, net_for_net))
            continue
        # Нормализуем здесь ТОЖЕ, хотя источники это уже делают: иначе новый
        # добытчик цепочки, забывший про регистр, молча перестал бы узнавать
        # наш кошелёк — заявки просто не закрывались бы без всякой ошибки.
        senders = {_norm(s) for s in (t.get("senders") or set()) if s}
        res["candidates"].append({
            "txid": txid, "amount": amount, "ts": t.get("ts"),
            "trusted": bool(senders & {_norm(x) for x in trusted}),
            "senders": sorted(senders),
        })

    if not res["candidates"]:
        # Три РАЗНЫХ ответа вместо одного «не найдено». Разница не косметическая:
        # по «не найдено» человек перестаёт искать, и если перевод при этом
        # лежит на адресе, выплата теряется вместе с заявкой.
        if res["near"]:
            res["near"].sort(key=lambda n: n["off_pct"])
            n = res["near"][0]
            why = ("" if fixed else
                   "; котировка в заявке не зафиксирована, объём пересчитан по "
                   "СЕГОДНЯШНЕМУ курсу — за дни он ушёл, и расхождение может "
                   "быть только из-за этого")
            res["reason"] = (
                f"перевод на адресе есть — {n['amount']:g}, ждали {expected:g} "
                f"(расхождение {n['off_pct']:g}%), это мимо допуска {tol:g}%{why}. "
                f"Закрывать автоматически нельзя, сверьте и решите сами")
        elif immature:
            # Отличаем «ничего нет» от «есть, но рано»: иначе оператор ищет
            # глазами перевод, который система уже нашла и молча отложила.
            res["reason"] = f"перевод найден, но ещё не окончателен ({immature[0]})"
        else:
            res["reason"] = "подходящих переводов на адрес клиента не найдено"
        return res
    if len(res["candidates"]) > 1:
        res["action"] = "review"
        res["reason"] = (f"подходящих переводов несколько ({len(res['candidates'])}) — "
                         f"выбрать должен человек")
        return res

    only = res["candidates"][0]
    if not only["trusted"]:
        res["action"] = "review"
        res["reason"] = ("сумма сошлась, но отправитель нам не принадлежит — "
                         "подтвердить может только человек "
                         "(добавьте свой кошелёк: /paysrc)")
        return res
    res["action"] = "close"
    res["txid"] = only["txid"]
    res["amount"] = only["amount"]
    res["reason"] = "перевод с нашего кошелька на адрес клиента — выплата состоялась"
    return res


# ─────────────────────────────────────────────────────────────────
# Проход по зависшим заявкам
# ─────────────────────────────────────────────────────────────────
def _db():
    import sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def stuck_orders() -> list[dict]:
    """Заявки, оплаченные клиентом, но без доказательства выдачи."""
    import sqlite3
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT order_id, user_id, rub_amount, currency, network, "
                "       crypto_address, agreed_crypto_amount, "
                "       CAST(strftime('%s', COALESCE(updated_at, created_at)) AS INT) paid_ts "
                "FROM orders "
                "WHERE status='paid' AND (paid_btc_tx IS NULL OR paid_btc_tx='') "
                "  AND COALESCE(updated_at, created_at) <= datetime('now', ?) "
                "  AND COALESCE(updated_at, created_at) >= datetime('now', ?) "
                "ORDER BY COALESCE(updated_at, created_at)",
                (f"-{MIN_AGE_MIN} minutes", f"-{MAX_AGE_DAYS} days")).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as e:
        logger.error("payout_discovery: чтение orders: %s", e)
        return []


def _used_txids() -> set:
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT paid_btc_tx FROM orders "
                "WHERE paid_btc_tx IS NOT NULL AND paid_btc_tx != ''").fetchall()
        return {_norm(r[0]) for r in rows}
    except Exception as e:
        logger.error("payout_discovery: чтение занятых txid: %s", e)
        # Fail-CLOSED: не зная, какие переводы уже закреплены, закрывать нельзя —
        # один перевод мог бы закрыть две заявки.
        raise


def quote_is_fixed(order: dict) -> bool:
    """Зафиксирован ли объём выплаты в самой заявке.

    Разница принципиальная для сверки. Зафиксированный объём — это обещание,
    данное клиенту в момент создания заявки, и перевод обязан совпасть с ним
    с точностью до допуска. Незафиксированный приходится пересчитывать по
    СЕГОДНЯШНЕМУ курсу, а выплата могла уйти неделю назад: на волатильной монете
    расхождение в проценты набегает само, безо всякой ошибки. Сравнивать их
    одной меркой — значит систематически отвергать верные переводы и молчать
    об этом.
    """
    agreed = order.get("agreed_crypto_amount")
    try:
        return bool(agreed) and float(agreed) > 0
    except (TypeError, ValueError):
        return False


def expected_amount(order: dict, rate_fn=None) -> float:
    """Сколько должно было уйти клиенту: обещанное при создании заявки, а при
    его отсутствии — пересчёт по курсу (для старых заявок)."""
    agreed = order.get("agreed_crypto_amount")
    if agreed and float(agreed) > 0:
        return float(agreed)
    if rate_fn is None:
        return 0.0
    try:
        rate = float(rate_fn(order.get("currency"), order.get("rub_amount")) or 0)
        return round(float(order.get("rub_amount") or 0) / rate, 8) if rate else 0.0
    except Exception:
        return 0.0



def _fetch_transfers(fetch, currency, address, network):
    """Зовёт источник переводов, не ломая старый контракт (currency, address).

    Сеть добавилась позже — а `fetch` подменяют снаружи (тесты, будущие
    источники). Позвать двухаргументную функцию с тремя значит получить
    TypeError, который выше ловится общим `except` и превращается в «цепочка
    недоступна»: сверка молча перестала бы находить что-либо вообще.

    Сигнатуру СПРАШИВАЕМ, а не выясняем по исключению (замечание codex 03.08):
    ловля TypeError не отличает «функция принимает два аргумента» от «внутри
    функции разбор ответа упал с TypeError». Во втором случае повтор без сети
    ушёл бы искать USDT не в той цепи (ERC-20 → по умолчанию TRC-20) и спрятал
    бы настоящий сбой. Не удалось разобрать сигнатуру — зовём с сетью и
    отвечаем за это честной ошибкой наверх.
    """
    import inspect
    try:
        sig = inspect.signature(fetch)
    except (TypeError, ValueError):
        sig = None                      # сигнатура недоступна (C-функция и т.п.)
    if sig is not None:
        try:
            sig.bind(currency, address, network)
        except TypeError:
            return fetch(currency, address)
    return fetch(currency, address, network)


def discover(rate_fn=None, fetch=None) -> dict:
    """Ищет доказательства выплаты по всем зависшим заявкам.

    rate_fn(currency, rub) — курс для старых заявок без зафиксированной
    котировки; fetch(currency, address, network) — источник переводов
    (подменяется в тестах). Сеть обязательна: у USDT их две, и монета в них
    разная — без неё половина выплат ищется не в той цепи.
    Ничего не меняет: возвращает список вердиктов.
    """
    fetch = fetch or incoming_transfers
    out = {"checked": 0, "close": [], "review": [], "near": [], "none": 0,
           "errors": []}
    try:
        used = _used_txids()
    except Exception as e:
        out["errors"].append(f"не удалось прочитать занятые txid: {type(e).__name__}")
        return out
    trusted_cache: dict[str, set] = {}

    for o in stuck_orders():
        out["checked"] += 1
        cur = (o.get("currency") or "").upper()
        addr = o.get("crypto_address")
        if not addr:
            continue
        if cur not in trusted_cache:
            trusted_cache[cur] = trusted_senders(cur)
        try:
            transfers = _fetch_transfers(fetch, cur, addr, o.get("network"))
        except Exception as e:
            out["errors"].append(f"#{o['order_id']}: цепочка недоступна ({type(e).__name__})")
            continue
        v = judge({**o, "expected_amount": expected_amount(o, rate_fn),
                   "expected_fixed": quote_is_fixed(o)},
                  transfers, used, trusted_cache[cur])
        v["currency"] = cur
        v["rub_amount"] = o.get("rub_amount")
        v["user_id"] = o.get("user_id")
        v["network"] = o.get("network")
        v["address"] = addr
        if v["action"] == "close":
            used.add(_norm(v["txid"]))   # в рамках прохода перевод уже занят
            out["close"].append(v)
        elif v["action"] == "review":
            out["review"].append(v)
        else:
            # «Ничего не нашли» и «нашли рядом, но закрыть не вправе» — разные
            # исходы, и второй обязан быть виден. Действие при этом остаётся
            # `none`: кнопки закрытия такая находка не получает.
            if v.get("near"):
                out["near"].append(v)
            out["none"] += 1
    return out


def candidates_for(order_id: int, rate_fn=None, fetch=None) -> dict:
    """Вердикт по ОДНОЙ заявке — для подтверждения человеком.

    Пересчитывается заново в момент нажатия, а не берётся из кнопки: между
    показом отчёта и решением заявку мог закрыть кто-то другой, а перевод —
    оказаться закреплён за соседней заявкой.
    """
    fetch = fetch or incoming_transfers
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT order_id, user_id, rub_amount, currency, network, "
                "       crypto_address, agreed_crypto_amount, status, paid_btc_tx, "
                "       CAST(strftime('%s', COALESCE(updated_at, created_at)) AS INT) paid_ts "
                "FROM orders WHERE order_id=?", (order_id,)).fetchone()
    except Exception as e:
        return {"error": f"чтение заявки: {type(e).__name__}: {e}"}
    if not row:
        return {"error": f"заявка #{order_id} не найдена"}
    o = dict(row)
    if o.get("status") != "paid" or (o.get("paid_btc_tx") or "").strip():
        return {"error": f"заявка #{order_id} уже не ждёт выдачи (статус {o.get('status')})"}
    try:
        used = _used_txids()
    except Exception:
        return {"error": "не удалось прочитать занятые txid — закрывать нельзя"}
    cur = (o.get("currency") or "").upper()
    try:
        transfers = _fetch_transfers(fetch, cur, o.get("crypto_address"), o.get("network"))
    except Exception as e:
        return {"error": f"цепочка недоступна: {type(e).__name__}"}
    v = judge({**o, "expected_amount": expected_amount(o, rate_fn),
               "expected_fixed": quote_is_fixed(o)},
              transfers, used, trusted_senders(cur))
    v["currency"] = cur
    v["network"] = o.get("network")
    v["user_id"] = o.get("user_id")
    v["rub_amount"] = o.get("rub_amount")
    v["address"] = o.get("crypto_address")
    return v


def alert_fingerprint(res: dict) -> str:
    """Отпечаток находок прохода — ключ окна молчания для тревоги.

    Живёт здесь, а не в боте, по одной причине: это правило «что считать той же
    самой новостью», и проверить его можно только тестом. Внутри обработчика
    оно проверялось бы глазами, а ошибиться тут легко и незаметно — окно просто
    съест сообщение, и никто не узнает.

    Считаем по ЗАЯВКАМ И ПЕРЕВОДАМ. По одним номерам заявок второй найденный
    перевод не менял бы ключ и молчал до конца окна — но окно существует, чтобы
    гасить повтор одной новости, а не новую. Нашёл codex.
    """
    def one(v, key):
        txs = sorted(_norm(t.get("txid"))[:16] for t in (v.get(key) or []))
        return f"{v.get('order_id')}:{'+'.join(txs)}"
    review = sorted(one(v, "candidates") for v in (res.get("review") or []))
    near = sorted(one(v, "near") for v in (res.get("near") or []))
    return "discovery:review:" + ",".join(review) + "|near:" + ",".join(near)


def format_report(res: dict, max_items: int = 6) -> str:
    """Сводка для Telegram или '' — если рассказывать не о чем."""
    if (not res.get("close") and not res.get("review") and not res.get("near")
            and not res.get("errors")):
        return ""
    lines = ["⛓ <b>Сверка выдачи с блокчейном</b>\n",
             f"<blockquote>Проверено зависших заявок: <b>{res.get('checked', 0)}</b>\n"
             f"Закрыто по доказательству: <b>{len(res.get('close', []))}</b>\n"
             f"Требуют решения: <b>{len(res.get('review', []))}</b>\n"
             f"Похожи, но мимо допуска: <b>{len(res.get('near', []))}</b></blockquote>"]
    for v in res.get("close", [])[:max_items]:
        lines.append(f"\n✅ #{v['order_id']} — {v.get('amount')} {v['currency']}, "
                     f"tx <code>{(v.get('txid') or '')[:16]}…</code>")
    for v in res.get("review", [])[:max_items]:
        lines.append(f"\n🟡 #{v['order_id']} ({v.get('rub_amount'):g} ₽ → {v['currency']}): "
                     f"{v['reason']}")
        for c in v.get("candidates", [])[:2]:
            lines.append(f"   <code>{c['txid'][:20]}…</code> {c['amount']} "
                         f"от {', '.join(c['senders'])[:48]}")
    for v in res.get("near", [])[:max_items]:
        lines.append(f"\n🔍 #{v['order_id']} ({v.get('rub_amount'):g} ₽ → "
                     f"{v['currency']}): {v['reason']}")
        for n in v.get("near", [])[:2]:
            # Хеш ЦЕЛИКОМ, а не обрезанный: по такой находке кнопки нет, и
            # единственный путь дальше — руками через /force_payout. Обрезанный
            # хеш превращает подсказку в задание «найди остаток сам».
            lines.append(f"   <code>{n['txid']}</code>\n"
                         f"   {n['amount']:g} ({n['off_pct']:g}% мимо) от "
                         f"{', '.join(n['senders'])[:48]}\n"
                         f"   <code>/force_payout {v['order_id']} {n['txid']}</code>")
    for e in res.get("errors", [])[:3]:
        lines.append(f"\n⚠️ {e}")
    return "\n".join(lines)
