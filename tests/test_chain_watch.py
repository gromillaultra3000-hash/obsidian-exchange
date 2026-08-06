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

# ── TRON: остаток и операции USDT-TRC20 ──────────────────────────────────────
# Отличие от BTC/LTC не в форме ответа, а в том, что на ОДНОМ счёте лежат разные
# активы. Ошибка здесь показывает клиенту чужие деньги под именем его USDT.
print("\n── TRON ──")
TADDR = "TN3W4H6rK2ce4vX9YnFQHwKENnHjoxb3m9"
TFROM = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6a"
USDT = cw.USDT_TRC20_CONTRACT
FAKE = "TFakeTokenContractAddressXXXXXXXXXX"

with_net(Net(reply={"data": [{"trc20": [{FAKE: "999000000"}, {USDT: "28078000"}]}]}))
st = cw.tron_account_state(TADDR)
check("остаток USDT считается по знакам контракта", st["balance"] == 28.078)
check("актив назван явно — это USDT, а не «TRON»", st.get("asset") == "USDT")
check("статус OK", st["status"] == "OK" and st["reason"] is None)

with_net(Net(reply={"data": [{"trc20": [{FAKE: "999000000"}]}]}))
st = cw.tron_account_state(TADDR)
check("подставной токен с чужим контрактом не считается за USDT", st["balance"] == 0.0)

# Пустой data у TronGrid = счёт не активирован. Это честный ноль: адрес есть,
# переводов не было. Выдавать его за сбой значило бы прятать правду.
with_net(Net(reply={"data": []}))
st = cw.tron_account_state(TADDR)
check("неактивированный счёт → честный ноль", st["balance"] == 0.0 and st["status"] == "OK")

with_net(Net(reply={"data": {"не": "список"}}))
st = cw.tron_account_state(TADDR)
check("незнакомый ответ TRON не выдаётся за пустой кошелёк",
      st["balance"] is None and st["status"] == "ERROR")

with_net(Net(boom=RuntimeError("429")))
st = cw.tron_account_state(TADDR)
check("сбой обозревателя TRON → «неизвестно», а не ноль",
      st["balance"] is None and st["status"] == "ERROR" and st.get("asset") == "USDT")

with_net(Net(reply={"data": [{"trc20": [{USDT: "не число"}]}]}))
st = cw.tron_account_state(TADDR)
check("нечисловой остаток → ERROR, а не ноль",
      st["balance"] is None and st["status"] == "ERROR")

TRC20_TXS = {"data": [
    {"transaction_id": "t1", "from": TFROM, "to": TADDR, "value": "3500000",
     "block_timestamp": 1700000000000, "token_info": {"address": USDT}},
    {"transaction_id": "t2", "from": TADDR, "to": TFROM, "value": "1200000",
     "block_timestamp": 1700000100000, "token_info": {"address": USDT}},
    # Тот же счёт, но чужой токен: к USDT клиента отношения не имеет.
    {"transaction_id": "t3", "from": TFROM, "to": TADDR, "value": "9000000000",
     "block_timestamp": 1700000200000, "token_info": {"address": FAKE}},
]}
with_net(Net(reply=TRC20_TXS))
h = cw.tron_history(TADDR, 10)
check("история TRON прочитана", h["status"] == "OK")
check("переводы чужого токена в историю не попадают", len(h["items"]) == 2)
check("приход USDT посчитан в знаках USDT",
      h["items"][0]["direction"] == "in" and h["items"][0]["amount"] == 3.5)
check("у прихода контрагент — отправитель", h["items"][0]["counterparty"] == TFROM)
check("расход помечен как расход",
      h["items"][1]["direction"] == "out" and h["items"][1]["amount"] == 1.2)
check("время переведено из миллисекунд в секунды", h["items"][0]["ts"] == 1700000000)
check("операция названа своим активом", h["items"][0].get("asset") == "USDT")

with_net(Net(boom=TimeoutError("долго")))
h = cw.tron_history(TADDR)
check("сбой истории TRON → ERROR, а не «операций нет»",
      h["status"] == "ERROR" and h["items"] == [])

with_net(Net(reply={"data": "не список"}))
check("незнакомый ответ истории TRON не выдаётся за пустую историю",
      cw.tron_history(TADDR)["status"] == "ERROR")

with_net(Net(reply={"data": []}))
h = cw.tron_history(TADDR)
check("нет переводов → пустая история со статусом OK",
      h["status"] == "OK" and h["items"] == [])

# ── связка с реестром кошельков ──────────────────────────────────────────────
print("\n── реестр источников ──")
from core import wallet_link as wl                                  # noqa: E402
check("BTC, LTC и TRON зарегистрированы как источники баланса",
      {"BTC", "LTC", "TRON"} <= set(wl.BALANCE_SOURCES))
check("BTC, LTC и TRON зарегистрированы как источники истории",
      {"BTC", "LTC", "TRON"} <= set(wl.HISTORY_SOURCES))
for coin in ("BTC", "LTC", "TRON"):
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

# Имя актива тоже теряется молча — и тогда 28 USDT подписываются словом «TRON».
state = wl._account_state("TRON", TADDR, source=lambda a: {
    "balance": 28.078, "status": "OK", "asset": "USDT"})
check("реестр проносит имя актива наружу", state.get("asset") == "USDT")
state = wl._account_state("BTC", ADDR, source=lambda a: {"balance": 1.0, "status": "OK"})
check("без имени актива подписью остаётся сама цепь", state.get("asset") == "BTC")

cw._get_json = _real_get
print()
if failures:
    print(f"❌ {len(failures)} провал(ов):")
    for f in failures:
        print("   ·", f)
    sys.exit(1)
print("Все проверки пройдены.")
