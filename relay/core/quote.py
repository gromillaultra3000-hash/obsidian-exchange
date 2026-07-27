"""Договорённость по заявке: сколько крипты обещано клиенту и можно ли это платить.

Зачем. Клиенту при создании заявки показывают «Получаете: X BTC» и обещают
«курс действует 15 минут». Но выплата исторически считала объём ЗАНОВО, по
свежему курсу на момент отправки:

    process_payout: rate = get_rate_with_markup(...); amount = rub / rate

То есть обещание не выполнялось никогда — клиент получал не X, а сколько
получится на момент выплаты. При росте рынка между оплатой и выплатой клиент
получал МЕНЬШЕ обещанного (разницу забирали мы), при падении — больше (теряли
мы). Плюс скидки VIP и промокодов, учтённые в котировке, при пересчёте
терялись — они применяются только к показу.

Решение: объём фиксируется в заявке при создании (orders.agreed_crypto_amount)
и выплачивается ИМЕННО он. Этот модуль — чистая логика: расчёт объёма по курсу
и проверка, безопасно ли платить зафиксированный объём.

Модуль без БД и сети — всё передаётся аргументами.
"""
from __future__ import annotations
import math
import os

# На сколько процентов зафиксированный объём может превышать «рыночный на момент
# выплаты», прежде чем мы откажемся платить его автоматически. Защита от выплаты
# по протухшей котировке: заявка могла зависнуть на дни, а рынок уйти. Такое
# уходит человеку на разбор, а не отменяется молча.
DEFAULT_MAX_EXCESS_PCT = 15.0

CRYPTO_ROUNDING = 8


def effective_rate(market_rate, commission_pct) -> float:
    """Курс для клиента (₽ за монету) из рыночного курса и комиссии.

    Единственно верная форма: market / (1 - c/100). Клиент получает (1-c/100)
    рыночного объёма — то есть комиссия действительно удерживается.

    ⚠️ Частая ошибка — написать market * (1 - c/100): тогда объём получается
    БОЛЬШЕ рыночного (при c=23% — 129.9% рынка вместо 77%), то есть обменник
    доплачивает клиенту ~30% сверху. Именно так считались DCA, подарки и
    лимитные заявки, пока это не было замечено.
    """
    m = _num(market_rate)
    c = _num(commission_pct)
    if m <= 0 or c >= 100:
        return 0.0
    return m / (1 - c / 100.0)


def crypto_for(rub_amount, rate) -> float:
    """Сколько крипты за rub_amount по курсу rate (курс уже с наценкой)."""
    rub = _num(rub_amount)
    r = _num(rate)
    if rub <= 0 or r <= 0:
        return 0.0
    return round(rub / r, CRYPTO_ROUNDING)


MAX_ALLOWED_EXCESS_PCT = 100.0   # потолок настройки: выше — защита теряет смысл


def _num(value) -> float:
    """Безопасное число: не-число, NaN и inf → 0.0. Денежные значения обязаны
    быть конечными, иначе NaN проскакивал бы все сравнения (NaN>x и NaN<=x —
    оба False) и протухшая котировка ушла бы в авто-выплату."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def max_excess_pct() -> float:
    """Порог из env, ограниченный сверху: inf/NaN/огромное значение отключили бы
    защиту от выплаты по протухшей котировке."""
    raw = os.getenv("PAYOUT_QUOTE_MAX_EXCESS_PCT", "").strip()
    if not raw:
        return DEFAULT_MAX_EXCESS_PCT
    try:
        v = float(raw)
    except ValueError:
        return DEFAULT_MAX_EXCESS_PCT
    if not math.isfinite(v) or v < 0:
        return DEFAULT_MAX_EXCESS_PCT
    return min(v, MAX_ALLOWED_EXCESS_PCT)


def settle_amount(agreed_amount, market_amount, max_excess=None) -> dict:
    """Сколько платить и можно ли платить автоматически.

    agreed_amount  — объём, зафиксированный при создании заявки (обещан клиенту);
    market_amount  — объём, который дал бы пересчёт по текущему курсу.

    Правила:
      * договорённости нет (старые заявки) → платим рыночный объём, как раньше;
      * договорённость есть и не превышает рынок больше чем на max_excess%
        → платим ОБЕЩАННОЕ (в т.ч. когда обещано меньше рынка — это то, на что
        клиент согласился);
      * превышение больше порога → авто-выплату запрещаем (fail-closed):
        котировка протухла, решение принимает человек.
    """
    limit = max_excess_pct() if max_excess is None else _num(max_excess)
    agreed = _num(agreed_amount)
    market = _num(market_amount)

    if market <= 0:
        return {"amount": 0.0, "auto_ok": False, "source": "none",
                "reason": "не удалось рассчитать рыночный объём"}

    if agreed <= 0:
        return {"amount": market, "auto_ok": True, "source": "market",
                "reason": "заявка без зафиксированной договорённости (легаси)"}

    excess_pct = (agreed - market) / market * 100.0
    if excess_pct > limit:
        return {
            "amount": agreed, "auto_ok": False, "source": "agreed",
            "excess_pct": round(excess_pct, 2),
            "reason": (f"обещано {agreed:.8f} — на {excess_pct:.1f}% больше рыночного "
                       f"{market:.8f} (порог {limit:.0f}%): котировка протухла, нужен разбор"),
        }
    return {"amount": agreed, "auto_ok": True, "source": "agreed",
            "excess_pct": round(excess_pct, 2),
            "reason": "платим объём, обещанный клиенту при создании заявки"}
