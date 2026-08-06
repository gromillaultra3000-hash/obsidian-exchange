"""Что клиент может нам ПРОДАТЬ — один источник на бот и сайт.

Направление продажи открывается не так, как покупка. Для покупки нужна наша
ликвидность (курируемый резерв, `services/offerings.py`); чтобы принять монету,
ликвидность не нужна вовсе — нужен адрес, куда её принять, и цена.

Зачем отдельный модуль. Список продаваемых монет жил рукописными словарями на
двух поверхностях: в боте `SELL_RECEIVE_ADDRESSES` из четырёх строк, на сайте
кортеж `('BTC','LTC','USDT','TON')`. Владелец мог завести адрес приёма Monero
и не получить ничего: монеты нет в словаре — значит, её нет в меню, и понять
это можно только чтением кода. Новое направление должно включаться настройкой,
а не правкой двух файлов, иначе оно молча не включается.

Четыре условия, и все fail-closed — потому что цена ошибки здесь не
недополученный заказ, а деньги клиента, ушедшие в никуда:

1. **Адрес приёма задан** (`SELL_<МОНЕТА>_ADDRESS`). Нет адреса — монеты нет
   в меню: звать продать некуда.
2. **Адрес проходит проверку СВОЕЙ монеты.** Опечатка или адрес чужой сети в
   настройке — это не «монета недоступна», это перевод клиента в пустоту, и
   вернуть его нельзя. Такой адрес закрывает направление и пишется в лог.
3. **Минимум объявлен.** Раньше монета без минимума получала `0.001` из
   умолчания `dict.get`: для Monero это ~30 ₽, то есть заявка на пыль, за
   которую мы платим комиссию СБП и теряем на каждой.
4. **Метку перевода есть чем выдать.** У XRP и TON назначение — это адрес плюс
   метка; перевод без метки на общий адрес не привязать к заявке, а часто и не
   вернуть. TON метку получает (`core.wallet_send.marker_for`), XRP — нет,
   поэтому XRP закрыт, пока метку не научимся выдавать. Это условие из
   реестра, а не список исключений: новая монета с меткой закроется сама.

Проверка депозита в цепи (`bot/sell_guard.py`) — отдельный вопрос: её нет для
ETH, XMR и любой новой монеты, и это НЕ повод прятать направление. Страж и так
fail-closed: без проверки вердикт `unsupported`, рубли автоматом не уходят,
решает человек. Но клиенту об этом говорят прямо — `needs_manual_check()`.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:                                     # модуль зовут и из бота, и из relay
    from core import assets as _assets
except ImportError:                      # запуск изнутри пакета core
    from . import assets as _assets      # type: ignore

# Минимальная сумма продажи. Порядок ~30–50 $ на монету: ниже комиссия сети и
# перевод по СБП съедают заявку целиком. Монета, которой здесь нет, к продаже
# НЕ предлагается — умолчание тут означало бы «примем сколько угодно пыли».
MINIMUMS = {
    "BTC": 0.0005,
    "LTC": 0.5,
    "USDT": 50,
    "TON": 5,
    "ETH": 0.01,
    "XMR": 0.15,
    "XRP": 20,
}

# Монеты, чей перевод мы умеем пометить меткой заявки. Без метки перевод на
# ОБЩИЙ адрес приёма не привязывается к клиенту.
MARKED_CURRENCIES = ("TON",)

# Пары (монета, сеть), депозит в которых `bot/sell_guard.py` умеет найти сам.
# Список живёт здесь, а не в страже: его читают и поверхности — чтобы сказать
# клиенту правду о том, кто подтвердит зачисление.
#
# Ключ — ПАРА, а не монета: у USDT сетей две, а страж читает только TRON. С
# ключом по монете ERC-20 адрес приёма считался бы «проверяемым», страж искал
# бы депозит Ethereum в TRON и не находил никогда, а клиенту при этом обещали
# бы автоматические 30–60 минут. Нашёл codex.
AUTO_CHECKED = (
    ("BTC", _assets.NET_MAINNET),
    ("LTC", _assets.NET_MAINNET),
    ("USDT", _assets.NET_TRC20),
    ("TON", _assets.NET_TON),
)


def _env_address(currency: str) -> str:
    return (os.getenv(f"SELL_{currency}_ADDRESS", "") or "").strip()


def receive_address(currency) -> str:
    """Адрес приёма монеты или пустая строка, если продажа закрыта.

    Проверка адреса здесь, а не только при создании заявки: неверный адрес в
    настройке — единственная ошибка этого модуля, которая уносит чужие деньги
    без возврата, и обнаружиться она должна ДО того, как его увидит клиент.

    Адрес проверяется по КАЖДОЙ сети монеты, а не по сети по умолчанию: у USDT
    первой в реестре стоит TRC-20, и проверка «без сети» отвергала бы верный
    `0x…` адрес приёма в Ethereum — направление молча не открывалось бы вовсе.
    Нашёл codex.
    """
    cur = _assets.normalize_currency(currency)
    if not cur:
        return ""
    addr = _env_address(cur)
    if not addr:
        return ""
    if receive_network(cur) is None:
        # Не «недоступно временно»: настройка неверна, и пока её не исправят,
        # каждый принятый перевод был бы потерян. Причина уже в логе —
        # receive_network пишет её подробнее.
        return ""
    return addr


def _fit_networks(cur: str, addr: str = None):
    """Сети монеты, к которым подходит адрес. None — спросить не о чем
    (нет монеты, нет адреса) или проверка сорвалась."""
    if addr is None:
        addr = _env_address(cur) if cur else ""
    if not cur or not addr:
        return None
    try:
        return [n for n in _assets.networks_for(cur)
                if _assets.validate_address(cur, addr, n)]
    except Exception as e:
        logger.error("sell_assets: сеть адреса %s не определить (%s)", cur, e)
        return None


def network_of(currency, address):
    """Сеть, которой принадлежит КОНКРЕТНЫЙ адрес, или None.

    Нужна стражу: в заявке сохранён адрес приёма на момент её создания, и
    судить о ней по сегодняшней настройке нельзя — адрес мог смениться.
    """
    cur = _assets.normalize_currency(currency)
    fit = _fit_networks(cur, str(address or "").strip())
    return fit[0] if fit and len(fit) == 1 else None


def receive_network(currency):
    """Сеть, которой принадлежит настроенный адрес приёма, или None.

    У USDT сетей две, и адрес однозначно называет свою: `T…` — TRON, `0x…` —
    Ethereum. Знать её обязательно: клиент, отправивший USDT-ERC20 на наш
    TRON-адрес, теряет перевод, и виноват в этом будет тот, кто не написал
    сеть рядом с адресом.

    Если адрес подходит СРАЗУ к нескольким сетям монеты, направление
    закрывается: назвать сеть мы не можем, а промолчать — значит переложить
    выбор на клиента, который его не сделает.
    """
    cur = _assets.normalize_currency(currency)
    fit = _fit_networks(cur)
    if fit is None:
        return None
    if len(fit) != 1:
        if len(fit) > 1:
            logger.error("sell_assets: адрес приёма %s подходит сразу к сетям %s — "
                         "назвать клиенту одну нельзя, продажа закрыта", cur, fit)
        else:
            logger.error("sell_assets: SELL_%s_ADDRESS не похож на адрес %s ни в "
                         "одной из сетей %s — продажа этой монеты закрыта, "
                         "исправьте настройку", cur, cur, _assets.networks_for(cur))
        return None
    return fit[0]


def minimum(currency):
    """Минимальная сумма продажи или None, если она не объявлена."""
    return MINIMUMS.get(_assets.normalize_currency(currency))


def needs_marker(currency) -> bool:
    """Нужна ли переводу метка заявки (у монеты назначение = адрес + метка)."""
    cur = _assets.normalize_currency(currency)
    return cur in getattr(_assets, "TAGGED_CURRENCIES", {})


def can_mark(currency) -> bool:
    """Умеем ли выдать метку для этой монеты."""
    return _assets.normalize_currency(currency) in MARKED_CURRENCIES


def deposit_check_available(currency, network=None) -> bool:
    """Умеет ли страж найти депозит сам — для СЕТИ настроенного адреса приёма.

    Сеть можно передать явно (страж знает её из заявки); без неё берётся сеть
    адреса приёма. Не знаем сеть — считаем, что не умеем: обещать автоматику
    вслепую дороже, чем лишний раз позвать человека.
    """
    cur = _assets.normalize_currency(currency)
    net = _assets.normalize_network(cur, network) if network else receive_network(cur)
    if not cur or not net:
        return False
    return (cur, net) in AUTO_CHECKED


def needs_manual_check(currency, network=None) -> bool:
    """Правда для клиента: зачисление подтвердит человек, а не автомат."""
    return not deposit_check_available(currency, network)


def closed_reason(currency) -> str:
    """Почему монета не продаётся. Пустая строка = продаётся.

    Отдельной функцией, чтобы админ видел причину, а не гадал по пустому меню.
    """
    cur = _assets.normalize_currency(currency)
    if not cur or not _assets.is_supported_currency(cur):
        return "монета не поддержана кодом"
    if minimum(cur) is None:
        return f"не объявлен минимум продажи (sell_assets.MINIMUMS['{cur}'])"
    if needs_marker(cur) and not can_mark(cur):
        tag = _assets.tag_name(cur) or "метка"
        return (f"переводу {cur} нужна {tag}, а выдавать её мы пока не умеем — "
                f"перевод на общий адрес было бы не привязать к заявке")
    if not _env_address(cur):
        return f"не задан адрес приёма (SELL_{cur}_ADDRESS)"
    fit = _fit_networks(cur)
    if not fit:
        return f"SELL_{cur}_ADDRESS не проходит проверку адреса {cur}"
    if len(fit) > 1:
        return (f"по адресу приёма не понять сеть {cur} (подходят {', '.join(fit)}) — "
                f"клиенту нечего написать рядом с адресом, а перевод не в ту сеть "
                f"теряется")
    return ""


def sell_currencies() -> tuple:
    """Монеты, которые клиент реально может продать. Порядок — как в реестре.

    Цену здесь НЕ спрашиваем: у бота и сайта разные источники курса, и каждая
    поверхность добавляет свою проверку. Общее — то, что решается настройкой.
    """
    out = []
    for cur in _assets.CURRENCY_NETWORKS:
        try:
            if not closed_reason(cur):
                out.append(cur)
        except Exception as e:
            logger.error("sell_assets: %s пропущена из-за ошибки: %s", cur, e)
    return tuple(out)


def label(currency) -> str:
    """Подпись монеты для меню: значок, код и — у монеты с несколькими сетями —
    сеть адреса приёма.

    Сеть в подписи не украшение. Прежние подписи набирались руками и писали
    «USDT (TRC20)»; общая подпись без сети означала бы, что клиент с USDT в
    Ethereum отправляет их на наш TRON-адрес и теряет. Нашёл codex.
    """
    cur = _assets.normalize_currency(currency)
    base = f"{COIN_ICONS.get(cur, '•')} {cur}"
    try:
        if len(_assets.networks_for(cur)) > 1:
            net = receive_network(cur)
            if net:
                return f"{base} ({_assets.network_label(cur, net)})"
    except Exception:
        pass
    return base


# Значки монет. Держим рядом с реестром продажи, а не в боте: сайту нужны те же.
COIN_ICONS = {
    "BTC": "₿", "LTC": "Ł", "USDT": "💵", "ETH": "Ξ",
    "XRP": "✕", "TON": "💎", "XMR": "ɱ",
}
