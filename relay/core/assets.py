"""Единый источник правды по валютам, сетям и валидации адресов (мультичейн).

Зачем. Логика «какие валюты обмениваем», «в каких сетях» и «валиден ли адрес»
исторически дублировалась в трёх местах (bot/main_bot.py, relay/utils/exchange_calc.py,
relay-fastapi/main.py) и расходилась. Для Фазы C (ETH + выбор сети USDT) правила
должны быть в ОДНОМ месте, иначе легко отправить не в ту сеть или принять адрес
чужой сети. Модуль чистый: без БД, без сети, без зависимостей — импортируется всеми.

Фейл-клоуз: неизвестная валюта/сеть → отказ (None/False), а не «как-нибудь».
"""
from __future__ import annotations
import os
import re

# ── Канонические коды сетей ──
NET_MAINNET = "MAINNET"   # BTC/LTC
NET_TRC20 = "TRC20"       # USDT на TRON
NET_ERC20 = "ERC20"       # ETH mainnet и USDT на Ethereum

# Валюта → допустимые сети (первая = сеть по умолчанию)
CURRENCY_NETWORKS = {
    "BTC": [NET_MAINNET],
    "LTC": [NET_MAINNET],
    "USDT": [NET_TRC20, NET_ERC20],
    "ETH": [NET_ERC20],   # для ETH «ERC20» = Ethereum mainnet (единый EVM-контур)
}

# Синонимы входных значений сети → канон (или None = недопустимо)
_NET_ALIASES = {
    "TRON": NET_TRC20, "TRC-20": NET_TRC20, "TRC20": NET_TRC20,
    "ERC-20": NET_ERC20, "ERC20": NET_ERC20,
    "ETH": NET_ERC20, "ETHEREUM": NET_ERC20, "ETHEREUM-MAINNET": NET_ERC20, "EVM": NET_ERC20,
    "MAIN": NET_MAINNET, "MAINNET": NET_MAINNET,
    "BEP20": None, "BSC": None, "POLYGON": None, "MATIC": None, "TON": None,
}

_ADDR_RE = {
    "BTC": [r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', r'^bc1[ac-hj-np-z02-9]{39,59}$'],
    "LTC": [r'^[LM][1-9A-HJ-NP-Za-km-z]{26,33}$', r'^ltc1[ac-hj-np-z02-9]{39,59}$'],
    NET_TRC20: [r'^T[A-Za-z1-9]{33}$'],
    NET_ERC20: [r'^0x[a-fA-F0-9]{40}$'],
}


def multichain_ui_enabled() -> bool:
    """Фиче-флаг мультичейн-UI (ETH как монета + выбор сети USDT в интерфейсах).
    По умолчанию ВЫКЛ: бэкенд готов, но поверхности не предлагают ETH/выбор сети,
    пока флаг не включён. Авто-выплата EVM гейтится ОТДЕЛЬНО (EVM_PAYOUTS_ENABLED)."""
    return os.getenv("MULTICHAIN_UI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def normalize_currency(currency) -> str:
    """Фейл-клоуз и на нестроковый вход (int/list/None) — .strip() на них упал бы
    исключением, что для вызывающего кода часто оборачивалось бы в try/except
    и МОЛЧА пропускало бы валидацию. Не-строка → "" → не найдена ни в одной таблице."""
    if not isinstance(currency, str):
        return ""
    return currency.strip().upper()


def is_supported_currency(currency) -> bool:
    return normalize_currency(currency) in CURRENCY_NETWORKS


def networks_for(currency):
    """Список допустимых сетей валюты (канон) или []. Первая — по умолчанию."""
    return list(CURRENCY_NETWORKS.get(normalize_currency(currency), []))


def default_network(currency):
    nets = networks_for(currency)
    return nets[0] if nets else None


def normalize_network(currency, network):
    """Каноническая сеть для (currency, network). Пусто → сеть по умолчанию валюты.
    Возвращает канон-код или None, если сеть недопустима для этой валюты (fail-closed).
    Значения нормализуются (strip/upper/синонимы), чтобы ' trc-20 ' не обошло защиту."""
    c = normalize_currency(currency)
    if c not in CURRENCY_NETWORKS:
        return None
    if network is not None and not isinstance(network, str):
        return None  # фейл-клоуз: нестроковый network не приводим молча
    raw = (network or "").strip().upper()
    if not raw:
        return CURRENCY_NETWORKS[c][0]
    canon = _NET_ALIASES.get(raw, raw)
    if canon is None:
        return None
    return canon if canon in CURRENCY_NETWORKS[c] else None


def validate_address(currency, address, network=None) -> bool:
    """True только если адрес формата, соответствующего валюте И сети.
    network=None → сеть по умолчанию (обратная совместимость: USDT→TRC20).
    Не в ту сеть (напр. 0x-адрес для USDT-TRC20) → False."""
    c = normalize_currency(currency)
    if address is not None and not isinstance(address, str):
        return False  # фейл-клоуз: нестроковый адрес не приводим молча
    addr = (address or "").strip()
    if not addr:
        return False
    net = normalize_network(c, network)
    if net is None:
        return False
    if c in ("BTC", "LTC"):
        pats = _ADDR_RE[c]
    elif c == "ETH":
        pats = _ADDR_RE[NET_ERC20]
    elif c == "USDT":
        pats = _ADDR_RE[NET_ERC20] if net == NET_ERC20 else _ADDR_RE[NET_TRC20]
    else:
        return False
    return any(re.match(p, addr) for p in pats)


def network_label(currency, network=None) -> str:
    """Человекочитаемая метка сети для UI, напр. 'TRC-20', 'ERC-20', 'Mainnet'."""
    net = normalize_network(currency, network)
    return {NET_TRC20: "TRC-20", NET_ERC20: "ERC-20", NET_MAINNET: "Mainnet"}.get(net, "")
