"""Деньги: сравнение и нормализация сумм без float-погрешности.

Суммы в БД лежат как REAL (исторически). Сплошную миграцию схемы на проде мы не
делаем — она рискованна, а прямых багов не нашли: сравнений сумм «на равенство»
в коде нет, а float64 для рублёвых величин точен с огромным запасом.
Опасен ОДИН случай — сравнение двух сумм в момент денежного решения. Для него
здесь есть явные хелперы, работающие в копейках (целые числа).

Почему допуск: провайдеры «уникализируют» сумму (XPay сдвигает на копейки/рубли,
чтобы отличить платежи), а комиссии дают дробный хвост. Точное равенство здесь
даст ложные тревоги, поэтому сравнение — с явным, названным допуском.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation

# Ключи, под которыми провайдеры кладут фактическую сумму в raw-ответ get_status
AMOUNT_KEYS = ("amount_rub", "amount", "base_amount", "paid_amount",
               "sum", "value", "total")


def to_minor(value) -> int | None:
    """Рубли → копейки (целое). None, если не число."""
    if value is None:
        return None
    try:
        return int((Decimal(str(value).replace(",", ".").strip()) * 100).to_integral_value())
    except (InvalidOperation, ValueError, TypeError):
        return None


def amounts_match(a, b, tol_rub: float = 1.0) -> bool | None:
    """Совпадают ли суммы в пределах допуска. None — если сравнить нечем."""
    ma, mb = to_minor(a), to_minor(b)
    if ma is None or mb is None:
        return None
    return abs(ma - mb) <= to_minor(tol_rub)


def extract_amount(raw) -> float | None:
    """Достаёт сумму из raw-ответа провайдера (форматы у всех разные)."""
    if not isinstance(raw, dict):
        return None
    for k in AMOUNT_KEYS:
        if k in raw and raw[k] not in (None, ""):
            m = to_minor(raw[k])
            if m is not None and m > 0:
                return m / 100
    return None
