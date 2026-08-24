"""Отправка из подключённого кошелька: счёт выставляет сервер, подпись ставит клиент.

Третий шаг некастодиального кошелька (этап 3 бэклога). Первые два только
показывали — баланс и историю. Этот даёт действие, и потому здесь же лежит
главное ограничение всего трека: **ключа у нас нет и появиться он не может**.
Модуль не подписывает, не хранит секретов и не умеет отправить ничего сам. Он
собирает ЗАПРОС на перевод, который клиент подтверждает в своём кошельке.

Что здесь фиксирует сервер и почему это важно. Получателя, сумму и метку
платежа берём ИЗ ЗАЯВКИ в базе, а не из тела запроса. Принять их от клиента
значило бы построить у себя удобную кнопку «отправь куда скажут»: страница
Mini App живёт в Telegram, выглядит нашей, и перевод из неё клиент считает
нашим — то есть чужой адрес в такой кнопке стал бы фишингом от нашего имени.
Единственное, что приходит от клиента, — номер СВОЕЙ заявки, и он проверяется
на принадлежность.

Метка платежа (комментарий). Адрес приёма один на всех, поэтому депозит
привязывается к заявке двумя независимыми признаками: текстовой меткой внутри
перевода и адресом отправителя, доказанным подписью при подключении кошелька
(`core.wallet_link`). Второй признак сильнее — его нельзя перепутать, скопировав
чужой комментарий, — но он есть только у подключённого кошелька; первый работает
и при переводе руками. Намерение записывается ДО подписи: клиент может закрыть
кошелёк, а монеты уже уйдут.

⚠️ Подпись в кошельке — не поступление денег. Кошелёк возвращает подписанное
сообщение, а не подтверждение сети: перевод может не долететь, не пройти по
балансу, быть отменён. Поэтому `ack` фиксирует «клиент подписал», и ничего
больше; заявку закрывает только проверка блокчейна (`bot/sell_guard.py`).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import time
from repositories.wallet_store import from_environment as _wallet_store_from_environment
from repositories.sell_order_store import from_environment as _sell_store_from_environment
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

CHAIN = "TON"
MAINNET = "-239"                 # id основной сети TON в TON Connect
REQUEST_TTL_SEC = 300            # окно жизни запроса на подпись
NANO = 10 ** 9
COMMENT_MAX_BYTES = 100          # метка короткая — она умещается в одну ячейку

REASON_TEXT = {
    "ok": "Готово к подписи",
    "not_connected": "Кошелёк не подключён — подключите его в профиле",
    "not_found": "Заявка не найдена",               # и чужая — тоже «не найдена»
    "wrong_currency": "Эта заявка не в TON",
    "not_pending": "Заявка уже не ждёт перевода",
    "no_address": "У заявки не сохранён адрес приёма",
    "bad_address": "Адрес приёма испорчен — напишите в поддержку",
    "bad_amount": "Некорректная сумма перевода",
    "bad_destination": "Адрес получателя не прошёл проверку — сверьте его посимвольно",
    "bad_comment": "Комментарий слишком длинный или содержит перевод строки",
    "unavailable": "Сейчас не получилось — попробуйте позже",
}


def reason_text(code: str) -> str:
    return REASON_TEXT.get(code, "Не удалось подготовить перевод")


# ── CRC32C (Castagnoli) ──────────────────────────────────────────────────────
# Нужен для контрольной суммы BOC. Стандартный zlib.crc32 — ДРУГОЙ полином
# (0xEDB88320); подменить один другим значит собрать сообщение, которое кошелёк
# отвергнет. Проверочное значение полинома: crc32c(b"123456789") == 0xE3069283.
_CRC32C_POLY = 0x82F63B78


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (_CRC32C_POLY if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


# ── текстовый комментарий как BOC ────────────────────────────────────────────
def text_comment_boc(text: str) -> str:
    """Комментарий к переводу в том виде, в каком его ждёт TON Connect: base64 BOC.

    Ячейка комментария по TEP-74: 32 нулевых бита (код операции «текст») и
    следом UTF-8. Собираем вручную, потому что в окружении нет ни одной
    библиотеки TON, а тянуть её в боевой venv ради четырнадцати байт метки —
    менять прод под мелочь. Раскладка BOC взята из спецификации и проверена
    разбором обратно в тесте: ошибка здесь не «подписалось не то», а «кошелёк
    отказался», но разбирать такой отказ пришлось бы по скриншоту клиента.
    """
    payload = str(text or "").encode("utf-8")
    if len(payload) > COMMENT_MAX_BYTES:
        raise ValueError(f"комментарий длиннее {COMMENT_MAX_BYTES} байт")
    data = b"\x00\x00\x00\x00" + payload          # op=0 + текст
    # Дескрипторы ячейки: ссылок нет, данные выровнены по байту.
    cell = bytes([0x00, 2 * len(data)]) + data
    header = (b"\xb5\xee\x9c\x72"                 # магия BOC
              + bytes([0x41])                     # есть crc32c, размер индекса 1 байт
              + bytes([0x01])                     # байт под смещение
              + bytes([0x01])                     # ячеек — одна
              + bytes([0x01])                     # корней — один
              + bytes([0x00])                     # отсутствующих нет
              + bytes([len(cell)])                # суммарный размер ячеек
              + bytes([0x00]))                    # индекс корня
    boc = header + cell
    boc += crc32c(boc).to_bytes(4, "little")
    return base64.b64encode(boc).decode()


# ── метка платежа ────────────────────────────────────────────────────────────
def marker_for(sell_id) -> str:
    """Метка заявки для комментария к переводу: `OE-<номер>` (+ подпись, если есть
    RELAY_SECRET). Детерминирована: проверяющий считает ту же строку заново, а не
    ищет «что-нибудь похожее» в чужом комментарии."""
    try:
        sid = int(sell_id)
    except (TypeError, ValueError):
        return ""
    if sid <= 0:
        return ""
    secret = (os.getenv("RELAY_SECRET") or "").strip()
    base = f"OE-{sid}"
    if not secret or secret == "fallback":
        return base
    tag = hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()[:6]
    return f"{base}-{tag}"


def comment_matches(comment: Any, sell_id) -> bool:
    """Есть ли в комментарии перевода метка ИМЕННО этой заявки.

    Метка ищется как ЦЕЛЫЙ токен, а не подстрока: «OE-12» лежит внутри «OE-123»,
    и подстрочное сравнение привязало бы депозит заявки №123 к заявке №12 —
    рубли ушли бы не тому клиенту. Нашёл codex; без подписи (RELAY_SECRET не
    задан) метки как раз такого вида.
    """
    marker = marker_for(sell_id)
    if not marker:
        return False
    return re.search(r"(?<![0-9A-Za-z_-])" + re.escape(marker) + r"(?![0-9A-Za-z_-])",
                     str(comment or ""), re.IGNORECASE) is not None


# ── журнал намерений ─────────────────────────────────────────────────────────
def _store():return _wallet_store_from_environment(sqlite_path=DB_PATH)
def _sell_store():return _sell_store_from_environment(sqlite_path=DB_PATH)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def remember_intent(user_id, sell_id, from_address: str, to_address: str,
                    amount: float, marker: str) -> Optional[int]:
    """Записать намерение перевести ДО того, как клиент подпишет.

    Порядок именно такой: между показом кошелька и приходом монет мы можем не
    узнать ничего (клиент закроет Mini App, сеть оборвётся), а монеты уже уйдут.
    Ненаступившее намерение безвредно — оно лишь помогает узнать отправителя;
    пропущенное означает депозит, который не к чему привязать.
    """
    try:
        return _store().remember_intent(user_id=int(user_id),chain=CHAIN,sell_id=int(sell_id),
            from_address=str(from_address),to_address=str(to_address),amount=float(amount),
            marker=str(marker),created_at=_now_iso())
    except Exception as e:
        logger.warning("wallet_send: не записали намерение uid=%s sell=%s: %s",
                       user_id, sell_id, e)
        return None


def mark_signed(user_id, sell_id) -> bool:
    """Клиент сообщил, что подписал. Это НЕ поступление денег — только отметка
    времени, чтобы поверхности могли сказать «ждём сеть» вместо молчания."""
    try:
        return _store().mark_signed(user_id=int(user_id),sell_id=int(sell_id),signed_at=_now_iso())
    except Exception as e:
        logger.warning("wallet_send: не отметили подпись uid=%s sell=%s: %s",
                       user_id, sell_id, e)
        return False


def intents_for_order(sell_id) -> List[Dict[str, Any]]:
    try:
        return _store().intents_for(int(sell_id))
    except Exception as e:
        logger.warning("wallet_send: не прочитали намерения sell=%s: %s", sell_id, e)
        return []


def same_account(a: str, b: str) -> bool:
    """Один ли это счёт TON. Сравнивать СТРОКИ нельзя: один и тот же счёт живёт
    в трёх видах записи (raw `0:…`, дружественный UQ…, bounceable EQ…), а
    обозреватель отдаёт отправителя в raw, тогда как подпись подключения дала
    нам дружественный вид. Сравнение строк не «иногда ошибётся» — оно не
    совпадёт НИКОГДА, то есть привязка тихо перестанет работать."""
    from core.address import ton_account_key
    ka, kb = ton_account_key(a), ton_account_key(b)
    return bool(ka) and ka == kb


def senders_for_order(sell_id) -> set:
    """Адреса, с которых клиент собирался платить по этой заявке. Пустое
    множество — не «никто не платил», а «доказанного отправителя нет»."""
    return {i["from_address"] for i in intents_for_order(sell_id) if i["from_address"]}


# ── подготовка перевода ──────────────────────────────────────────────────────
def _verdict(reason: str, **extra) -> Dict[str, Any]:
    out = {"ok": reason == "ok", "reason": reason, "message": reason_text(reason)}
    out.update(extra)
    return out


def to_nano(amount) -> Optional[int]:
    """TON в нанотоны без плавающей арифметики: 0.1 в float — не 0.1."""
    try:
        nano = (Decimal(str(amount)) * NANO).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except Exception:
        return None
    n = int(nano)
    return n if n > 0 else None


def _sell_row(sell_id):
    return _sell_store().get(int(sell_id))


def pending_sells(user_id, currency: str = CHAIN) -> List[Dict[str, Any]]:
    """Заявки клиента, ждущие перевода монет. Список СВОИХ: user_id приходит из
    подписанного initData, а не из запроса."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return []
    try:
        rows = _sell_store().pending_for_user(
            user_id=uid, currency=(currency or CHAIN).upper(), limit=10)
    except Exception as e:
        logger.warning("wallet_send: не прочитали заявки продажи uid=%s: %s", user_id, e)
        return []
    return [{"sell_id": r["id"], "currency": r["currency"],
             "amount": float(r["crypto_amount"] or 0),
             "rub_amount": float(r["rub_amount"] or 0),
             "address": r["receive_address"] or "",
             "marker": marker_for(r["id"]),
             "created_at": r["created_at"]} for r in rows]


