#!/usr/bin/env python3
"""Тесты фиксации котировки (core.quote): что обещали — то и платим.

Три денежных инварианта:
  1. Курс для клиента = market/(1-c/100), а НЕ market*(1-c/100). Вторая форма
     давала объём БОЛЬШЕ рыночного (129.9% рынка при 23% комиссии вместо 77%) —
     так считались DCA, подарки и лимитные заявки.
  2. Выплата идёт по объёму, зафиксированному при создании заявки, а не по
     свежему курсу: обещание «курс действует 15 минут» должно выполняться, а
     скидки VIP/промо — доживать до выплаты.
  3. Протухшая котировка (рынок ушёл далеко вверх) НЕ уходит в авто-выплату —
     это разбор человеком, а не молчаливая переплата.

Запуск: python3 tests/test_quote.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import quote as Q  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


def approx(a, b, eps=1e-9):
    return abs(a - b) < eps


# ── effective_rate: направление формулы ──────────────────────────────────────
MARKET = 5_000_000.0
r23 = Q.effective_rate(MARKET, 23)
check("курс с наценкой ВЫШЕ рыночного", r23 > MARKET)
check("23% → market/0.77", approx(r23, MARKET / 0.77))
coins = Q.crypto_for(10_000, r23)
market_coins = 10_000 / MARKET
check("клиент получает 77% рыночного объёма (комиссия удержана)",
      approx(round(coins / market_coins, 6), 0.77))
# Именно та ошибка, что жила в DCA/подарках/лимитках
wrong = 10_000 / (MARKET * 0.77)
check("перевёрнутая формула дала бы БОЛЬШЕ рынка (регрессия, которую чиним)",
      wrong > market_coins and coins < market_coins)
check("нулевой рынок → 0 (без деления на ноль)", Q.effective_rate(0, 23) == 0.0)
check("комиссия 100% → 0 (без деления на ноль)", Q.effective_rate(MARKET, 100) == 0.0)
check("мусорный вход не роняет", Q.effective_rate(None, None) == 0.0)

# ── crypto_for ───────────────────────────────────────────────────────────────
check("объём = рубли / курс", approx(Q.crypto_for(10_000, 5_000_000), 0.002))
check("нулевой курс → 0", Q.crypto_for(10_000, 0) == 0.0)
check("отрицательная сумма → 0", Q.crypto_for(-5, 100) == 0.0)
check("строки не роняют", Q.crypto_for("abc", "xyz") == 0.0)

# ── settle_amount: что реально платим ───────────────────────────────────────
os.environ.pop("PAYOUT_QUOTE_MAX_EXCESS_PCT", None)

v = Q.settle_amount(None, 0.002)
check("старая заявка без договорённости → платим рыночный объём", v["amount"] == 0.002)
check("старая заявка → авто-выплата разрешена", v["auto_ok"] is True)
check("источник помечен как market", v["source"] == "market")

# рынок упал → обещали меньше, чем дал бы пересчёт: платим ОБЕЩАННОЕ
v = Q.settle_amount(0.0015, 0.0020)
check("обещано меньше рынка → платим обещанное", v["amount"] == 0.0015)
check("обещано меньше рынка → авто-выплата разрешена", v["auto_ok"] is True)

# рынок вырос немного → обещали больше, но в пределах порога: платим обещанное
v = Q.settle_amount(0.00210, 0.00200)
check("обещано на 5% больше рынка → платим обещанное (в пределах порога)",
      v["amount"] == 0.00210 and v["auto_ok"] is True)

# рынок вырос сильно → котировка протухла: авто-выплата запрещена
v = Q.settle_amount(0.0030, 0.0020)
check("обещано на 50% больше рынка → авто-выплата ЗАПРЕЩЕНА", v["auto_ok"] is False)
check("причина отказа объяснена", "протухла" in v["reason"])
check("превышение посчитано", v.get("excess_pct") == 50.0)

# граница порога
v = Q.settle_amount(0.0023, 0.0020)   # ровно +15%
check("ровно на пороге (+15%) → ещё платим", v["auto_ok"] is True)
v = Q.settle_amount(0.00231, 0.0020)  # чуть выше порога
check("чуть выше порога → уже не платим", v["auto_ok"] is False)

# порог настраивается
os.environ["PAYOUT_QUOTE_MAX_EXCESS_PCT"] = "50"
v = Q.settle_amount(0.0028, 0.0020)   # +40%
check("порог из env расширяет допуск", v["auto_ok"] is True)
os.environ["PAYOUT_QUOTE_MAX_EXCESS_PCT"] = "не число"
check("битый env → дефолтный порог", Q.max_excess_pct() == Q.DEFAULT_MAX_EXCESS_PCT)
os.environ.pop("PAYOUT_QUOTE_MAX_EXCESS_PCT", None)

# нечего сравнивать → не платим вслепую
v = Q.settle_amount(0.002, 0)
check("рыночный объём не посчитан → авто-выплата запрещена", v["auto_ok"] is False)
check("рыночный объём не посчитан → сумма 0", v["amount"] == 0.0)

# ── сквозной сценарий: VIP-скидка доживает до выплаты ───────────────────────
# Клиенту с VIP-скидкой 6пп показали объём по комиссии 17% вместо 23%
vip_rate = Q.effective_rate(MARKET, 23 - 6)
vip_coins = Q.crypto_for(10_000, vip_rate)
base_coins = Q.crypto_for(10_000, Q.effective_rate(MARKET, 23))
check("VIP получает больше базового тарифа", vip_coins > base_coins)
v = Q.settle_amount(vip_coins, base_coins)   # выплата пересчитала бы по базе
check("выплата отдаёт VIP-объём, а не базовый", approx(v["amount"], vip_coins))
check("VIP-надбавка не считается протухшей котировкой", v["auto_ok"] is True)

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
