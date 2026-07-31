"""Проверка идентификатора транзакции перед показом клиенту.

Зачем. В поле orders.paid_btc_tx исторически попадала ССЫЛКА НА ОПЛАТУ Platega
(96 заявок), а также служебные пометки вроде 'manual'. Код строил ссылку в
эксплорер простой склейкой, и получалось
    https://mempool.space/tx/https://pay.platega.io?id=…
Клиент видел кнопку «🔍 Транзакция в блокчейне», жал — и попадал в никуда.

Показывать сломанную ссылку хуже, чем не показывать никакой: она выглядит как
доказательство отправки, но ничего не доказывает.
"""
from __future__ import annotations
import re

# BTC/LTC — 64 hex. TRON — 64 hex. ETH-совместимые — 0x + 64 hex.
_HEX64 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
# Служебные пометки, которые txid НЕ являются
_MARKERS = {"manual", "manual-reconciled-20260719", "pending", "none", "null", "-", ""}


def is_txid(value) -> bool:
    """True — только для настоящего хеша транзакции."""
    if value is None:
        return False
    s = str(value).strip()
    if not s or s.lower() in _MARKERS:
        return False
    if s.lower().startswith(("http://", "https://")):
        return False          # ссылка на оплату, а не транзакция
    return bool(_HEX64.match(s))


def explorer_url(currency, tx, network=None) -> str | None:
    """Ссылка в эксплорер или None, если показывать нечего.

    network важен для USDT: одна и та же монета живёт в TRON (tronscan) и в
    Ethereum (etherscan). Без сети берём каноническую для валюты (USDT→TRC-20),
    иначе ERC-20-выплата вела бы клиента в tronscan, где её нет.
    """
    if not is_txid(tx):
        return None
    cur = (currency or "BTC").upper()
    net = str(network or "").strip().upper().replace("-", "")
    if cur in ("USDT", "ETH") and net in ("ERC20", "ETH", "ETHEREUM", "EVM"):
        cur = "ETH"
    base = _EXPLORERS.get(cur)
    return f"{base}{str(tx).strip()}" if base else None


# Куда ведёт ссылка на транзакцию. Одно место на весь проект: раньше карта была
# скопирована в четыре (бот, /api, инлайн-JS страницы оплаты, Mini App), копии
# разошлись, и новые направления получали либо пустую кнопку, либо ссылку в
# чужую сеть. Пополнять ТОЛЬКО здесь.
_EXPLORERS = {
    "BTC": "https://mempool.space/tx/",
    "LTC": "https://blockchair.com/litecoin/transaction/",
    "USDT": "https://tronscan.org/#/transaction/",
    "TRX": "https://tronscan.org/#/transaction/",
    "ETH": "https://etherscan.io/tx/",
    "XRP": "https://xrpscan.com/tx/",
    # tonviewer принимает хеш транзакции в том же виде, в каком его
    # отдаёт toncenter (base64), — отдельного преобразования не нужно.
    "TON": "https://tonviewer.com/transaction/",
}


def known_currencies() -> tuple:
    """Валюты, для которых ссылка вообще существует. Для проверок и диагностики.

    Карты наружу НЕ отдаём намеренно. Первая версия отдавала копию словаря
    «валюта → префикс» для поверхностей без Python — и это воспроизводило ровно
    ту беду, ради которой источник сводили в одно место: ключ без сети, значит
    USDT-ERC20 по такой карте уезжает в tronscan. Клиенту ссылку считает сервер
    (explorer_url) и отдаёт готовой в поле tx_url."""
    return tuple(sorted(_EXPLORERS))
