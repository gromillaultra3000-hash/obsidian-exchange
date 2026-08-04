#!/usr/bin/env python3
"""Сверка выплат: XRPL и EVM. Разбор ответа цепи, без сети.

Ручная выдача XRP — ЕДИНСТВЕННЫЙ путь (авто-выплаты для него нет вовсе), и
сверка, которая ловит ручные выдачи, про XRP не знала ничего. Здесь проверяется
то, на чём такая слепота дорого стоит: что считается доставленным, что —
провалившимся, и не примем ли мы за выплату чужой перевод.

Запуск: python3 tests/test_discovery_chains.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import payout_discovery as pd  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def main():
    ADDR = "rClientAddressXXXXXXXXXXXXXXXXXXXX"

    # ── XRPL ──────────────────────────────────────────────────────────
    xrpl = {"result": {"transactions": [
        # обычный доставленный платёж
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "AAA",
                "Account": "rOurWallet", "Amount": "12500000", "date": 780000000},
         "validated": True, "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "12500000"}},
        # ЧАСТИЧНЫЙ платёж: заявлено много, дошло мало — считать надо дошедшее
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "BBB",
                "Account": "rOurWallet", "Amount": "99000000", "date": 780000100},
         "validated": True, "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "1000000"}},
        # неуспешная — денег не было
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "CCC",
                "Account": "rOurWallet", "Amount": "50000000", "date": 780000200},
         "validated": True, "meta": {"TransactionResult": "tecUNFUNDED_PAYMENT", "delivered_amount": "50000000"}},
        # чужому адресу
        {"tx": {"TransactionType": "Payment", "Destination": "rSomeoneElse", "hash": "DDD",
                "Account": "rOurWallet", "Amount": "7000000", "date": 780000300},
         "validated": True, "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "7000000"}},
        # не платёж
        {"tx": {"TransactionType": "TrustSet", "Destination": ADDR, "hash": "EEE",
                "Account": "rOurWallet", "date": 780000400},
         "validated": True, "meta": {"TransactionResult": "tesSUCCESS"}},
        # предварительный успех: реестр ещё НЕ подтвердил. Такую транзакцию
        # можно потерять — засчитать её значит закрыть заявку раньше денег.
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "GGG",
                "Account": "rOurWallet", "Amount": "31000000", "date": 780000600},
         "validated": False,
         "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "31000000"}},
        # поля validated нет вовсе — тоже не доказательство
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "HHH",
                "Account": "rOurWallet", "Amount": "42000000", "date": 780000700},
         "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "42000000"}},
        # платёж токеном (Amount — объект, не дропы)
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "FFF",
                "Account": "rIssuer", "date": 780000500,
                "Amount": {"currency": "USD", "value": "10", "issuer": "rI"}},
         "validated": True, "meta": {"TransactionResult": "tesSUCCESS",
                  "delivered_amount": {"currency": "USD", "value": "10", "issuer": "rI"}}},
    ]}}

    import requests
    real_post = requests.post
    requests.post = lambda *a, **k: _Resp(xrpl)
    try:
        got = pd._incoming_xrpl(ADDR)
    finally:
        requests.post = real_post
    by = {t["txid"]: t for t in got}
    check(set(by) == {"AAA", "BBB"},
          f"XRPL: взяты переводы {sorted(by)} — ждали только AAA и BBB")
    check("GGG" not in by and "HHH" not in by,
          "XRPL: неподтверждённая реестром транзакция засчитана как выплата — "
          "заявка закроется раньше, чем деньги окончательно уйдут")
    check(abs(by.get("AAA", {}).get("amount", 0) - 12.5) < 1e-9,
          f"XRPL: дропы не переведены в XRP ({by.get('AAA', {}).get('amount')})")
    check(abs(by.get("BBB", {}).get("amount", 0) - 1.0) < 1e-9,
          "XRPL: у частичного платежа взята заявленная сумма вместо доставленной "
          "— недоплата закрыла бы заявку как полная выплата")
    check(by.get("AAA", {}).get("senders") == ["rOurWallet"],
          "XRPL: отправитель не разобран — авто-закрытие по своему кошельку не сработает")
    check(by.get("AAA", {}).get("ts", 0) > 1_600_000_000,
          "XRPL: время не переведено из ripple-эпохи в unix — перевод окажется "
          "«раньше оплаты» и будет отброшен")

    # сеть недоступна → пусто, а не исключение
    def _boom(*a, **k):
        raise OSError("нет сети")
    requests.post = _boom
    try:
        check(pd._incoming_xrpl(ADDR) == [], "XRPL: сбой сети не даёт пустой список")
    finally:
        requests.post = real_post

    # ── EVM ───────────────────────────────────────────────────────────
    EADDR = "0x00000000000000000000000000000000000000aa"
    evm = {"result": [
        {"hash": "0x1", "to": EADDR.upper(), "from": "0xOUR", "value": str(10**18),
         "timeStamp": "1780000000", "isError": "0", "txreceipt_status": "1"},
        # провалившаяся
        {"hash": "0x2", "to": EADDR, "from": "0xOUR", "value": str(5 * 10**17),
         "timeStamp": "1780000100", "isError": "1", "txreceipt_status": "0"},
        # вызов контракта без перевода
        {"hash": "0x3", "to": EADDR, "from": "0xOUR", "value": "0",
         "timeStamp": "1780000200", "isError": "0", "txreceipt_status": "1"},
        # чужому адресу
        {"hash": "0x4", "to": "0xbeef", "from": "0xOUR", "value": str(10**18),
         "timeStamp": "1780000300", "isError": "0", "txreceipt_status": "1"},
    ]}
    real_get = pd._get_json
    pd._get_json = lambda *a, **k: evm
    try:
        got = pd._incoming_evm(EADDR)
    finally:
        pd._get_json = real_get
    ids = {t["txid"] for t in got}
    check(ids == {"0x1"}, f"EVM: взяты {sorted(ids)} — ждали только 0x1 "
                          f"(провалившаяся, нулевая и чужая должны отсеяться)")
    check(got and abs(got[0]["amount"] - 1.0) < 1e-9,
          f"EVM: wei не переведены в ETH ({got[0]['amount'] if got else '—'})")

    pd._get_json = lambda *a, **k: (_ for _ in ()).throw(OSError("нет сети"))
    try:
        check(pd._incoming_evm(EADDR) == [], "EVM: сбой обозревателя не даёт пустой список")
    finally:
        pd._get_json = real_get

    # ── маршрутизация по валюте ───────────────────────────────────────
    seen = {}
    # Читатели берём из модуля: список руками отстаёт от кода, и новая цепь
    # уходила бы в настоящую сеть вместо шпиона.
    for name in [n for n in dir(pd) if n.startswith("_incoming_")]:
        setattr(pd, name, (lambda n: (lambda *a, **k: seen.setdefault(n, a) or []))(name))
    try:
        for cur, want in (("BTC", "_incoming_btc_like"), ("LTC", "_incoming_btc_like"),
                          ("USDT", "_incoming_trc20"), ("XRP", "_incoming_xrpl"),
                          ("ETH", "_incoming_evm"), ("xrp", "_incoming_xrpl"),
                          ("TON", "_incoming_ton")):
            seen.clear()
            pd.incoming_transfers(cur, "addr")
            check(want in seen, f"{cur}: сверка не пошла в {want} — выплата в этой "
                                f"сети остаётся невидимой навсегда")
        seen.clear()
        check(pd.incoming_transfers("DOGE", "addr") == [],
              "незнакомая валюта не даёт пустой список")
        check(not seen, "незнакомая валюта ушла в чужой обозреватель")
    finally:
        import importlib
        importlib.reload(pd)

    # ── у USDT ДВЕ сети, и монета в них разная ───────────────────────
    # TRC-20 живёт в TRON, ERC-20 — токен в Ethereum. Искать обе в одной цепи
    # значит не найти половину выплат и считать, что искали. Плюс знаки: у
    # USDT их шесть, у ETH восемнадцать — перепутать значит увидеть ноль
    # вместо 25 USDT и решить, что выплаты не было.
    UA = "0x00000000000000000000000000000000000000aa"
    seen = {}
    # Настоящий контракт USDT в Ethereum — тот же, которым мы платим.
    REAL_USDT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    tokentx = {"result": [
        {"hash": "0xU", "to": UA, "from": "0xour", "value": str(25 * 10**6),
         "tokenSymbol": "USDT", "tokenDecimal": "6", "timeStamp": "1780000000",
         "contractAddress": REAL_USDT},
        {"hash": "0xOTHER", "to": UA, "from": "0xx", "value": str(25 * 10**6),
         "tokenSymbol": "USDC", "tokenDecimal": "6", "timeStamp": "1780000100",
         "contractAddress": REAL_USDT},
        # Поддельный контракт: имя себе выбирает кто угодно, и Transfer он
        # выпускает с любыми полями — включая НАШ адрес в отправителе. Пройди
        # он проверку, заявка закрылась бы как выплаченная без единой монеты.
        {"hash": "0xFAKE", "to": UA, "from": "0xour", "value": str(25 * 10**6),
         "tokenSymbol": "USDT", "tokenDecimal": "6", "timeStamp": "1780000200",
         "contractAddress": "0x000000000000000000000000000000000000dead"},
    ]}
    # Запоминаем ВСЕ обращения, а не последнее: читатель ходит к обозревателю
    # ещё и за вершиной цепи, и «последний вызов» перестал бы говорить о том,
    # спросили ли мы вообще про токен-переводы.
    pd._get_json = lambda url, params=None, **k: (
        seen.setdefault("actions", []).append((params or {}).get("action"))
        or tokentx)
    real_trc = pd._incoming_trc20
    pd._incoming_trc20 = lambda a: (seen.update(chain="TRON") or [])
    try:
        erc = pd.incoming_transfers("USDT", UA, "ERC20")
        check("tokentx" in seen.get("actions", []),
              "USDT/ERC20 читается как обычные транзакции (txlist) — токен-переводов "
              "там нет вовсе, выплата невидима")
        check([t["txid"] for t in erc] == ["0xU"],
              f"USDT/ERC20: взято {[t['txid'] for t in erc]} — чужой токен и "
              f"поддельный контракт с именем USDT должны отсеяться")
        check("0xFAKE" not in [t["txid"] for t in erc],
              "USDT/ERC20: перевод с ЛЕВОГО контракта, назвавшегося USDT, принят "
              "за выплату — заявку можно закрыть, не отправив ни одной монеты")
        check(erc and abs(erc[0]["amount"] - 25.0) < 1e-9,
              f"USDT/ERC20: знаки токена перепутаны с ETH "
              f"({erc[0]['amount'] if erc else '—'} вместо 25.0)")
        seen.clear()
        pd.incoming_transfers("USDT", "TXxx", "TRC20")
        check(seen.get("chain") == "TRON", "USDT/TRC20 ушёл не в TRON")
        seen.clear()
        pd.incoming_transfers("USDT", "TXxx", None)
        check(seen.get("chain") == "TRON",
              "USDT без указания сети должен идти в TRON — историческое умолчание")
    finally:
        pd._get_json, pd._incoming_trc20 = real_get, real_trc

    # ── ПУТЬ ЦЕЛИКОМ: читатель → judge ───────────────────────────────
    # Тесты выше проверяют читателей по отдельности, и этого оказалось мало:
    # judge() молча отбрасывает перевод без флага confirmed, а читатели его не
    # ставили — весь путь находил бы НОЛЬ всегда и выглядел работающим.
    SHARED = "rExchangeSharedAddressXXXXXXXXXXXXX"

    def _xtx(h, drops, tag):
        return {"tx": {"TransactionType": "Payment", "Destination": SHARED, "hash": h,
                       "Account": "rOurWallet", "Amount": str(drops),
                       "date": 800000000, "DestinationTag": tag},
                "validated": True, "meta": {"TransactionResult": "tesSUCCESS",
                         "delivered_amount": str(drops)}}

    requests.post = lambda *a, **k: _Resp(
        {"result": {"transactions": [_xtx("НАШ", 25_000_000, 777),
                                     _xtx("ЧУЖОЙ", 25_000_000, 999)]}})
    try:
        order = {"order_id": 1, "currency": "XRP", "crypto_address": SHARED,
                 "expected_amount": 25.0, "paid_ts": 700000000}
        with_tag = pd.judge(order, pd._incoming_xrpl(SHARED, 777), set(),
                            trusted={"rourwallet"})
        no_tag = pd.judge(order, pd._incoming_xrpl(SHARED), set(),
                          trusted={"rourwallet"})
    finally:
        requests.post = real_post
    got = [c["txid"] for c in with_tag["candidates"]]
    check(got == ["НАШ"],
          f"XRPL: со сверкой тега кандидаты {got} — classic-адрес биржи общий "
          f"на всех клиентов, и без тега перевод того же размера закроет чужую "
          f"заявку")
    check(with_tag["action"] != "none",
          "XRPL: перевод не дошёл до вердикта — judge отбрасывает переводы без "
          "флага confirmed, и весь путь находит ноль всегда")
    check(len(no_tag["candidates"]) == 2,
          "проверка бессмысленна: чужой тег не воспроизвёлся")

    ETH_ADDR = "0x00000000000000000000000000000000000000aa"
    ETH_ORDER = {"order_id": 2, "currency": "ETH", "crypto_address": ETH_ADDR,
                 "expected_amount": 1.0, "paid_ts": 1700000000}

    def _erow(**extra):
        row = {"hash": "0xE", "to": ETH_ADDR, "from": "0xour", "value": str(10**18),
               "timeStamp": "1780000000", "isError": "0", "txreceipt_status": "1",
               "blockNumber": "1000000"}
        row.update(extra)
        return row

    def _eth_verdict(row, tip=None):
        """Прогон читатель→judge с подставным обозревателем.

        Вершину цепи отдаём отдельным ответом: `_incoming_evm` спрашивает её
        вторым запросом и только когда в строке нет подтверждений.
        """
        def fake(base, params=None, *a, **k):
            if (params or {}).get("action") == "eth_blockNumber":
                return {"result": tip} if tip is not None else {}
            return {"result": [row]}
        pd._get_json = fake
        try:
            return pd.judge(ETH_ORDER, pd._incoming_evm(ETH_ADDR), set(),
                            trusted={"0xour"})
        finally:
            pd._get_json = real_get

    # 1. Обычный ответ обозревателя: подтверждения есть в строке.
    check(_eth_verdict(_erow(confirmations="40"))["action"] != "none",
          "EVM: перевод не дошёл до вердикта — путь ETH мёртв")
    # 2. Поля confirmations нет (набор полей Blockscout меняется от версии к
    #    версии). Без счёта от вершины цепи порог в 12 подтверждений не взять
    #    НИКОГДА — и сверка ETH молча находила бы ноль всегда.
    check(_eth_verdict(_erow(), tip="0xF4288")["action"] != "none",
          "EVM: обозреватель не прислал confirmations — считать от вершины цепи "
          "некому, и путь ETH молча мёртв")
    # 3. Ни поля, ни вершины: закрывать заявку нельзя, но и молчать нельзя —
    #    причина обязана быть названа человеку.
    blind = _eth_verdict(_erow())
    check(blind["action"] == "none" and "окончател" in str(blind.get("reason", "")),
          f"EVM: без подтверждений и без вершины вердикт {blind.get('action')} "
          f"с причиной {blind.get('reason')!r} — молчание вместо объяснения")
    # 4. Свежий блок — перевод ещё не окончателен, закрывать рано.
    fresh = _eth_verdict(_erow(confirmations="3"))
    check(fresh["action"] == "none",
          "EVM: три подтверждения в Ethereum приняты за окончательные")

    # ── TON: один счёт в разных формах записи — один и тот же счёт ────
    # Обозреватель отдаёт отправителя сырым (`0:…`), а TON_PAYOUT_ADDRESS
    # владелец пишет дружественно (`UQ…`). Сравнение строк тут не «иногда
    # ошибается» — оно не совпадает НИКОГДА: своя выплата TON выглядела бы
    # чужой, и заявка не закрывалась бы автоматически ни при каких условиях.
    sys.path.insert(0, os.path.join(ROOT, "relay"))
    from core.address import ton_friendly_address    # noqa: E402
    RAW_OWN = "0:" + "ab" * 32
    FRIENDLY_OWN = ton_friendly_address(RAW_OWN)
    check(RAW_OWN != FRIENDLY_OWN, "формы записи счёта TON и правда различаются")
    check(pd._norm_account("TON", RAW_OWN) == pd._norm_account("TON", FRIENDLY_OWN),
          "TON: сырая и дружественная формы одного счёта дают разные ключи — "
          "своя выплата навсегда останется «чужой»")
    check(pd._norm_account("TON", RAW_OWN) != pd._norm_account("TON", "0:" + "cd" * 32),
          "TON: разные счета слились в один ключ")
    check(pd._norm_account("BTC", "BC1QXYZ") == "bc1qxyz",
          "у остальных валют правило сравнения не изменилось")

    ton_tx = {"ok": True, "result": [{
        # Хеш toncenter отдаёт в base64 от 32 байт — иначе он не пройдёт общую
        # проверку txid и перевод отбросится ещё до сравнения отправителя.
        "transaction_id": {"hash": __import__("base64").b64encode(bytes(range(32))).decode()},
        "utime": 1700000000,
        "in_msg": {"source": RAW_OWN, "value": str(2 * 10 ** 9), "message": ""},
    }]}
    real_get = pd._get_json
    pd._get_json = lambda *a, **k: ton_tx
    try:
        got_ton = pd._incoming_ton(ton_friendly_address("0:" + "11" * 32), "")
    finally:
        pd._get_json = real_get
    check(got_ton, "TON: входящий перевод не разобрался")

    # Откат: сумма положительна, но монеты вернулись отправителю. Принять такую
    # за выплату — закрыть заявку, по которой клиент ничего не получил.
    ton_aborted = {"ok": True, "result": [dict(ton_tx["result"][0],
                                               description={"aborted": True})]}
    pd._get_json = lambda *a, **k: ton_aborted
    try:
        got_ab = pd._incoming_ton(ton_friendly_address("0:" + "11" * 32), "")
    finally:
        pd._get_json = real_get
    check(got_ab == [], "TON: откатившаяся транзакция принята за выплату")
    # Проверяем ПУТЬ целиком, а не половину: отправитель из обозревателя против
    # доверенного множества, собранного из настройки владельца. По отдельности
    # обе стороны выглядят исправными — расходятся они только вместе.
    os.environ["TON_PAYOUT_ADDRESS"] = FRIENDLY_OWN
    pd._OWN_CACHE.pop("TON", None)
    trusted_ton = pd.trusted_senders("TON")
    pd._OWN_CACHE.pop("TON", None)
    check(trusted_ton, "TON: доверенные отправители пусты при заданном TON_PAYOUT_ADDRESS")
    if got_ton:
        check(set(got_ton[0]["senders"]) & trusted_ton,
              "TON: отправитель из обозревателя не пересёкся со своим же кошельком — "
              "своя выплата считается чужой, и заявка не закроется никогда")

    if FAILS:
        print(f"❌ Провалов: {len(FAILS)}\n")
        for m in FAILS:
            print("  •", m)
        return 1
    print("✅ Сверка видит XRP и ETH: доставленное отличается от заявленного, "
          "провалившееся и чужое отсеиваются, сбой сети не роняет проход.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
