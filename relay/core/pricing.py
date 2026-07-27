"""Единый источник тарифной лестницы обменника.

Зачем. Лестница комиссий была продублирована в ТРЁХ местах и во всех трёх
разная — то есть клиенту показывали одну цену, а списывали другую:

  bot/main_bot.py            <5k:27  <10k:25  <20k:23  ≥20k:19   ← истина
  relay/utils/exchange_calc  ≤4999:27         ≤14999:23    :19   ← нет тира 25%
  static/js/main.js (виджет) <10k:27  <30k:25 <100k:23    :19    ← чужие границы
                             + USDT фиксированные 2%             ← отменено 25.07

Виджет на главной — это витрина, по которой клиент принимает решение. Обещать
USDT по 2%, а списывать по тарифу — ровно тот обман, который вычищали 25.07,
просто виджет тогда пропустили.

Здесь лестница задана ОДИН раз, в терминах «граница → процент», и отдаётся
всем поверхностям: боту, серверным расчётам и фронту (через /api/rates), чтобы
JS ничего не хардкодил.

Модуль чистый: без БД и сети.
"""
from __future__ import annotations

# (верхняя граница суммы в ₽ исключительно, процент). None = «и выше».
# Значения — из бота, он же был источником фактического списания.
COMMISSION_TIERS = (
    (5000, 27),
    (10000, 25),
    (20000, 23),
    (None, 19),
)

MIN_COMMISSION_PERCENT = 2   # пол для VIP/промо-скидок


def commission_percent(amount_rub) -> int:
    """Базовая комиссия обменника для суммы в рублях (без VIP/промо)."""
    try:
        amount = float(amount_rub or 0)
    except (TypeError, ValueError):
        amount = 0.0
    for limit, pct in COMMISSION_TIERS:
        if limit is None or amount < limit:
            return pct
    return COMMISSION_TIERS[-1][1]


_HINTS = {
    27: "минимальный диапазон обмена",
    25: "средний диапазон обмена",
    23: "увеличенный объём",
    19: "крупные обмены",
}


def tiers_for_display():
    """Лестница для витрин (сайт, Mini App, тексты бота) — один формат для всех.
    from_rub/to_rub в рублях, to_rub=None означает «и выше»."""
    out, prev = [], 0
    for limit, pct in COMMISSION_TIERS:
        out.append({
            "from_rub": prev,
            "to_rub": limit,
            "percent": pct,
            "label": (f"до {limit:,} ₽".replace(",", " ") if limit
                      else f"от {prev:,} ₽ и выше".replace(",", " ")),
            "hint": _HINTS.get(pct, ""),
        })
        prev = limit or prev
    return out