def build_transfer(user_id, to, amount, comment: str = "", *,
                   now: float = None, ttl: int = REQUEST_TTL_SEC) -> Dict[str, Any]:
    """Свободный перевод из кошелька клиента: получателя выбирает ОН.

    Отличие от build_request принципиальное, и его нельзя стирать. Там счёт
    выставляет сервер, и клиенту незачем знать адрес: он платит нам по заявке.
    Здесь наоборот — это его кошелёк и его деньги, мы лишь собираем сообщение и
    отдаём кошельку на подпись. Поэтому наша работа тут другая: проверить адрес
    контрольной суммой (опечатка в адресе TON не лечится ничем — перевод уходит
    в никуда) и не дать перепутать «перевод по заявке» с «переводом кому угодно».

    Ответ помечен `client_chosen: True` — по нему поверхность обязана показать
    адрес получателя целиком, а не «оплатить заявку №…».
    """
    from core import wallet_link as _wl
    from core.address import is_valid_ton, is_valid_ton_memo, ton_friendly_address

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return _verdict("not_connected")

    from_address = _wl.address_for(uid, CHAIN)
    if not from_address:
        return _verdict("not_connected")

    dest = str(to or "").strip()
    if not is_valid_ton(dest):
        # Контрольная сумма, а не «похоже на адрес»: у TON опечатка проходит
        # глазами и не проходит по чек-сумме — это последняя защита клиента.
        return _verdict("bad_destination")

    nano = to_nano(amount)
    if nano is None:
        return _verdict("bad_amount")

    memo = str(comment or "")
    if not is_valid_ton_memo(memo):
        return _verdict("bad_comment")
    payload = None
    if memo:
        try:
            payload = text_comment_boc(memo)
        except ValueError:
            return _verdict("bad_comment")

    message = {"address": ton_friendly_address(dest) or dest, "amount": str(nano)}
    if payload:
        message["payload"] = payload
    return _verdict(
        "ok",
        client_chosen=True,
        amount=float(Decimal(str(nano)) / NANO),
        address=message["address"],
        comment=memo,
        from_address=from_address,
        request={
            "validUntil": int((now or time.time())) + int(ttl),
            "network": MAINNET,
            "messages": [message],
        },
    )


