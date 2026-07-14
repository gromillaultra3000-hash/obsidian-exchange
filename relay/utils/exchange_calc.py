"""Расчёт курса/комиссии и валидация криптоадресов для веб-форм ObsidianExchange.

Логика идентична main_bot.py (get_cached_rate, get_rate_with_markup,
get_commission_percent, validate_crypto_address) — скопирована в общий
модуль, чтобы бот оставался без изменений.
"""
import os
import re
import time
import requests

SWAP_COINS = ["BTC", "LTC", "USDT"]
SWAP_NETWORKS = {"BTC": "Mainnet", "LTC": "Mainnet", "USDT": "TRC20"}

_rate_cache = {
    "BTC": {"rate": 0, "ts": 0},
    "LTC": {"rate": 0, "ts": 0},
    "USDT": {"rate": 0, "ts": 0},
}

_COINGECKO_IDS = {"BTC": "bitcoin", "LTC": "litecoin", "USDT": "tether"}
_FALLBACK_RATES = {"BTC": 6500000, "LTC": 4000, "USDT": 85}


def get_commission_percent(amount_rub):
    if amount_rub <= 4999:
        return 27
    elif amount_rub <= 14999:
        return 23
    else:
        return 19


def get_cached_rate(coin):
    cache = _rate_cache[coin]
    now = time.time()
    if cache["rate"] and (now - cache["ts"]) < 600:
        return cache["rate"]
    try:
        cg_id = _COINGECKO_IDS[coin]
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=rub", timeout=8)
        rate = r.json()[cg_id]["rub"]
    except Exception:
        try:
            if coin == "BTC":
                r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=8)
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB", timeout=8)
                rate = float(r1.json()["price"]) * float(r2.json()["price"])
            elif coin == "LTC":
                r1 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=LTCUSDT", timeout=8)
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB", timeout=8)
                rate = float(r1.json()["price"]) * float(r2.json()["price"])
            else:
                r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB", timeout=8)
                rate = float(r.json()["price"])
        except Exception:
            return cache["rate"] or _FALLBACK_RATES[coin]
    cache["rate"] = rate
    cache["ts"] = now
    return rate


def get_rate_with_markup(coin, amount=None):
    if amount is None:
        commission = 23
    elif coin == "USDT":
        commission = float(os.getenv("USDT_COMMISSION_PERCENT", 2))
    else:
        commission = get_commission_percent(amount)
    return get_cached_rate(coin) / (1 - commission / 100)


def get_sell_rate(coin):
    """Курс ПОКУПКИ крипты у клиента (продажа → RUB): рынок минус комиссия.
    Та же логика, что в боте (menu_sell): ~19% BTC/LTC, ~2% USDT."""
    if coin == "USDT":
        commission = float(os.getenv("USDT_COMMISSION_PERCENT", 2))
    else:
        commission = get_commission_percent(50000)
    return round(get_cached_rate(coin) * (1 - commission / 100), 2)


def validate_crypto_address(addr, currency):
    if currency == "BTC":
        return any(re.match(p, addr) for p in [r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', r'^bc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == "LTC":
        return any(re.match(p, addr) for p in [r'^[LM][1-9A-HJ-NP-Za-km-z]{26,33}$', r'^ltc1[ac-hj-np-z02-9]{39,59}$'])
    elif currency == "USDT":
        return re.match(r'^T[A-Za-z1-9]{33}$', addr) is not None
    return False
