"""Fail-closed страж тестовых реквизитов — общий для ВСЕХ провайдеров.

16.07.2026 живому клиенту (order 99955015) была показана карта
1111111111111111 «Spitamenbank» — заведомо тестовый реквизит от Brabus. Клиент,
разумеется, не заплатил. Страж такого рода существовал (6deb80c), но жил ВНУТРИ
providers/xpayconnect.py и защищал только XPay — остальные провайдеры его
обходили. Здесь та же проверка поднята на уровень PaymentService, где через одну
точку (create_session) проходят все маршруты: бот, сайт, mini app, эскалация.

Политика: тестовый реквизит = ошибка провайдера, а не «реквизиты выданы».
Роутер уходит на следующий маршрут, здоровье провайдера штрафуется (мерчант в
песочнице действительно непригоден). Показать клиенту заведомо неоплачиваемые
реквизиты хуже, чем честно уйти на другой провайдер.

На реальных реквизитах не срабатывает — снимать страж не нужно. Аварийный
рубильник ALLOW_TEST_REQUISITES=1 (только для отладки песочницы).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Получатели-заглушки, которыми провайдеры отдают песочницу.
_TEST_HOLDERS = {"test name", "test", "тест", "test test", "ivan ivanov", "john doe"}

# Поля реквизитов, куда провайдеры кладут «куда платить».
_ADDRESS_FIELDS = ("card_number", "card", "phone", "account", "account_number")
_HOLDER_FIELDS = ("holder_name", "recipient", "full_name", "name")


def _looks_like_test_address(address: str) -> bool:
    digits = "".join(ch for ch in str(address or "") if ch.isdigit())
    if len(digits) < 8:
        return False
    # все цифры одинаковые (0000…, 1111…) — классический тестовый паттерн
    if len(set(digits)) == 1:
        return True
    # 1234567890123456 / 0123456789 — монотонная последовательность
    if len(digits) >= 12:
        deltas = {(int(b) - int(a)) % 10 for a, b in zip(digits, digits[1:])}
        if deltas == {1}:
            return True
    return False


def test_requisite_reason(invoice: dict) -> str | None:
    """Причина, по которой реквизиты выглядят тестовыми, либо None.

    Принимает invoice в форме, которую возвращают провайдеры:
    {'raw': {'requisites': {...}}, ...}. Толерантен к отсутствию полей —
    неизвестная форма молча пропускается (страж не должен ронять живые
    маршруты, если провайдер отдал непривычную структуру)."""
    if os.getenv("ALLOW_TEST_REQUISITES", "") == "1":
        return None
    if not isinstance(invoice, dict):
        return None

    raw = invoice.get("raw")
    if not isinstance(raw, dict):
        return None
    req = raw.get("requisites")
    if not isinstance(req, dict):
        return None

    for field in _ADDRESS_FIELDS:
        value = req.get(field)
        if value and _looks_like_test_address(value):
            return f"{field}={value}"

    for field in _HOLDER_FIELDS:
        value = req.get(field)
        if value and str(value).strip().lower() in _TEST_HOLDERS:
            return f"{field}={value}"

    return None
