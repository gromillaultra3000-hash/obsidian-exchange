"""Какие монеты обменник РЕАЛЬНО предлагает клиенту прямо сейчас.

Зачем отдельный слой. `core.assets` знает, какие валюты вообще поддерживаются
кодом (BTC/LTC/USDT/ETH) — это статическое знание. Но показать клиенту кнопку
«купить ETH» можно только если ETH есть чем выдать. Иначе заявка создаётся,
деньги от клиента приходят, а крипты нет — худший из возможных исходов, дороже
любого недополученного заказа.

Поэтому витрина = поддержка кодом ∧ подтверждённая ликвидность:
  * BTC/LTC/USDT — исторические направления, всегда в витрине (их контур
    выплат работает давно);
  * новые мультичейн-направления (ETH, USDT-ERC20) — только при
    MULTICHAIN_UI_ENABLED И непустом курируемом резерве (таблица reserves,
    задаётся админом через /setreserve).

Резерв выбран признаком ликвидности намеренно: он уже курируется вручную
(OPSEC — не сырой баланс кошелька), у админа есть привычная команда, и «выключить
направление» = /setreserve ETH 0. Дополнительный автоматический признак —
готовый secure EVM-вольт с включённым гейтом авто-выплат.

Кеш 60 с: витрина дёргается на каждый рендер страницы и каждый /api/rates.
"""
from __future__ import annotations
import os
import sqlite3
import time

import sys
if "/root/relay" not in sys.path:
    sys.path.insert(0, "/root/relay")
from core import assets as _assets

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Направления, работавшие до мультичейна — их выдача не зависит от новых гейтов.
_LEGACY_CURRENCIES = ("BTC", "LTC", "USDT")

_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 60.0


def _reserves() -> dict:
    """Курируемые резервы {валюта: количество}. Ошибка чтения → пусто (fail-closed:
    новое направление не покажем, легаси-направления от этого не пострадают)."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            rows = conn.execute("SELECT currency, amount FROM reserves").fetchall()
        finally:
            conn.close()
        return {str(c).upper(): float(a or 0) for c, a in rows}
    except Exception:
        return {}


# Ключ курируемого резерва для USDT в сети Ethereum. Отдельный от «USDT»
# (тот — про TRON): наличие ETH или USDT-TRC20 НЕ доказывает, что в EVM-вольте
# лежит USDT. Ставится админом: /setreserve USDT_ERC20 <кол-во>.
RESERVE_USDT_ERC20 = "USDT_ERC20"


def _compute() -> dict:
    reserves = _reserves()

    currencies = list(_LEGACY_CURRENCIES)
    networks = {c: _assets.networks_for(c)[:1] for c in _LEGACY_CURRENCIES}
    networks["USDT"] = [_assets.NET_TRC20]

    # Ликвидность подтверждается ТОЛЬКО курируемым резервом. Сознательно не
    # открываем направление по факту «вольт создан + гейт включён»: созданный
    # вольт может быть пустым или заблокированным, то есть это был бы fail-open
    # ровно там, где цена ошибки — оплаченная заявка без выдачи. Резерв ставит
    # человек, который видел баланс.
    if _assets.multichain_ui_enabled():
        if reserves.get("ETH", 0) > 0:
            currencies.append("ETH")
            networks["ETH"] = [_assets.NET_ERC20]
        # USDT-ERC20 — независимое направление со своим резервом
        if reserves.get(RESERVE_USDT_ERC20, 0) > 0:
            networks["USDT"] = [_assets.NET_TRC20, _assets.NET_ERC20]

    eth_on = "ETH" in currencies
    return {
        "currencies": tuple(currencies),
        "networks": networks,
        "eth_enabled": eth_on,
        "reason_eth_off": (
            "" if eth_on
            else ("MULTICHAIN_UI_ENABLED выключен" if not _assets.multichain_ui_enabled()
                  else "нет подтверждённой ликвидности ETH: задайте /setreserve ETH <кол-во>")
        ),
    }


def _safe_default() -> dict:
    """Витрина на случай любого сбоя: только исторические направления в их
    канонических сетях. Fail-closed — сбой не должен ОТКРЫВАТЬ новое направление."""
    return {
        "currencies": _LEGACY_CURRENCIES,
        "networks": {"BTC": [_assets.NET_MAINNET], "LTC": [_assets.NET_MAINNET],
                     "USDT": [_assets.NET_TRC20]},
        "eth_enabled": False,
        "reason_eth_off": "витрина недоступна — направление закрыто",
    }


def get_offerings(force: bool = False) -> dict:
    now = time.time()
    if not force and _cache["data"] is not None and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]
    try:
        data = _compute()
    except Exception:
        # Кеш не портим: следующий вызов попробует пересчитать заново.
        return _safe_default()
    _cache["data"] = data
    _cache["ts"] = now
    return data


def offered_currencies(force: bool = False) -> tuple:
    """Валюты, которые сейчас можно предлагать клиенту."""
    return get_offerings(force)["currencies"]


def offered_networks(currency, force: bool = False) -> list:
    """Сети, доступные клиенту для валюты (первая — по умолчанию)."""
    return list(get_offerings(force)["networks"].get(_assets.normalize_currency(currency), []))


def is_offered(currency, network=None, force: bool = False) -> bool:
    """Можно ли принять заявку на (валюту, сеть) прямо сейчас. Fail-closed."""
    cur = _assets.normalize_currency(currency)
    if cur not in offered_currencies(force):
        return False
    net = _assets.normalize_network(cur, network)
    if net is None:
        return False
    return net in offered_networks(cur, force)
