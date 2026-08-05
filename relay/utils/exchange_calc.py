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

_RELAY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RELAY_ROOT not in sys.path:
    sys.path.insert(0, _RELAY_ROOT)
from core import assets as _assets  # единый источник правды по валютам/сетям/адресам
from core import pricing as _pricing  # единый источник тарифной лестницы

SWAP_COINS = ["BTC", "LTC", "USDT"]
SWAP_NETWORKS = {"BTC": "Mainnet", "LTC": "Mainnet", "USDT": "TRC20"}

_COINGECKO_IDS = {"BTC": "bitcoin", "LTC": "litecoin", "USDT": "tether",
                  "ETH": "ethereum", "XRP": "ripple",
                  # На CoinGecko TON — the-open-network, не «toncoin».
                  "TON": "the-open-network",
                  "XMR": "monero"}
_FALLBACK_RATES = {"BTC": 6500000, "LTC": 4000, "USDT": 85, "ETH": 250000,
                   "XRP": 95, "TON": 260, "XMR": 30000}
# Резервный источник — пара на Binance. Символ, оканчивающийся на RUB, УЖЕ в
# рублях; остальные умножаются на USDTRUB.
# ⚠️ Монеты здесь может не быть вовсе (XMR снят с Binance в 2024): тогда
# резервного источника просто НЕТ. Раньше отсутствие пары означало ветку
# «значит, это USDT» и монета получала цену тезера — Monero ушла бы по 91 ₽
# вместо ~30 000. Отсутствие источника — отказ, а не догадка.
_BINANCE_SYMBOL = {"BTC": "BTCUSDT", "LTC": "LTCUSDT", "ETH": "ETHUSDT",
                   "XRP": "XRPUSDT", "TON": "TONUSDT", "USDT": "USDTRUB"}

# Кеш заводится ОТ списка котируемых монет, а не отдельным литералом: раньше
# это были два независимых перечня, и монета, забытая в кеше, роняла
# get_cached_rate по KeyError на живом клиенте.
_rate_cache = {coin: {"rate": 0, "ts": 0} for coin in _COINGECKO_IDS}


def get_commission_percent(amount_rub):
    """Единый источник — core.pricing. Раньше здесь была СВОЯ лестница без тира
    25% и с границей 15 000 вместо 10/20 тыс.: сайт считал заявку не так, как бот."""
    return _pricing.commission_percent(amount_rub)


def get_cached_rate(coin):
    if coin not in _rate_cache:
        # Отсутствие источника — отказ, а не догадка: монета без своей цены
        # не должна получить чужую.
        raise ValueError(f"нет источника курса для {coin} — монету нельзя продавать")
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
            sym = _BINANCE_SYMBOL.get(coin)
            if not sym:
                raise LookupError(f"нет резервного источника цены для {coin}")
            r1 = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", timeout=8)
            price = float(r1.json()["price"])
            if sym.endswith("RUB"):
                rate = price          # пара уже в рублях (USDTRUB)
            else:
                r2 = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=USDTRUB", timeout=8)
                rate = price * float(r2.json()["price"])
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
    """Валидация СТРОКИ НАЗНАЧЕНИЯ под валюту И сеть (единый источник — core.assets).

    Понимает каноническую склейку с тегом (`UQ…#memo`) — в таком виде адрес
    хранится у валют с тегом и в таком же виде его вставляют клиенты. Голая
    проверка адреса отвергала бы правильное назначение.
    network=None → сеть по умолчанию валюты (USDT→TRC20) для обратной совместимости."""
    return _assets.validate_destination(currency, addr, network)
