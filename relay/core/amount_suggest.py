"""Подсказка рабочей суммы, когда под запрошенную нет трейдера.

Зачем. За 30 дней 52 заявки (635 045 ₽) умерли, не дойдя до реквизитов, и доля
растёт с суммой: 4% на суммах до 3к против 22% на 11–21к. Провайдер отвечает
«нет трейдера под сумму» и отдаёт живые диапазоны своих слотов. Раньше клиенту
показывали сырой список диапазонов («3 000–7 000 ₽, 10 000–15 000 ₽») и
предлагали разбираться самому. Человек с суммой 12 000 ₽ должен был сам понять,
что ему подходит 10 000 — и обычно просто уходил.

Здесь считается ближайшая сумма, которая реально пройдёт.
"""
from __future__ import annotations


def _ranges(slots) -> list[tuple[int, int]]:
    out = []
    for s in slots or []:
        try:
            lo, hi = int(s["min_limit"]), int(s["max_limit"])
        except (KeyError, TypeError, ValueError):
            continue
        if hi >= lo > 0:
            out.append((lo, hi))
    return sorted(set(out))


def _round_nice(v: int, lo: int, hi: int) -> int:
    """Округляет к «красивому» числу, не выходя за границы диапазона."""
    for step in (1000, 500, 100):
        c = round(v / step) * step
        if lo <= c <= hi:
            return int(c)
    return int(v)


def suggest_amounts(slots, requested: float, limit: int = 3) -> list[int]:
    """Суммы из доступных диапазонов, ближайшие к запрошенной.

    Возвращает до `limit` вариантов, отсортированных по близости к requested.
    Пустой список — если диапазонов нет (значит трейдеров нет вовсе, и
    подсказывать нечего).
    """
    rs = _ranges(slots)
    if not rs:
        return []
    try:
        req = float(requested)
    except (TypeError, ValueError):
        return []

    # Если сумма попадает хоть в один диапазон — подсказывать нечего.
    # (Иначе клиенту с рабочей суммой предложили бы «ближайшую рабочую» — бред.)
    if any(lo <= req <= hi for lo, hi in rs):
        return []

    cands = []
    for lo, hi in rs:
        near = hi if req > hi else lo  # ближайшая точка диапазона
        cands.append(_round_nice(int(near), lo, hi))

    seen, out = set(), []
    for v in sorted(set(cands), key=lambda x: (abs(x - req), -x)):
        if v not in seen:
            seen.add(v)
            out.append(v)
        if len(out) >= limit:
            break
    return out


def suggest_text(slots, requested: float) -> str:
    """Готовая фраза для клиента или '' — если подсказать нечего."""
    s = suggest_amounts(slots, requested)
    if not s:
        return ""
    fmt = lambda v: f"{v:,}".replace(",", " ")
    if len(s) == 1:
        return f"Ближайшая сумма, которая пройдёт прямо сейчас: <b>{fmt(s[0])} ₽</b>."
    return ("Прямо сейчас пройдут суммы: "
            + ", ".join(f"<b>{fmt(v)} ₽</b>" for v in s) + ".")
