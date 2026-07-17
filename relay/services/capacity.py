"""Живая ёмкость: какие суммы платёжная сеть реально обслуживает прямо сейчас.

Мы рекламируем MAX_AMOUNT=500 000 ₽, а трейдеры по картам держат слоты 600–30 000.
Заявка на 40 000 ₽ обречена ещё до создания: 16.07 order 99955020 обошёл всю
цепочку (xpay 403 → montera → brabus → stormtrade → fallback) и клиент получил
голое «All providers failed». Он не знает, что виновата сумма, и уходит.

Единственный провайдер, отдающий живые лимиты трейдеров — Montera
(GET /payment-details/active). Проверено 16.07: по картам слоты 600–30 000 →
check_availability(40000,'card')=False, что ТОЧНО совпало с реальным отказом;
по СБП пул до 121 000. То есть данные предсказательные, а не декоративные.

Оговорка: это витрина ОДНОЙ Montera. У Vertu/Brabus лимиты не публикуются, их
пул может отличаться. Поэтому ёмкость используется как подсказка («доступно до
N ₽»), а не как жёсткий запрет, и при любой неопределённости мы молчим
(fail-open) — лучше дать клиенту попробовать, чем ошибочно завернуть живую
заявку. CAPACITY_HINTS=0 — выключить.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

_TTL = 60  # лимиты трейдеров меняются постоянно; чаще дёргать провайдера незачем
_cache = {"ts": 0.0, "data": None}


def hints_enabled() -> bool:
    return os.getenv("CAPACITY_HINTS", "1") != "0"


def _method_key(payment_method) -> str:
    """Montera различает phone (СБП) и card. Пустой метод трактуем как card —
    так же, как MonteraProvider.check_availability."""
    return "phone" if str(payment_method or "").lower() == "sbp" else "card"


def live_capacity(force: bool = False) -> dict | None:
    """{'card': (min,max), 'phone': (min,max)} либо None, если лимиты неизвестны."""
    if not hints_enabled():
        return None
    now = time.time()
    if not force and _cache["data"] is not None and now - _cache["ts"] < _TTL:
        return _cache["data"]
    try:
        from providers.montera import MonteraProvider
        limits = MonteraProvider()._get_active_limits()
    except Exception as exc:
        logger.debug("capacity: лимиты недоступны: %s", exc)
        limits = None

    data = None
    if limits:
        rub = (limits or {}).get("rub") or {}
        data = {}
        for key in ("card", "phone"):
            slots = rub.get(key) or []
            mins, maxs = [], []
            for s in slots:
                try:
                    mins.append(int(s["min_limit"]))
                    maxs.append(int(s["max_limit"]))
                except (KeyError, TypeError, ValueError):
                    continue
            if mins and maxs:
                data[key] = (min(mins), max(maxs))
        data = data or None

    _cache["ts"] = now
    _cache["data"] = data
    return data


def max_available(payment_method=None) -> int | None:
    """Потолок для метода, либо None если неизвестен."""
    cap = live_capacity()
    if not cap:
        return None
    rng = cap.get(_method_key(payment_method))
    return rng[1] if rng else None


def overall_max() -> int | None:
    """Максимум по всем методам — для витрины (сайт/mini app)."""
    cap = live_capacity()
    if not cap:
        return None
    maxs = [rng[1] for rng in cap.values() if rng]
    return max(maxs) if maxs else None


def shortfall_message(amount, payment_method=None) -> str | None:
    """Честное объяснение, если сумма заведомо выше живой ёмкости, иначе None.

    Возвращает None и при неизвестных лимитах, и когда сумма проходит — в обоих
    случаях сказать нам нечего, а врать про причину нельзя."""
    if not hints_enabled():
        return None
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return None
    top = max_available(payment_method)
    if not top or amt <= top:
        return None
    return (f"Сейчас нет реквизитов на {amt:,.0f} ₽ — свободные лимиты до "
            f"{top:,.0f} ₽. Попробуйте сумму поменьше или повторите через "
            f"10–15 минут.").replace(",", " ")
