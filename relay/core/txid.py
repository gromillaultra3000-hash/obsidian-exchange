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


def explorer_url(currency, tx) -> str | None:
    """Ссылка в эксплорер или None, если показывать нечего."""
    if not is_txid(tx):
        return None
    base = {
        "BTC": "https://mempool.space/tx/",
        "LTC": "https://blockchair.com/litecoin/transaction/",
        "USDT": "https://tronscan.org/#/transaction/",
        "TRX": "https://tronscan.org/#/transaction/",
    }.get((currency or "BTC").upper())
    return f"{base}{str(tx).strip()}" if base else None
