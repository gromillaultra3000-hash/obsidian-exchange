#!/usr/bin/env python3
"""Тесты витрины направлений (services.offerings) и тарифов (core.pricing).

Два денежных инварианта:
  1. Монета попадает на витрину ТОЛЬКО если её есть чем выдать. Иначе клиент
     оплатит заявку, которую нечем закрыть — худший исход из возможных.
  2. Лестница комиссий одна на всех (бот, сайт, Mini App). Раньше их было три
     разных, и витрина обещала не то, что списывалось (USDT «2%» после отмены
     фикс-тарифа 25.07, чужие границы тиров в виджете).

Запуск: python3 tests/test_offerings_pricing.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import pricing as P            # noqa: E402
from services import offerings as O      # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# ── тарифная лестница ────────────────────────────────────────────────────────
check("до 5 000 → 27%", P.commission_percent(4999) == 27)
check("5 000 → 25% (тир существует)", P.commission_percent(5000) == 25)
check("9 999 → 25%", P.commission_percent(9999) == 25)
check("10 000 → 23%", P.commission_percent(10000) == 23)
check("19 999 → 23%", P.commission_percent(19999) == 23)
check("20 000 → 19%", P.commission_percent(20000) == 19)
check("500 000 → 19%", P.commission_percent(500000) == 19)
check("мусорный вход не роняет (None → 27%)", P.commission_percent(None) == 27)
check("строка не роняет", P.commission_percent("abc") == 27)
# USDT не имеет отдельной ставки — тариф общий (фикс-2% отменены 25.07.2026)
check("лестница не зависит от монеты (4 тира)", len(P.tiers_for_display()) == 4)

# Подпись ступени обязана означать ровно то, что делает расчёт. Границы
# ПОЛУОТКРЫТЫЕ (amount < limit): подпись «до 5 000 ₽» читалась как «включая
# 5 000», а на 5 000 списывалась уже следующая ступень — витрина расходилась
# с расчётом ровно на границе, в пользу клиента, поэтому жалоб не было.
_mismatch = []
for _t in P.tiers_for_display():
    _lo, _hi = _t["from_rub"], _t["to_rub"]
    _probes = [_lo, _lo + 1] + ([_hi - 1, _hi - 0.01] if _hi else [_lo + 10 ** 6])
    for _p in _probes:
        if P.commission_percent(_p) != _t["percent"]:
            _mismatch.append((_p, _t["label"], _t["percent"], P.commission_percent(_p)))
check("подпись ступени совпадает с расчётом на границах", not _mismatch)
check("верхняя граница ступени принадлежит СЛЕДУЮЩЕЙ ступени",
      P.commission_percent(5000) == 25 and P.commission_percent(4999) == 27
      and P.commission_percent(10000) == 23 and P.commission_percent(20000) == 19)
check("витринные метки заполнены",
      all(t["label"] and t["percent"] for t in P.tiers_for_display()))

# Совпадение с фактическим расчётом на сервере: exchange_calc обязан
# использовать ту же лестницу, иначе витрина снова разъедется со списанием.
from utils import exchange_calc as EC    # noqa: E402
check("exchange_calc делегирует в core.pricing",
      all(EC.get_commission_percent(a) == P.commission_percent(a)
          for a in (1000, 4999, 5000, 9999, 10000, 19999, 20000, 100000)))

# ── витрина: ликвидность решает ──────────────────────────────────────────────
_real_reserves = O._reserves


def with_state(reserves, flag):
    O._reserves = lambda: reserves
    if flag:
        os.environ["MULTICHAIN_UI_ENABLED"] = "1"
    else:
        os.environ.pop("MULTICHAIN_UI_ENABLED", None)
    return O.get_offerings(force=True)


base = {"BTC": 0.09, "LTC": 98.0, "USDT": 5318.0}

d = with_state(base, False)
check("флаг выкл → только базовые направления", d["currencies"] == ("BTC", "LTC", "USDT"))
check("флаг выкл → ETH закрыт", d["eth_enabled"] is False)
check("флаг выкл → у USDT только TRC20", d["networks"]["USDT"] == ["TRC20"])

d = with_state(base, True)
check("флаг вкл, но резерва ETH нет → ETH всё равно закрыт", d["eth_enabled"] is False)
check("причина закрытия объясняет, что делать", "setreserve" in d["reason_eth_off"])
check("без своего резерва ERC-20 у USDT не появляется", d["networks"]["USDT"] == ["TRC20"])

d = with_state(dict(base, ETH=2.5), True)
check("флаг вкл + резерв ETH → ETH открыт", d["eth_enabled"] is True)
check("ETH идёт в сети ERC20", d["networks"]["ETH"] == ["ERC20"])
# Резерв ETH НЕ доказывает наличие USDT в Ethereum — направления независимы
check("резерв ETH сам по себе НЕ открывает USDT-ERC20",
      d["networks"]["USDT"] == ["TRC20"])

d = with_state(dict(base, USDT_ERC20=4000), True)
check("свой резерв открывает USDT-ERC20", d["networks"]["USDT"] == ["TRC20", "ERC20"])
check("резерв USDT_ERC20 не открывает ETH", d["eth_enabled"] is False)

d = with_state(dict(base, ETH=0), True)
check("резерв ETH = 0 закрывает направление", d["eth_enabled"] is False)
check("резерв USDT_ERC20 = 0 закрывает сеть",
      with_state(dict(base, USDT_ERC20=0), True)["networks"]["USDT"] == ["TRC20"])

# ── is_offered: fail-closed по паре (валюта, сеть) ──────────────────────────
with_state(base, False)
check("BTC/MAINNET принимается", O.is_offered("BTC", "MAINNET", force=True))
check("BTC без сети принимается (дефолт)", O.is_offered("BTC", None, force=True))
check("USDT/TRC20 принимается", O.is_offered("USDT", "TRC20", force=True))
check("USDT/ERC20 отклоняется, пока направление закрыто",
      not O.is_offered("USDT", "ERC20", force=True))
check("ETH отклоняется, пока направление закрыто", not O.is_offered("ETH", None, force=True))
check("несуществующая монета отклоняется", not O.is_offered("DOGE", None, force=True))
check("чужая сеть для BTC отклоняется", not O.is_offered("BTC", "ERC20", force=True))

with_state(dict(base, ETH=1.0, USDT_ERC20=100), True)
check("при открытом ETH принимается ETH/ERC20", O.is_offered("ETH", "ERC20", force=True))
check("при открытом ETH принимается USDT/ERC20", O.is_offered("USDT", "ERC20", force=True))
check("USDT/TRC20 продолжает работать", O.is_offered("USDT", "TRC20", force=True))

# Сбой внутри витрины не должен ни ронять вызывающего, ни ОТКРЫВАТЬ направление
os.environ["MULTICHAIN_UI_ENABLED"] = "1"
O._reserves = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
try:
    d = O.get_offerings(force=True)
    ok = True
except Exception:
    d, ok = None, False
check("сбой витрины не роняет вызывающего", ok)
check("сбой витрины → только базовые направления (fail-closed)",
      ok and d["currencies"] == ("BTC", "LTC", "USDT") and d["eth_enabled"] is False)
check("сбой витрины → is_offered(ETH) отклоняет", not O.is_offered("ETH", None, force=True))

O._reserves = _real_reserves
os.environ.pop("MULTICHAIN_UI_ENABLED", None)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