def build_request(user_id, sell_id, *, now: float = None,
                  ttl: int = REQUEST_TTL_SEC, remember: bool = True) -> Dict[str, Any]:
    """Запрос на перевод для кошелька клиента.

    Получатель, сумма и метка — из заявки; из запроса приходит только её номер.
    Владение проверяется до всего остального: чужая заявка неотличима от
    несуществующей, иначе перебор номеров рассказал бы, какие из них живые.
    """
    from core import wallet_link as _wl
    from core.address import parse_ton_address

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return _verdict("not_found")
    try:
        sid = int(sell_id)
    except (TypeError, ValueError):
        return _verdict("not_found")

    try:
        row = _sell_row(sid)
    except Exception as e:
        logger.warning("wallet_send: не прочитали заявку %s: %s", sid, e)
        return _verdict("unavailable")
    if not row:
        return _verdict("not_found")
    if int(row["user_id"] or 0) != uid:
        # Отдельного кода отказа НЕТ намеренно: он ушёл бы клиенту в ответе и
        # перебором номеров рассказал бы, какие заявки существуют. В журнал —
        # подробно, наружу — то же самое, что про несуществующую.
        logger.warning("wallet_send: uid=%s просит чужую заявку %s", uid, sid)
        return _verdict("not_found")
    if str(row["currency"] or "").upper() != CHAIN:
        return _verdict("wrong_currency")
    if str(row["status"] or "").lower() != "pending":
        return _verdict("not_pending")

    to_address = str(row["receive_address"] or "").strip()
    if not to_address:
        return _verdict("no_address")
    if parse_ton_address(to_address)[0] is None:
        # Адрес приёма испорчен — молчать нельзя: перевод ушёл бы в никуда.
        return _verdict("bad_address")

    amount = float(row["crypto_amount"] or 0)
    nano = to_nano(amount)
    if nano is None:
        return _verdict("bad_amount")

    # Отправитель обязан быть доказанным: на нём держится привязка депозита к
    # заявке, а доказательство даёт только подпись при подключении кошелька.
    from_address = _wl.address_for(uid, CHAIN)
    if not from_address:
        return _verdict("not_connected")

    marker = marker_for(sid)
    try:
        payload = text_comment_boc(marker)
    except ValueError as e:
        logger.error("wallet_send: метка не собралась для заявки %s: %s", sid, e)
        return _verdict("unavailable")

    if remember:
        remember_intent(uid, sid, from_address, to_address, amount, marker)

    valid_until = int((now or time.time())) + int(ttl)
    return _verdict(
        "ok",
        sell_id=sid,
        amount=amount,
        rub_amount=float(row["rub_amount"] or 0),
        marker=marker,
        address=to_address,
        from_address=from_address,
        request={
            "validUntil": valid_until,
            "network": MAINNET,
            "messages": [{"address": to_address, "amount": str(nano), "payload": payload}],
        },
    )
