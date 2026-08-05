"""Доказательство владения адресом подписью кошелька (BTC, LTC).

Зачем. Книга адресов до сих пор наполнялась только СЕРВЕРОМ — по заявкам, по
которым монеты уже дошли. У клиента, который ещё ничего не менял, она пуста, и
первый — самый опасный — адрес он набирает руками, без единой подсказки. Взять
адрес из запроса и просто положить в его список нельзя: тогда обменник станет
бесплатным пробником чужих кошельков (см. шапки `core/wallet_link` и
`core/address_book`). Есть ровно один способ добавить адрес по просьбе клиента,
не ослабляя это правило, — потребовать доказательство владения.

Что доказывает подпись. Кошелёк подписывает наш текст своим ключом; из подписи
восстанавливается публичный ключ, из него — адрес. Совпал с заявленным — ключ у
подписавшего. Ничего не переводится и никакого доступа к средствам мы не
получаем: подписанное сообщение не является транзакцией и не может ею стать —
формат Bitcoin Signed Message с его двойным префиксом длины несовместим с
форматом подписываемой транзакции.

Три правила, ради которых модуль написан именно так:

1. Текст для проверки СОБИРАЕТСЯ ЗДЕСЬ из адреса и кода, а не принимается из
   запроса. Поэтому у `verify()` нет параметра «сообщение»: иначе клиенту
   достаточно было бы прислать подпись любого текста, который его кошелёк
   когда-либо подписывал, — включая текст, подсунутый ему кем-то другим.
2. Код (nonce) выдаётся нами, живёт 15 минут и привязан к КОНКРЕТНОМУ клиенту
   (`core.tonconnect.make_payload` — та же машинка одноразовых кодов, что у
   TON Connect; второй реализации защиты от повтора в проекте быть не должно).
   Без привязки к клиенту чужое доказательство, подсмотренное на проводе,
   вставлялось бы в свой запрос — и адрес жертвы оказался бы в кошельке чужого
   человека, вместе с балансом и историей.
3. Любая неожиданность — «не подтверждено». Сбой импорта, нераспознанный адрес,
   мусор вместо подписи: молчаливое «ну наверное да» здесь стоит чужих денег.

Почему подписанный текст на латинице. Его показывает экран кошелька, в том
числе аппаратного; часть устройств отображает не-ASCII как «?» или отказывается
подписывать. Клиенту вокруг поля всё объясняется по-русски — на подпись уходит
только ASCII.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Префикс сети в подписываемом сообщении задан кошельками, а не нами: Electrum,
# Bitcoin Core, Sparrow, BlueWallet, Trezor подставляют именно эти строки.
MAGIC = {
    "BTC": b"Bitcoin Signed Message:\n",
    "LTC": b"Litecoin Signed Message:\n",
}

# Версии Base58 по типам адреса. Держим отдельно от `core.address` (там они
# слиты в один набор «валидный адрес валюты»), потому что здесь нужно знать
# ИМЕННО тип: у P2PKH и P2SH из одного ключа получаются разные хеши.
_P2PKH_VERSION = {"BTC": 0x00, "LTC": 0x30}
_P2SH_VERSION = {"BTC": 0x05, "LTC": 0x32}
_HRP = {"BTC": "bc", "LTC": "ltc"}

_REASONS = {
    "ok": "Владение адресом подтверждено.",
    "not_configured": "Проверка подписи временно недоступна.",
    "bad_request": "Запрос неполный.",
    "bad_currency": "Для этой монеты подпись сообщения не поддерживается.",
    "bad_address": "Адрес не проходит проверку — сверьте символы.",
    "unsupported_address": "Этот тип адреса подписью подтвердить нельзя — "
                           "используйте адрес, начинающийся с 1/3/bc1q (L/M/ltc1q).",
    "bad_payload": "Код проверки не наш или испорчен — начните заново.",
    "payload_expired": "Код проверки истёк — начните заново.",
    "payload_alien": "Код проверки выдан другому клиенту.",
    "bad_signature": "Подпись не разобрана — скопируйте её целиком.",
    "not_owner": "Подпись верна, но сделана ключом от другого адреса.",
}


def reason_text(code: str) -> str:
    return _REASONS.get(code, "Подтвердить владение не удалось.")


def recovery_available() -> bool:
    """Есть ли чем восстановить ключ из подписи (coincurve).

    Проверяется отдельно и заранее, потому что отсутствие библиотеки выглядит
    как ошибка КЛИЕНТА: восстановление молча не удаётся, и вердикт получается
    «подпись не разобрана — скопируйте её целиком». Человек будет заново
    копировать безупречную подпись, пока не сдастся. Нашёл codex.
    """
    try:
        from coincurve import PublicKey            # noqa: F401
        return True
    except Exception as e:
        logger.warning("sig_proof: восстановление ключа недоступно (%s) — "
                       "подтверждение адреса подписью выключено", e)
        return False


def currencies() -> set:
    """Монеты, для которых доказательство подписью включено. Источник — реестр
    `core.assets`, чтобы список во фронте не разошёлся с проверкой на сервере.

    Пустой набор, если движка восстановления ключа нет: обещать подтверждение,
    которое заведомо не состоится, хуже, чем не показывать форму совсем.

    Монеты с тегом отсюда вычёркиваются, даже если их впишут в реестр: их
    назначение живёт СКЛЕЕННОЙ строкой (`UQ…#memo`, X-адрес XRPL), а подписью
    подтверждается голый адрес. Приняв склейку, мы вписали бы её в текст на
    подпись — и не сошлось бы ни у одного честного кошелька, зато выглядело бы
    как «ваш кошелёк не тот».
    """
    if not recovery_available():
        return set()
    try:
        from core import assets as _assets
        return {c for c in _assets.SIGNED_MESSAGE_CURRENCIES
                if c not in getattr(_assets, "TAGGED_CURRENCIES", {})}
    except Exception as e:
        logger.warning("sig_proof: реестр монет недоступен: %s", e)
        return set()


def challenge(subject: Any) -> Optional[str]:
    """Одноразовый код для клиента. None — сервер не настроен (нет RELAY_SECRET)."""
    try:
        from core import tonconnect as _tc
        return _tc.make_payload(subject)
    except Exception as e:
        logger.warning("sig_proof: код не выдан: %s", e)
        return None


def message_for(currency: str, address: str, payload: str) -> Optional[str]:
    """Ровно тот текст, который подписывает кошелёк.

    Одна функция на показ и на проверку — намеренно. Если бы поверхность
    показывала свой вариант, а сервер собирал свой, расхождение в один пробел
    давало бы «подпись неверна» на честном кошельке, и отличить это от подделки
    было бы нечем.
    """
    cur = str(currency or "").strip().upper()
    addr = str(address or "").strip()
    code = str(payload or "").strip()
    if cur not in MAGIC or not addr or not code:
        return None
    return ("ObsidianExchange address proof\n"
            f"currency: {cur}\n"
            f"address: {addr}\n"
            f"code: {code}\n"
            "This signature proves ownership only. It moves no funds.")


def prepare(currency: str, address: str, subject: Any) -> Dict[str, Any]:
    """Всё, что нужно поверхности для шага «подпишите текст»:
    {'ok', 'reason', 'error', 'message', 'payload', 'currency', 'address'}.
    `message` — только текст НА ПОДПИСЬ и только при `ok`; человеческая причина
    отказа лежит в `error`. Одно поле на то и другое читалось бы поверхностью
    как текст для кошелька — клиент подписал бы «Адрес не проходит проверку».

    Единственная точка входа для бота, сайта и Mini App — намеренно. Проверка
    адреса здесь ГОЛАЯ (`validate_address`, не `validate_destination`): на
    подпись идёт адрес, а не назначение перевода, и склейка с тегом здесь
    именно ошибка. Поверхностям такое различие доверять нельзя — они обязаны
    проверять назначение целиком, поэтому решение принимается тут.
    """
    cur = str(currency or "").strip().upper()
    addr = str(address or "").strip()
    if cur not in currencies():
        return {"ok": False, "reason": "bad_currency",
                "error": reason_text("bad_currency")}
    try:
        from core import assets as _assets
        good = _assets.validate_address(cur, addr)
    except Exception as e:
        logger.warning("sig_proof: проверка адреса недоступна: %s", e)
        good = False
    if not good:
        return {"ok": False, "reason": "bad_address",
                "error": reason_text("bad_address")}
    payload = challenge(subject)
    message = message_for(cur, addr, payload) if payload else None
    if not message:
        return {"ok": False, "reason": "not_configured",
                "error": reason_text("not_configured")}
    return {"ok": True, "reason": "ok", "message": message, "payload": payload,
            "currency": cur, "address": addr}


def _hash160(data: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()


def _varint(n: int) -> bytes:
    if n < 0xFD:
        return bytes([n])
    if n <= 0xFFFF:
        return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xFFFFFFFF:
        return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def message_digest(currency: str, message: str) -> Optional[bytes]:
    """Двойной SHA-256 от сообщения в обёртке кошельков. None — монета чужая."""
    magic = MAGIC.get(str(currency or "").strip().upper())
    if magic is None:
        return None
    body = message.encode("utf-8")
    blob = _varint(len(magic)) + magic + _varint(len(body)) + body
    return hashlib.sha256(hashlib.sha256(blob).digest()).digest()


def _address_targets(currency: str, address: str):
    """(тип, хеш160) заявленного адреса или (None, None).

    Тип нужен, чтобы сравнивать с тем же преобразованием ключа: один и тот же
    ключ даёт разные хеши для P2PKH, P2SH-P2WPKH и P2WPKH.
    """
    cur = str(currency or "").strip().upper()
    addr = str(address or "").strip()
    if cur not in MAGIC or not addr:
        return (None, None)
    try:
        from core import address as _addr
    except Exception as e:
        logger.warning("sig_proof: разбор адресов недоступен: %s", e)
        return (None, None)
    try:
        if addr.lower().startswith(_HRP[cur] + "1"):
            ver, prog = _addr.segwit_decode(_HRP[cur], addr)
            # Только v0 длиной 20 байт — это P2WPKH, единственный segwit-тип,
            # чей хеш выводится из одного публичного ключа. Taproot (v1) и
            # P2WSH (v0/32) подписью сообщения не подтверждаются: у них за
            # адресом стоит не ключ. Честный отказ лучше вечного «не совпало».
            if ver == 0 and prog and len(prog) == 20:
                return ("p2wpkh", bytes(prog))
            return (None, None)
        payload = _addr.b58check_decode(addr)
        if not payload or len(payload) != 21:
            return (None, None)
        if payload[0] == _P2PKH_VERSION[cur]:
            return ("p2pkh", payload[1:])
        if payload[0] == _P2SH_VERSION[cur]:
            return ("p2sh", payload[1:])
    except Exception as e:
        logger.warning("sig_proof: адрес не разобран: %s", e)
    return (None, None)


def _recover_keys(signature: str, digest: bytes) -> list:
    """Публичные ключи, которыми МОГЛА быть сделана эта подпись, или [].

    Заголовочный байт по BIP-137 кодирует и тип адреса, и сжатие ключа, но
    кошельки в этом расходятся: Electrum подписывает segwit-адреса заголовком
    от P2PKH. Поэтому из заголовка берём только номер восстановления, а тип
    проверяем по совпадению хешей — оно и есть доказательство. Требовать
    «правильный» заголовок значило бы отвергать подписи популярных кошельков.
    """
    raw = "".join(str(signature or "").split())
    if not raw:
        return []
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception:
        return []
    if len(blob) != 65:
        return []
    header = blob[0]
    if header < 27 or header > 42:
        return []
    recid = (header - 27) & 3
    try:
        from coincurve import PublicKey
    except Exception as e:
        logger.warning("sig_proof: восстановление ключа недоступно: %s", e)
        return []
    try:
        # coincurve ждёт compact-подпись r||s||recid, у кошельков recid идёт
        # первым байтом заголовка — переставляем.
        pub = PublicKey.from_signature_and_message(blob[1:] + bytes([recid]),
                                                   digest, hasher=None)
    except Exception:
        return []
    try:
        return [pub.format(compressed=True), pub.format(compressed=False)]
    except Exception:
        return []


def _verdict(reason: str, address: str = None, **extra) -> Dict[str, Any]:
    v = {"verified": reason == "ok", "reason": reason,
         "message": reason_text(reason), "address": address}
    v.update(extra)
    return v


def verify(currency: str, address: str, payload: str, signature: str, *,
           subject: Any, now: float = None) -> Dict[str, Any]:
    """Вердикт о владении: {'verified','reason','message','address'}.

    Положительный вердикт возможен единственным путём — восстановленный из
    подписи ключ даёт ровно тот адрес, который назвал клиент, а код проверки
    наш, свежий и выдан ему же. Сообщение собирается здесь (см. шапку), поэтому
    подменить подписанный текст нечем.
    """
    cur = str(currency or "").strip().upper()
    addr = str(address or "").strip()
    if not cur or not addr or not payload or not signature:
        return _verdict("bad_request", addr)
    if cur not in MAGIC or cur not in currencies():
        return _verdict("bad_currency", addr)

    # Контрольная сумма адреса — до всякой криптографии: на испорченном адресе
    # подпись не сойдётся никогда, а клиент должен услышать «сверьте символы»,
    # а не «ключ не тот».
    try:
        from core import assets as _assets
        if not _assets.validate_address(cur, addr):
            return _verdict("bad_address", addr)
    except Exception as e:
        logger.warning("sig_proof: проверка адреса недоступна: %s", e)
        return _verdict("bad_address", addr)

    try:
        from core import tonconnect as _tc
        bad = _tc.check_payload(payload, subject, now=now)
    except Exception as e:
        logger.warning("sig_proof: код не проверен: %s", e)
        return _verdict("not_configured", addr)
    if bad:
        return _verdict(bad if bad in _REASONS else "bad_payload", addr)

    kind, target = _address_targets(cur, addr)
    if not kind:
        return _verdict("unsupported_address", addr)

    message = message_for(cur, addr, payload)
    digest = message_digest(cur, message or "")
    if not message or not digest:
        return _verdict("bad_request", addr)

    keys = _recover_keys(signature, digest)
    if not keys:
        return _verdict("bad_signature", addr)

    for pub in keys:
        h160 = _hash160(pub)
        if kind == "p2pkh" and h160 == target:
            return _verdict("ok", addr)
        if kind == "p2wpkh" and len(pub) == 33 and h160 == target:
            # segwit-адрес выводится только из СЖАТОГО ключа; принять здесь
            # несжатый значило бы подтвердить адрес, которого у этого ключа нет.
            return _verdict("ok", addr)
        if kind == "p2sh" and len(pub) == 33 and _hash160(b"\x00\x14" + h160) == target:
            return _verdict("ok", addr)
    return _verdict("not_owner", addr)
