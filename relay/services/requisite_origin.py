"""Определение «страны» выданного реквизита: РФ или зарубежный.

Разбор нулевой конверсии (16.07.2026): за 3 дня клиентам-россиянам выдали 9 карт
9762… (узбекский Humo, банк подписан «Карта получателя»), 5 ссылок на «Душанбе
сити» и ровно ОДНУ карту Сбербанка. Люди платят по СБП из российского банка и
видят узбекскую карту без имени получателя — не платят. 71 заявка, 0 оплат.

Модуль отвечает на два вопроса:
  1) роутеру (через smart_router.RU_PROVIDERS) — кого пробовать первым;
  2) странице /pay — надо ли честно предупредить, что реквизит зарубежный.

Классификация консервативная: то, в чём не уверены → 'unknown', а не 'ru'.
Соврать клиенту «российский банк» про узбекскую карту хуже, чем промолчать.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

RU = "ru"
FOREIGN = "foreign"
UNKNOWN = "unknown"

# Российские банки (нижний регистр, подстрочное вхождение).
_RU_BANK_MARKERS = (
    "сбер", "sber", "тинькофф", "тбанк", "т-банк", "tinkoff", "tbank",
    "альфа", "alfa", "втб", "vtb", "райффайзен", "raiffeisen", "газпром",
    "gazprom", "открытие", "otkritie", "совкомбанк", "sovcombank", "росбанк",
    "rosbank", "почта банк", "pochta", "мтс банк", "mts", "уралсиб", "uralsib",
    "юmoney", "юмани", "yumoney", "qiwi", "озон банк", "ozon", "яндекс",
    "русский стандарт", "хоум кредит", "мкб", "psb", "промсвязь", "ак барс",
)

# Зарубежные маркеры, встреченные живьём у наших провайдеров.
_FOREIGN_BANK_MARKERS = (
    "spitamen", "спитамен", "душанбе", "dushanbe", "dcbank", "humo", "хумо",
    "uzcard", "узкард", "click", "seabank", "си банк", "amonatbank", "амонат",
    "eskhata", "эсхата", "korti milli", "алиф", "alif", "kapitalbank",
    "ipak yuli", "hamkorbank", "asia alliance", "tenge", "kaspi", "халык",
    "halyk", "forte", "freedom",
)

# BIN-префиксы. РФ: МИР 2200-2204. Зарубежные, встреченные живьём: 9762 (Humo,
# Узбекистан), 8600 (Uzcard, Узбекистан).
_RU_BINS = ("2200", "2201", "2202", "2203", "2204")
_FOREIGN_BINS = ("9762", "8600")

_ADDRESS_FIELDS = ("card_number", "card", "account", "account_number")
_BANK_FIELDS = ("bank_name", "bank")


def _digits(value) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def classify_requisites(req: dict, payment_link: str = "") -> str:
    """req — словарь реквизитов провайдера (raw['requisites']).

    Порядок проверок от самого надёжного признака к слабому."""
    if not isinstance(req, dict):
        req = {}

    bank = ""
    for f in _BANK_FIELDS:
        if req.get(f):
            bank = str(req[f]).lower()
            break

    # 1. Имя банка — самый прямой признак
    if bank:
        if any(m in bank for m in _FOREIGN_BANK_MARKERS):
            return FOREIGN
        if any(m in bank for m in _RU_BANK_MARKERS):
            return RU

    # 2. BIN карты
    card = ""
    for f in _ADDRESS_FIELDS:
        if req.get(f):
            card = _digits(req[f])
            break
    if len(card) >= 4:
        if card[:4] in _FOREIGN_BINS:
            return FOREIGN
        if card[:4] in _RU_BINS:
            return RU

    # 3. Платёжная ссылка: НСПК = российская СБП, остальные ссылки у наших
    #    провайдеров = трансграничные рельсы (XPay → payment.link-fast.io)
    link = str(payment_link or req.get("payment_link") or "").lower()
    if link:
        if "nspk.ru" in link:
            return RU
        return FOREIGN

    # 4. Телефон СБП: СБП существует только в РФ → реквизит российский
    if req.get("phone"):
        return RU

    return UNKNOWN


def classify_invoice(invoice: dict) -> str:
    """Обёртка над classify_requisites для формы, которую возвращают провайдеры."""
    if not isinstance(invoice, dict):
        return UNKNOWN
    raw = invoice.get("raw")
    raw = raw if isinstance(raw, dict) else {}
    req = raw.get("requisites")
    req = req if isinstance(req, dict) else {}
    link = invoice.get("payment_link") or raw.get("payment_link") or ""
    return classify_requisites(req, link)
