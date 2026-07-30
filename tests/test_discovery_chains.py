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
         "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "12500000"}},
        # ЧАСТИЧНЫЙ платёж: заявлено много, дошло мало — считать надо дошедшее
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "BBB",
                "Account": "rOurWallet", "Amount": "99000000", "date": 780000100},
         "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "1000000"}},
        # неуспешная — денег не было
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "CCC",
                "Account": "rOurWallet", "Amount": "50000000", "date": 780000200},
         "meta": {"TransactionResult": "tecUNFUNDED_PAYMENT", "delivered_amount": "50000000"}},
        # чужому адресу
        {"tx": {"TransactionType": "Payment", "Destination": "rSomeoneElse", "hash": "DDD",
                "Account": "rOurWallet", "Amount": "7000000", "date": 780000300},
         "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "7000000"}},
        # не платёж
        {"tx": {"TransactionType": "TrustSet", "Destination": ADDR, "hash": "EEE",
                "Account": "rOurWallet", "date": 780000400},
         "meta": {"TransactionResult": "tesSUCCESS"}},
        # платёж токеном (Amount — объект, не дропы)
        {"tx": {"TransactionType": "Payment", "Destination": ADDR, "hash": "FFF",
                "Account": "rIssuer", "date": 780000500,
                "Amount": {"currency": "USD", "value": "10", "issuer": "rI"}},
         "meta": {"TransactionResult": "tesSUCCESS",
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
    for name in ("_incoming_btc_like", "_incoming_trc20", "_incoming_xrpl", "_incoming_evm"):
        setattr(pd, name, (lambda n: (lambda *a, **k: seen.setdefault(n, a) or []))(name))
    try:
        for cur, want in (("BTC", "_incoming_btc_like"), ("LTC", "_incoming_btc_like"),
                          ("USDT", "_incoming_trc20"), ("XRP", "_incoming_xrpl"),
                          ("ETH", "_incoming_evm"), ("xrp", "_incoming_xrpl")):
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
