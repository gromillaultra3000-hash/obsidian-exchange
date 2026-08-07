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

# ── Выкуп: клиент продаёт нам монету, мы платим рубли ────────────────────────
# Ставка ОДНА и НЕ зависит от суммы, в отличие от лестницы покупки. Так решил
# владелец 07.08.2026, и это не упрощение расчёта: покупка и продажа — разные
# экономики. На покупке маржа платит за платёжный канал (провайдер берёт свой
# процент с приёма рублей), на продаже мы сами отдаём рубли и платим за выплату.
#
# Раньше выкуп считался по ступени покупки на 50 000 ₽ (то есть 19%), причём в
# ДВУХ местах независимо: exchange_calc.get_sell_rate — без персональных скидок,
# бот — со скидкой VIP и промокода. Один и тот же клиент видел в боте один курс
# выкупа, а на сайте другой, и заявка уходила по тому, где он её создал.
# Поэтому здесь не только число, но и сама формула: перемножение живёт в
# sell_rate(), а не по копии на каждой поверхности.
SELL_COMMISSION_DEFAULT = 9

# Потолок вменяемости для env-оверрайда. Опечатка «90» вместо «9» дала бы курс
# в десять раз ниже рынка, а «900» — отрицательную выплату, и оба варианта
# выглядели бы как рабочая настройка. Выше потолка — считаем значение ошибкой
# и берём умолчание, а не «почти ноль клиенту».
SELL_COMMISSION_MAX = 40


def _sell_env(name: str):
    """Число из переменной окружения или None, если её нет/она не число."""
    import os
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        val = float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not (0 <= val <= SELL_COMMISSION_MAX):
        return None
    return val


def sell_commission_percent(currency=None) -> float:
    """Наша ставка на выкуп монеты у клиента, в процентах.

    Переопределяется без релиза: SELL_COMMISSION_<МОНЕТА> точечно (например
    SELL_COMMISSION_BTC=7) или SELL_COMMISSION_PERCENT для всех. Негодное
    значение игнорируется — см. SELL_COMMISSION_MAX.
    """
    cur = str(currency or "").strip().upper()
    if cur:
        per_coin = _sell_env(f"SELL_COMMISSION_{cur}")
        if per_coin is not None:
            return per_coin
    common = _sell_env("SELL_COMMISSION_PERCENT")
    return common if common is not None else float(SELL_COMMISSION_DEFAULT)


def sell_rate(market_rate, currency=None) -> float:
    """Курс выкупа: рыночная цена минус наша ставка. Единственное место, где
    ставка превращается в число рублей — и бот, и сайт, и Mini App зовут его.

    Нечисловая или неположительная рыночная цена — это отсутствие курса, а не
    повод посчитать выплату от нуля: возвращаем 0.0, и вызывающий обязан
    трактовать его как отказ (так и делают _sell_rate в main.py и бот).
    """
    try:
        market = float(market_rate or 0)
    except (TypeError, ValueError):
        return 0.0
    if not market > 0 or market != market or market in (float("inf"), float("-inf")):
        return 0.0
    return round(market * (1 - sell_commission_percent(currency) / 100), 2)


def sell_commission_label(currency=None) -> str:
    """«9%» — для витрин. Дробную ставку показываем без хвоста нулей."""
    pct = sell_commission_percent(currency)
    return (f"{pct:.1f}".rstrip("0").rstrip(".") if pct % 1 else f"{int(pct)}") + "%"


def best_commission_percent() -> int:
    """Лучшая (минимальная) ставка покупки — для витрин «курс от».
    Раньше в рекламном посте стояло 0.19 литералом: правка COMMISSION_TIERS
    прошла бы мимо него молча, и пост обещал бы курс, которого больше нет."""
    return min(pct for _, pct in COMMISSION_TIERS)

# Накопительная скидка за оборот: (порог оборота в ₽, название, скидка в п.п.).
# Жила только в боте, а сайт обещал её отдельным вручную набранным списком —
# то есть скидку, которую начисляет ОДИН процесс, описывал текст в ДРУГОМ, и
# сверить их было нечем. Порядок — по убыванию порога, первый подошедший тир
# и есть ответ.
VIP_TIERS = (
    (300_000, "Platinum", -10),
    (100_000, "Gold", -6),
    (30_000, "Silver", -3),
    (0, "Standard", 0),
)


def vip_tier_for(total_rub) -> tuple:
    """(название, скидка в п.п.) по накопленному обороту."""
    try:
        total = float(total_rub or 0)
    except (TypeError, ValueError):
        total = 0.0
    for threshold, name, disc in VIP_TIERS:
        if total >= threshold:
            return name, disc
    return "Standard", 0


def vip_tiers_for_display():
    """Ступени скидки для витрин — без «Standard», о нём говорить нечего.

    from_rub — порог оборота, discount — скидка в процентных пунктах
    (положительное число: «минус N%»).
    """
    return [
        {
            "name": name,
            "from_rub": threshold,
            "from_label": f"{_ru(threshold)} ₽",
            "discount": abs(disc),
        }
        for threshold, name, disc in sorted(VIP_TIERS)
        if disc
    ]


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


def _ru(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def tiers_for_display():
    """Лестница для витрин (сайт, Mini App, тексты бота) — один формат для всех.
    from_rub/to_rub в рублях, to_rub=None означает «и выше».

    ⚠️ Границы ПОЛУОТКРЫТЫЕ: `amount < limit`. Подпись «до 5 000 ₽» читается как
    «включая 5 000», а на 5 000 ₽ списывается уже следующая ступень — витрина
    расходилась с расчётом ровно на границе. Разница в пользу клиента, поэтому
    жалоб не было и заметить это можно было только сверкой. Формулируем так,
    чтобы подпись означала ровно то, что делает код.
    """
    out, prev = [], 0
    for limit, pct in COMMISSION_TIERS:
        if limit is None:
            label = f"от {_ru(prev)} ₽ и выше"
        elif prev == 0:
            label = f"менее {_ru(limit)} ₽"
        else:
            label = f"{_ru(prev)} – {_ru(limit - 1)} ₽"
        out.append({
            "from_rub": prev,
            "to_rub": limit,
            "percent": pct,
            "label": label,
            "hint": _HINTS.get(pct, ""),
        })
        prev = limit or prev
    return out
