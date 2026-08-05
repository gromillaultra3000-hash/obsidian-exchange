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
import base64
import re

# BTC/LTC — 64 hex. TRON — 64 hex. ETH-совместимые — 0x + 64 hex.
_HEX64 = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
# Служебные пометки, которые txid НЕ являются
_MARKERS = {"manual", "manual-reconciled-20260719", "pending", "none", "null", "-", ""}
# Сети, где тот же хеш ходит ещё и в base64 (toncenter, кошельки TON).
_BASE64_HASH_CURRENCIES = {"TON"}


def normalize_txid(value, currency=None) -> str | None:
    """Хеш транзакции в канонической для проекта форме, или None.

    Форма записи хеша — свойство сети, а не универсальная константа. У TON
    один и тот же хеш ходит в двух видах: hex64 и base64 (44 символа, так его
    отдаёт toncenter и так его показывает кошелёк клиента). Приведение живёт
    здесь, а не у вызывающего: TON выдаётся вручную, владелец копирует хеш из
    кошелька, и без общего приведения он получил бы отказ «это не хеш» на
    настоящей выплате, а клиент — заявку без ссылки-доказательства.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in _MARKERS:
        return None
    if s.lower().startswith(("http://", "https://")):
        return None          # ссылка на оплату, а не транзакция
    if _HEX64.match(s):
        return s
    # base64 принимаем ТОЛЬКО там, где сеть его действительно использует:
    # для BTC случайная 44-символьная строка иначе сошла бы за доказательство.
    if str(currency or "").strip().upper() in _BASE64_HASH_CURRENCIES:
        try:
            raw = base64.b64decode(s.replace("-", "+").replace("_", "/")
                                   + "=" * (-len(s) % 4), validate=False)
        except Exception:
            return None
        if len(raw) == 32:
            return raw.hex()
    return None


def is_txid(value, currency=None) -> bool:
    """True — только для настоящего хеша транзакции."""
    return normalize_txid(value, currency) is not None


def explorer_url(currency, tx, network=None) -> str | None:
    """Ссылка в эксплорер или None, если показывать нечего.

    network важен для USDT: одна и та же монета живёт в TRON (tronscan) и в
    Ethereum (etherscan). Без сети берём каноническую для валюты (USDT→TRC-20),
    иначе ERC-20-выплата вела бы клиента в tronscan, где её нет.
    """
    cur = (currency or "BTC").upper()
    canon = normalize_txid(tx, cur)
    if canon is None:
        return None
    net = str(network or "").strip().upper().replace("-", "")
    if cur in ("USDT", "ETH") and net in ("ERC20", "ETH", "ETHEREUM", "EVM"):
        cur = "ETH"
    base = _EXPLORERS.get(cur)
    return f"{base}{canon}" if base else None


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
    # В ссылку идёт hex-форма: base64 из toncenter и из кошелька клиента
    # приводит к ней normalize_txid, чтобы форма была одна на весь проект.
    "TON": "https://tonviewer.com/transaction/",
    # Monero: хеш транзакции публичен и ищется в обозревателе, а вот суммы и
    # стороны в нём скрыты — по устройству сети. Ссылка нужна, чтобы клиент
    # убедился, что перевод существует; больше она ничего не покажет, и это
    # нормально.
    "XMR": "https://xmrchain.net/tx/",
}


def known_currencies() -> tuple:
    """Валюты, для которых ссылка вообще существует. Для проверок и диагностики.

    Карты наружу НЕ отдаём намеренно. Первая версия отдавала копию словаря
    «валюта → префикс» для поверхностей без Python — и это воспроизводило ровно
    ту беду, ради которой источник сводили в одно место: ключ без сети, значит
    USDT-ERC20 по такой карте уезжает в tronscan. Клиенту ссылку считает сервер
    (explorer_url) и отдаёт готовой в поле tx_url."""
    return tuple(sorted(_EXPLORERS))
