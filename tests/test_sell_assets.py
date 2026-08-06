#!/usr/bin/env python3
"""Реестр направления продажи (core/sell_assets).

Проверяем не «какие монеты сегодня открыты» — это меняется настройкой, — а
правила, по которым монета открывается. Каждое из них закрывает свой способ
потерять деньги клиента: перевод на адрес чужой сети не вернуть, перевод без
метки не привязать к заявке, приём пыли обходится дороже выручки.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import assets                                             # noqa: E402
from core import sell_assets as sa                                  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


BTC = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
LTC = "LLctoqD99G5TM6wnHXJrMmsNeUjqrUb2JP"
XMR = ("4AdUndXHHZ6cfufTMvppY6JwXNouMBzSkbLYfpAV5Usx3skxNgYeYTRj5Uzqt"
       "ReoS44qo9mtmXCqY45DJ852K5Jv2684Rge")
ETH = "0x000000000000000000000000000000000000dEaD"
XRP = "rN7n7otQDd6FczFgLdSqtcsAUxDkw6fzRH"
TON = "UQDNdldtBrXxsFDgXSyJjbV-SsAg6yfG5tViIyXMV43gaqM8"

_KEYS = [f"SELL_{c}_ADDRESS" for c in assets.CURRENCY_NETWORKS]
_saved = {k: os.environ.get(k) for k in _KEYS}
for k in _KEYS:
    os.environ.pop(k, None)


def restore():
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ── адрес приёма ─────────────────────────────────────────────────────────────
print("\n── адрес приёма ──")
check("без адреса монета не продаётся", sa.sell_currencies() == ())
check("причина названа словами", "SELL_BTC_ADDRESS" in sa.closed_reason("BTC"))

os.environ["SELL_BTC_ADDRESS"] = BTC
check("адрес задан — монета в продаже", "BTC" in sa.sell_currencies())
check("адрес отдаётся тем же, что задан", sa.receive_address("BTC") == BTC)
check("у открытой монеты причины закрытия нет", sa.closed_reason("BTC") == "")

# Главное правило модуля: неверный адрес — не «недоступно временно». Перевод
# клиента на адрес чужой сети не возвращается никем.
os.environ["SELL_LTC_ADDRESS"] = BTC
check("адрес чужой сети закрывает направление", "LTC" not in sa.sell_currencies())
check("причина указывает на настройку, а не на «сбой»",
      "не проходит проверку" in sa.closed_reason("LTC"))
os.environ["SELL_LTC_ADDRESS"] = LTC
check("верный адрес открывает ту же монету", "LTC" in sa.sell_currencies())

os.environ["SELL_BTC_ADDRESS"] = "  " + BTC + "  "
check("пробелы вокруг адреса не мешают", sa.receive_address("BTC") == BTC)
os.environ["SELL_BTC_ADDRESS"] = "не адрес вовсе"
check("мусор в настройке закрывает монету", "BTC" not in sa.sell_currencies())
os.environ["SELL_BTC_ADDRESS"] = BTC

# ── новые монеты включаются настройкой, а не правкой кода ────────────────────
print("\n── новые монеты ──")
os.environ["SELL_XMR_ADDRESS"] = XMR
os.environ["SELL_ETH_ADDRESS"] = ETH
open_now = sa.sell_currencies()
check("Monero открывается своим адресом", "XMR" in open_now)
check("ETH открывается своим адресом", "ETH" in open_now)
check("порядок — как в реестре монет",
      list(open_now) == [c for c in assets.CURRENCY_NETWORKS if c in open_now])

# ── метка перевода ───────────────────────────────────────────────────────────
print("\n── метка перевода ──")
os.environ["SELL_XRP_ADDRESS"] = XRP
check("XRP закрыт: метку выдавать нечем", "XRP" not in sa.sell_currencies())
check("причина объясняет, чего именно не хватает",
      "destination tag" in sa.closed_reason("XRP"))
os.environ["SELL_TON_ADDRESS"] = TON
check("TON открыт: метку выдавать умеем", "TON" in sa.sell_currencies())
check("TON помечен как монета с меткой", sa.needs_marker("TON") and sa.can_mark("TON"))
check("у BTC метки нет и выдумывать её не надо", not sa.needs_marker("BTC"))

# ── минимум ──────────────────────────────────────────────────────────────────
print("\n── минимум ──")
check("у каждой открытой монеты объявлен минимум",
      all(sa.minimum(c) is not None for c in sa.sell_currencies()))
_m = sa.MINIMUMS.pop("XMR")
check("монета без минимума не предлагается", "XMR" not in sa.sell_currencies())
check("причина про минимум, а не про что-то ещё",
      "минимум" in sa.closed_reason("XMR"))
sa.MINIMUMS["XMR"] = _m
check("минимум вернулся — монета снова в продаже", "XMR" in sa.sell_currencies())

# ── кто подтверждает зачисление ──────────────────────────────────────────────
print("\n── подтверждение зачисления ──")
check("депозит BTC страж находит сам", sa.deposit_check_available("BTC"))
# У USDT сетей две, а страж читает только TRON. Обещание автоматики привязано
# к СЕТИ адреса приёма: на `0x…` адресе страж искал бы депозит Ethereum в TRON
# и не нашёл бы его никогда, а клиенту были бы обещаны 30–60 минут.
os.environ["SELL_USDT_ADDRESS"] = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
check("депозит USDT-TRC20 страж находит сам", sa.deposit_check_available("USDT"))
check("подпись USDT называет сеть адреса", "TRC" in sa.label("USDT"))
os.environ["SELL_USDT_ADDRESS"] = "0x000000000000000000000000000000000000dEaD"
check("тот же USDT на ERC-20 адресе — только вручную",
      sa.needs_manual_check("USDT") and "ERC" in sa.label("USDT"))
check("ERC-20 адрес приёма не отвергнут «по сети по умолчанию»",
      sa.receive_address("USDT") != "")
os.environ.pop("SELL_USDT_ADDRESS", None)
# Monero скрывает суммы и получателя устройством сети — обозревателя, который
# покажет наш приход, не существует. Клиенту говорим об этом заранее.
check("зачисление Monero подтверждает человек", sa.needs_manual_check("XMR"))
check("зачисление ETH подтверждает человек", sa.needs_manual_check("ETH"))
check("у монеты с авто-проверкой этой строки нет", not sa.needs_manual_check("LTC"))

# ── подписи ──────────────────────────────────────────────────────────────────
print("\n── подписи ──")
for cur in sa.sell_currencies():
    check(f"подпись {cur} содержит код монеты", cur in sa.label(cur))
check("неизвестная монета не роняет подпись", sa.label("ZZZ") == "• ZZZ")
check("неизвестная монета не попадает в продажу", "ZZZ" not in sa.sell_currencies())
check("причина у неизвестной монеты честная",
      "не поддержана" in sa.closed_reason("ZZZ"))

restore()
print()
if failures:
    print(f"❌ {len(failures)} провал(ов):")
    for f in failures:
        print("   ·", f)
    sys.exit(1)
print("Все проверки пройдены.")
