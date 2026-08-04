#!/usr/bin/env python3
"""Порог окончательности: одна сеть — одно число, молчание = отказ.

Проверяется то, на что опирается приём крипты как оплаты (этап 4) и уже
опирается сверка выплат: перевод считается состоявшимся не когда он «в блоке»,
а когда сеть его больше не отменит.

Запуск: /root/bot/venv/bin/python3 tests/test_chain_confirm.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import chain_confirm as cc

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


def tx(**kw):
    base = {"txid": "a" * 64, "amount": 1.0, "confirmed": True}
    base.update(kw)
    return base


# ── имя сети ──────────────────────────────────────────────────────────
check("TRC20 и TRON — одна сеть",
      cc.normalize_network("USDT", "TRC20") == cc.normalize_network("USDT", "TRON") == "TRON")
check("ERC20 — это сеть Ethereum",
      cc.normalize_network("USDT", "ERC20") == "ETH")
check("сеть из заявки важнее канонической для монеты",
      cc.normalize_network("USDT", "ERC20") != cc.normalize_network("USDT", None))
check("USDT без сети — каноническая TRON",
      cc.normalize_network("USDT", None) == "TRON")
check("незнакомая монета без сети — пусто",
      cc.normalize_network("DOGE", None) == "")
check("названная, но незнакомая сеть НЕ подменяется канонической",
      cc.normalize_network("USDT", "BEP20") == "")
check("порог по незнакомой сети не выдаётся от чужой цепи",
      cc.required_confirmations("USDT", "BEP20") is None)
check("«mainnet» — не название сети, а уточнение: остаётся каноническая",
      cc.normalize_network("BTC", "mainnet") == "BTC")

# ── пороги ────────────────────────────────────────────────────────────
check("у BTC порог больше одного", cc.required_confirmations("BTC") >= 2)
check("у LTC порог не ниже, чем у BTC",
      cc.required_confirmations("LTC") >= cc.required_confirmations("BTC"))
check("у TRON порог покрывает круг подписей (19)",
      cc.required_confirmations("USDT", "TRON") >= 19)
check("у Ethereum порог биржевой (12)",
      cc.required_confirmations("USDT", "ERC20") >= 12)
check("у XRP и TON финализация сразу",
      cc.required_confirmations("XRP") == 1 and cc.required_confirmations("TON") == 1)
check("неизвестная сеть → None, а не ноль",
      cc.required_confirmations("DOGE") is None)

# ── переменная окружения ──────────────────────────────────────────────
os.environ["CONFIRMATIONS_BTC"] = "4"
check("порог переопределяется окружением", cc.required_confirmations("BTC") == 4)
os.environ["CONFIRMATIONS_BTC"] = "мусор"
check("нечисловая настройка не ломает правило по умолчанию",
      cc.required_confirmations("BTC") == cc._DEFAULTS["BTC"])
os.environ["CONFIRMATIONS_BTC"] = "0"
try:
    cc.required_confirmations("BTC")
    check("попытка выключить порог нулём не проходит молча", False)
except ValueError:
    check("попытка выключить порог нулём не проходит молча", True)
del os.environ["CONFIRMATIONS_BTC"]

# ── счётчик подтверждений ─────────────────────────────────────────────
check("нет поля → -1 («источник не сообщил»), а не 0",
      cc.confirmations_of(tx()) == -1)
check("ноль подтверждений — известный факт, а не молчание",
      cc.confirmations_of(tx(confirmations=0)) == 0)
check("строка с числом читается", cc.confirmations_of(tx(confirmations="7")) == 7)
check("мусор читается как молчание",
      cc.confirmations_of(tx(confirmations="скоро")) == -1)
check("не словарь → молчание", cc.confirmations_of(None) == -1)

# ── решение ───────────────────────────────────────────────────────────
check("BTC: одно подтверждение — рано",
      cc.is_final(tx(confirmations=1), "BTC") is False)
check("BTC: два подтверждения — окончательно",
      cc.is_final(tx(confirmations=2), "BTC") is True)
check("BTC: флаг «в блоке» без счётчика — отказ",
      cc.is_final(tx(), "BTC") is False)
check("XRP: флага «в блоке» достаточно", cc.is_final(tx(), "XRP") is True)
check("TON: флага «в блоке» достаточно", cc.is_final(tx(), "TON") is True)
check("явное «не в блоке» перевешивает счётчик",
      cc.is_final(tx(confirmed=False, confirmations=99), "BTC") is False)
check("отсутствие ключа confirmed отказом не считается",
      cc.is_final({"confirmations": 30, "txid": "x"}, "USDT", "TRON") is True)
check("незнакомая сеть → отказ при любом счётчике",
      cc.is_final(tx(confirmations=999), "DOGE") is False)
check("не словарь → отказ", cc.is_final("что-то", "BTC") is False)

# ── объяснение ────────────────────────────────────────────────────────
note = cc.finality_note(tx(confirmations=1), "BTC")
check("объяснение называет и текущее число, и нужное",
      "1" in note and str(cc.required_confirmations("BTC")) in note)
check("молчание источника объясняется отдельно",
      "не сообщил" in cc.finality_note(tx(), "BTC"))
check("нераспознанная сеть объясняется отдельно",
      "не распознана" in cc.finality_note(tx(), "DOGE"))

# ── «цепь сказала: откатить нельзя» ───────────────────────────────────
# У TRON числа подтверждений в ответе нет, а считать его по возрасту блока
# нельзя: прошедшее время не доказывает, что блоки выпускались. Поэтому
# необратимость приходит утверждением ОТ ИСТОЧНИКА, и оно сильнее счётчика.
check("флаг необратимости от цепи перевешивает отсутствие счётчика",
      cc.is_final({"txid": "x", "confirmed": True, "irreversible": True},
                  "USDT", "TRON") is True)
check("необратимость не воскрешает перевод, объявленный не-в-блоке",
      cc.is_final({"txid": "x", "confirmed": False, "irreversible": True},
                  "USDT", "TRON") is False)
check("необратимость объясняется человеку словами",
      "несократим" in cc.finality_note({"txid": "x", "irreversible": True},
                                       "USDT", "TRON"))
check("значение не-True флагом не считается (строка «false» — не истина)",
      cc.is_final({"txid": "x", "confirmed": True, "irreversible": "false"},
                  "USDT", "TRON") is False)

# ── читатель TRON просит у цепи только несократимые блоки ─────────────
sys.path.insert(0, os.path.join(ROOT, "relay", "core"))
from core import payout_discovery as pd

asked = {}
real_get = pd._get_json
pd._get_json = lambda url, params=None, **k: (asked.update(params or {}) or
                                              {"data": []})
try:
    pd._incoming_trc20("TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")
finally:
    pd._get_json = real_get
check("TRON запрашивается с only_confirmed — иначе судить об откате нечем",
      str(asked.get("only_confirmed", "")).lower() == "true")
check("часы больше не участвуют в решении по TRON",
      not hasattr(pd, "_tron_confirmations"))

print()
if failures:
    print(f"❌ Провалено проверок: {len(failures)}")
    for f in failures:
        print("  •", f)
    sys.exit(1)
print("✅ Порог окончательности: один источник, молчание читается как отказ.")
