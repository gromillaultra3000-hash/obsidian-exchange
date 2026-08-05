#!/usr/bin/env python3
"""Остаток и операции чужого адреса в цепи (core/chain_watch).

Сеть здесь подменена: проверяем не обозреватель, а наши выводы из его ответа.
Главные из них — «не знаем ≠ ноль» и «ожидающее ≠ подтверждённое»: оба ошибочно
округляются в спокойную неправду, которую клиент замечает последним.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import chain_watch as cw                                  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


ADDR = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
OTHER = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"


class Net:
    """Подставная сеть: отдаёт заготовку или бросает."""

    def __init__(self, reply=None, boom=None):
        self.reply, self.boom, self.calls = reply, boom, 0

    def __call__(self, url, timeout=12):
        self.calls += 1
        if self.boom:
            raise self.boom
        return self.reply


def with_net(net):
    cw._cache.clear()
    cw._get_json = net
    return net


_real_get = cw._get_json

STATS = {"chain_stats": {"funded_txo_sum": 500_000_000, "spent_txo_sum": 200_000_000},
         "mempool_stats": {"funded_txo_sum": 1_000_000, "spent_txo_sum": 0}}

# ── остаток ──────────────────────────────────────────────────────────────────
print("\n── остаток ──")
with_net(Net(reply=STATS))
st = cw.account_state("BTC", ADDR)
check("остаток = полученное минус потраченное", st["balance"] == 3.0)
check("ожидающее считается отдельно", st["pending"] == 0.01)
check("статус OK", st["status"] == "OK" and st["reason"] is None)

with_net(Net(boom=RuntimeError("сеть недоступна")))
st = cw.account_state("BTC", ADDR)
check("сбой сети → баланс НЕ ноль, а «неизвестно»", st["balance"] is None)
check("сбой сети → статус ERROR с причиной", st["status"] == "ERROR" and st["reason"])

with_net(Net(reply={"что-то": "новое"}))
st = cw.account_state("BTC", ADDR)
check("незнакомый ответ не считается пустым кошельком",
      st["balance"] is None and st["status"] == "ERROR")

with_net(Net(reply=STATS))
check("неизвестная монета → UNSUPPORTED",
      cw.account_state("DOGE", ADDR)["status"] == "UNSUPPORTED")
check("пустой адрес → UNSUPPORTED", cw.account_state("BTC", "")["status"] == "UNSUPPORTED")

with_net(Net(reply={"chain_stats": {"funded_txo_sum": 7, "spent_txo_sum": 7},
                    "mempool_stats": {"funded_txo_sum": 0, "spent_txo_sum": 300}}))
st = cw.account_state("LTC", ADDR)
check("настоящий ноль остаётся нулём (это не «неизвестно»)", st["balance"] == 0.0)
check("уходящий перевод в мемпуле показывается отрицательным",
      st["pending"] == -0.000003)

# ── кеш ──────────────────────────────────────────────────────────────────────
print("\n── кеш ──")
net = with_net(Net(reply=STATS))
cw.account_state("BTC", ADDR)
cw.account_state("BTC", ADDR)
check("успешный ответ спрашивают у сети один раз", net.calls == 1)
check("другой адрес спрашивается заново",
      (cw.account_state("BTC", OTHER), net.calls)[1] == 2)

net = with_net(Net(boom=RuntimeError("429")))
cw.account_state("BTC", ADDR)
cw.account_state("BTC", ADDR)
# Закешированный отказ пережил бы восстановление сети и держал бы клиента без
# баланса всю минуту — а сбои обозревателя длятся секунды.
check("отказ НЕ кешируется — следующая попытка идёт в сеть", net.calls == 2)

# ── операции ─────────────────────────────────────────────────────────────────
print("\n── операции ──")
TXS = [
    {"txid": "aa", "status": {"confirmed": True, "block_time": 1700000000},
     "vin": [{"prevout": {"scriptpubkey_address": OTHER, "value": 300_000_000}}],
     "vout": [{"scriptpubkey_address": ADDR, "value": 250_000_000}]},
    {"txid": "bb", "status": {"confirmed": False},
     "vin": [{"prevout": {"scriptpubkey_address": ADDR, "value": 100_000_000}}],
     "vout": [{"scriptpubkey_address": OTHER, "value": 90_000_000}]},
    # Адрес и на входе, и на выходе на ту же сумму: остаток не изменился.
    {"txid": "cc", "status": {"confirmed": True, "block_time": 1700000100},
     "vin": [{"prevout": {"scriptpubkey_address": ADDR, "value": 50_000_000}}],
     "vout": [{"scriptpubkey_address": ADDR, "value": 50_000_000}]},
]
with_net(Net(reply=TXS))
h = cw.history("BTC", ADDR, 10)
check("история прочитана", h["status"] == "OK")
check("операция, не изменившая остаток, не показывается", len(h["items"]) == 2)
inc = h["items"][0]
check("приход помечен как приход", inc["direction"] == "in" and inc["amount"] == 2.5)
check("у прихода контрагент — отправитель", inc["counterparty"] == OTHER)
out = h["items"][1]
check("расход помечен как расход", out["direction"] == "out" and out["amount"] == 1.0)
check("у расхода контрагент — получатель", out["counterparty"] == OTHER)
check("неподтверждённая операция помечена", out["confirmed"] is False)

with_net(Net(reply=TXS))
check("ограничение количества соблюдается", len(cw.history("BTC", ADDR, 1)["items"]) == 1)

with_net(Net(boom=TimeoutError("долго")))
h = cw.history("BTC", ADDR)
check("сбой истории → ERROR, а не «операций нет»",
      h["status"] == "ERROR" and h["items"] == [])

with_net(Net(reply={"не": "список"}))
check("незнакомый ответ истории не выдаётся за пустую историю",
      cw.history("BTC", ADDR)["status"] == "ERROR")

check("история неизвестной монеты → UNSUPPORTED",
      cw.history("DOGE", ADDR)["status"] == "UNSUPPORTED")

# ── связка с реестром кошельков ──────────────────────────────────────────────
print("\n── реестр источников ──")
from core import wallet_link as wl                                  # noqa: E402
check("BTC и LTC зарегистрированы как источники баланса",
      {"BTC", "LTC"} <= set(wl.BALANCE_SOURCES))
check("BTC и LTC зарегистрированы как источники истории",
      {"BTC", "LTC"} <= set(wl.HISTORY_SOURCES))
for coin in ("BTC", "LTC"):
    mod, fn = wl.BALANCE_SOURCES[coin]
    check(f"источник баланса {coin} существует и зовётся одним адресом",
          callable(getattr(__import__(mod, fromlist=[fn]), fn)))
    mod, fn = wl.HISTORY_SOURCES[coin]
    check(f"источник истории {coin} существует",
          callable(getattr(__import__(mod, fromlist=[fn]), fn)))

# Ожидающее должно ДОЕХАТЬ до поверхности: реестр собирает свой словарь, и
# поле, забытое в нём, теряется молча.
state = wl._account_state("BTC", ADDR, source=lambda a: {
    "balance": 1.25, "pending": 0.5, "status": "OK", "reason": None})
check("реестр проносит ожидающее наружу", state.get("pending") == 0.5)
state = wl._account_state("BTC", ADDR, source=lambda a: {
    "balance": None, "status": "ERROR", "reason": "сеть"})
check("при сбое ожидающее тоже «неизвестно», а не ноль", state.get("pending") is None)

cw._get_json = _real_get
print()
if failures:
    print(f"❌ {len(failures)} провал(ов):")
    for f in failures:
        print("   ·", f)
    sys.exit(1)
print("Все проверки пройдены.")
