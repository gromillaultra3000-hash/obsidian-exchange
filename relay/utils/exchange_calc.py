"""Расчёт курса/комиссии и валидация криптоадресов для веб-форм ObsidianExchange.

Логика идентична main_bot.py (get_cached_rate, get_rate_with_markup,
get_commission_percent, validate_crypto_address) — скопирована в общий
модуль, чтобы бот оставался без изменений.
"""
import os
import re
import sys
import time
import requests

if "/root/relay" not in sys.path:
    sys.path.insert(0, "/root/relay")
from core import assets as _assets  # единый источник правды по валютам/сетям/адресам

SWAP_COINS = ["BTC", "LTC", "USDT"]
SWAP_NETWORKS = {"BTC": "Mainnet", "LTC": "Mainnet", "USDT": "TRC20"}

_rate_cache = {
    "BTC": {"rate": 0, "ts": 0},
    "LTC": {"rate": 0, "ts": 0},
    "USDT": {"rate": 0, "ts": 0},
    "ETH": {"rate": 0, "ts": 0},
}

_COINGECKO_IDS = {"BTC": "bitcoin", "LTC": "litecoin", "USDT": "tether", "ETH": "ethereum"}
_FALLBACK_RATES = {"BTC": 6500000, "LTC": 4000, "USDT": 85, "ETH": 250000}
_BINANCE_USDT = {"BTC": "BTCUSDT", "LTC": "LTCUSDT", "ETH": "ETHUSDT"}


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
            sym = _BINANCE_USDT.get(coin)
            if sym:  # BTC/LTC/ETH — цена в USDT × курс USDT/RUB
                r1 = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", timeout=8)
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB", timeout=8)
                rate = float(r1.json()["price"]) * float(r2.json()["price"])
            else:  # USDT
                r = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB", timeout=8)
                rate = float(r.json()["price"])
        except Exception:
            return cache["rate"] or _FALLBACK_RATES[coin]
    cache["rate"] = rate
    cache["ts"] = now
    return rate


def get_rate_with_markup(coin, amount=None):
    # USDT по умолчанию — тарифная лестница как BTC/LTC (было фикс 2%, уводило
    # маржу). Опциональный env-оверрайд USDT_COMMISSION_PERCENT; не задан → тариф.
    _usdt_override = os.getenv("USDT_COMMISSION_PERCENT")
    if amount is None:
        commission = 23
    elif coin == "USDT" and _usdt_override:
        commission = float(_usdt_override)
    else:
        commission = get_commission_percent(amount)
    return get_cached_rate(coin) / (1 - commission / 100)


def get_sell_rate(coin):
    """Курс ПОКУПКИ крипты у клиента (продажа → RUB): рынок минус комиссия.
    ~19% BTC/LTC; USDT по умолчанию тоже по тарифу (продажа USDT сейчас скрыта,
    держим консистентно с покупкой). env USDT_COMMISSION_PERCENT — оверрайд."""
    _usdt_override = os.getenv("USDT_COMMISSION_PERCENT")
    if coin == "USDT" and _usdt_override:
        commission = float(_usdt_override)
    else:
        commission = get_commission_percent(50000)
    return round(get_cached_rate(coin) * (1 - commission / 100), 2)


def validate_crypto_address(addr, currency, network=None):
    """Валидация адреса под валюту И сеть (единый источник — core.assets).
    network=None → сеть по умолчанию валюты (USDT→TRC20) для обратной совместимости."""
    return _assets.validate_address(currency, addr, network)
