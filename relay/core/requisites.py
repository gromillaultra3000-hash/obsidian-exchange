"""Нормализация реквизитов — единый источник для бота, /pay и Mini App.

Провайдеры регулярно отдают в имени получателя плейсхолдер вместо настоящего ФИО
('...', '-', 'Test Name', 'н/д'). Показывать такое клиенту хуже, чем не показывать
ничего: человек переводит 4-значную сумму незнакомцу по СБП, видит «Получатель: ...»
и закрывает окно. Банк всё равно покажет реальное имя на шаге подтверждения.
"""
from __future__ import annotations
import re

# Точные значения-заглушки (сравнение по нормализованной строке)
_EXACT = {
    "", "...", "…", "..", ".", "-", "--", "—", "_", "n/a", "na", "none", "null",
    "нд", "н/д", "неизвестно", "не указано", "нет данных", "unknown",
    "test", "test name", "тест", "string",
}
# Явно тестовые/шаблонные имена.
# ⚠️ «Клиент 1» / «Client 2» НЕ трогаем: у Vertu это настоящее имя трейдера
# (см. CLAUDE.md — живой тест 13.07: Т-Банк «Клиент 1», Сбер «Анди р»).
_PATTERNS = (
    re.compile(r"^test[\s_-]", re.I),
    re.compile(r"^[.\-_—…\s]+$"),          # только пунктуация/пробелы
    re.compile(r"^(x|х|\*|0)+$", re.I),     # xxxx / **** / 0000
)


def is_placeholder_name(value) -> bool:
    """True, если имя получателя — заглушка, а не настоящее ФИО."""
    if value is None:
        return True
    s = str(value).strip()
    if not s:
        return True
    norm = re.sub(r"\s+", " ", s).strip().lower()
    if norm in _EXACT:
        return True
    return any(p.match(s.strip()) for p in _PATTERNS)


def clean_recipient(value):
    """Возвращает имя получателя или '' — если это заглушка."""
    return "" if is_placeholder_name(value) else str(value).strip()
