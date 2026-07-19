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


# Поля, куда провайдеры иногда кладут ССЫЛКУ вместо номера
_DETAIL_FIELDS = ("card_number", "phone", "account")
# «Карта получателя»/«Карта» — не банк, а подпись поля
_FAKE_BANKS = {"карта получателя", "карта", "счёт получателя", "реквизиты", "card"}


def normalize_requisites(req: dict) -> dict:
    """Приводит реквизиты к виду, пригодному для показа клиенту.

    Главное: если провайдер положил ссылку в поле номера (Brabus tbank_deeplink
    кладёт https://pay.paymentssystem.us/... в card_number), клиент видит
    «Карта: https://…» — вставить такое в банк невозможно. За 30 дней такой
    экран показали 30 раз и получили НОЛЬ оплат. Ссылку переносим в payment_link,
    чтобы поверхности показали кнопку/QR, а не мусорный «номер карты».
    """
    if not isinstance(req, dict):
        return req
    r = dict(req)

    # 1) ссылка в поле номера → payment_link
    for f in _DETAIL_FIELDS:
        v = str(r.get(f) or "").strip()
        if v.lower().startswith(("http://", "https://")):
            if not str(r.get("payment_link") or "").strip():
                r["payment_link"] = v
            r[f] = ""

    # 2) плейсхолдеры в имени получателя
    for f in ("recipient", "holder_name"):
        if is_placeholder_name(r.get(f)):
            r[f] = ""

    # 3) дубль «получатель == номер»
    detail = str(r.get("phone") or r.get("card_number") or "").strip()
    rec = str(r.get("recipient") or "").strip()
    if rec and detail and rec.replace(" ", "") == detail.replace(" ", ""):
        r["recipient"] = ""

    # 4) подпись поля вместо банка
    bank = str(r.get("bank_name") or r.get("bank") or "").strip()
    if bank.lower() in _FAKE_BANKS:
        r["bank_name"] = ""
        if "bank" in r:
            r["bank"] = ""
        bank = ""
    # 5) банк-фолбэк только когда есть реальный номер
    if not bank:
        if str(r.get("phone") or "").strip():
            r["bank_name"] = "СБП"
        elif str(r.get("card_number") or "").strip():
            r["bank_name"] = "Карта"

    return r
