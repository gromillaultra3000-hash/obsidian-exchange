"""Единая доставка чека клиента провайдеру.

Зачем. Доказательство оплаты писалось под каждого провайдера отдельно и прямо
в обработчиках бота: Montera умела (upload_additional_info / upload_receipt),
Brabus частично (confirm_transfer), у остальных канала не было ВООБЩЕ. У Vertu
эндпоинт /v1/wt_receipts/ существовал с самого начала, но реализован не был —
20.07.2026 из-за этого потеряна заявка 99955056 на 30 000 ₽: клиент заплатил,
подтвердить было нечем, сделка ушла в Declined.

Здесь один вход: send_receipt(order_id, ...). Он сам находит, через какого
провайдера шла оплата, и отдаёт файл в его канал. Новый провайдер добавляется
одной записью в _ROUTES, а не правкой обработчиков бота.

Принцип: если канала нет — говорим об этом прямо (ok=False, reason='unsupported').
Молчаливое «чек принят» там, где он никуда не ушёл, — худший из возможных
исходов: клиент спокоен, деньги теряются.
"""
from __future__ import annotations
import ast
import hashlib
import logging
import os
import sqlite3
import sys

import requests

# путь к relay — от себя, а не от боевого каталога (мина «зашитый боевой путь»)
_RELAY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RELAY not in sys.path:
    sys.path.insert(0, _RELAY)

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

PDF = "application/pdf"


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def find_session(order_id) -> dict | None:
    """Последняя платёжная сессия заявки: через кого и по какой сделке платили."""
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT provider, provider_invoice_id, provider_payload, status "
                "FROM payment_sessions WHERE order_id=? ORDER BY id DESC LIMIT 1",
                (order_id,)).fetchone()
    except Exception as e:
        logger.warning("receipts: чтение сессии order=%s: %s", order_id, e)
        return None
    if not row:
        return None
    raw = {}
    payload = row["provider_payload"]
    if payload:
        # исторически payload писался и как JSON, и как repr(dict) — читаем оба
        try:
            import json
            raw = json.loads(payload)
        except Exception:
            try:
                raw = ast.literal_eval(payload)
            except Exception:
                raw = {}
    # provider в сессии бывает с вариантом через двоеточие ('brabus:vietqr',
    # 'brabus:tbank_deeplink'). Для маршрутизации нужен базовый ключ, иначе
    # _ROUTES/_DISPUTES.get() не находит обработчик и чек/спор молча теряется.
    # Вариант сохраняем отдельно — он нужен Brabus, чтобы найти нужный API-ключ.
    prov_full = (row["provider"] or "").lower()
    prov_base, _, prov_variant = prov_full.partition(":")
    return {"provider": prov_base,
            "provider_full": prov_full,
            "variant": prov_variant,
            "invoice_id": row["provider_invoice_id"],
            "status": row["status"],
            "raw": raw if isinstance(raw, dict) else {}}


# ── каналы провайдеров ────────────────────────────────────────────────────────

def _montera(sess, file_bytes, filename, content_type):
    """У Montera рабочего API-канала приёма чека НЕТ (проверено 23.07.2026).

    Маршрут /h2h/order/{id}/additional-info отвечает 404 «route could not be
    found» — и на обычных заявках, и на тех, где трейдер сам запрашивал
    верификацию. Это ошибка роутинга, а не состояния сделки. Второй путь
    (receipt_upload_url) не работал никогда: такого поля у Montera нет, мы
    читали несуществующий ключ и всегда получали None.

    Пока Montera не даст верный эндпоинт, честный исход — отдать чек оператору,
    а не делать вид, что доказательство ушло партнёру.
    """
    url = (sess["raw"] or {}).get("client_receipt_url") \
        or (sess["raw"] or {}).get("receipt_upload_url")
    api_res = {}
    if content_type == PDF and url:
        # Ссылка появляется, только если Montera сама её выдала — пробуем.
        from providers.montera import MonteraProvider
        api_res = MonteraProvider().upload_receipt(url, file_bytes, filename) or {}
        if api_res.get("ok"):
            return {"ok": True, "raw": {"api": api_res}}
    # API-канала нет ни для чека (receipt), ни для видео-верификации
    # (additional-info = 404) — единственный путь к Montera это группа споров.
    # Форвардим и PDF, и видео (трейдер иногда просит именно видео).
    chat_res = _send_to_dispute_chat(
        "Montera", DISPUTE_CHATS.get("montera"), sess["invoice_id"],
        file_bytes, filename, content_type=content_type)
    if chat_res.get("ok"):
        return {"ok": True, "raw": {"api": api_res, "chat": chat_res}}
    return {"ok": False, "reason": "unsupported",
            "error": "Montera не принимает чеки через API — файл сохранён, "
                     "оператору нужно приложить его в кабинете Montera",
            "raw": {"api": api_res, "chat": chat_res}}


# Telegram-группы споров по провайдерам: их бот/оператор принимает PDF-чек и
# привязывает его к сделке по ID в подписи. Нужны там, где у провайдера НЕТ
# надёжного API-канала приёма чека: Vertu (штатный /v1/wt_receipts/ иногда
# принимает чек, но не проталкивает трейдеру, external_sync_success=false),
# Montera (API-канала нет вовсе) и XPay по ссылочным/побанковским методам.
# Chat ID берётся из окружения; пусто = группы нет, тогда чек держим у оператора
# и НЕ врём клиенту «ушло провайдеру». Бот должен быть участником группы.
DISPUTE_CHATS = {
    "vertu": os.getenv("VERTU_DISPUTE_CHAT_ID", "-5527649225"),
    "montera": os.getenv("MONTERA_DISPUTE_CHAT_ID", ""),
    "xpay": os.getenv("XPAY_DISPUTE_CHAT_ID", ""),
}


def _send_to_dispute_chat(provider_label, chat_id, deal_key, file_bytes, filename,
                          extra_lines=None, content_type=PDF) -> dict:
    """Шлёт чек/видео-верификацию в Telegram-группу споров провайдера нашим ботом.

    Поддерживает PDF-чек и видео (трейдер Montera иногда просит именно видео, а
    API-канала additional-info у Montera нет — группа единственный путь).
    reason='no_chat' — группа для этого провайдера не настроена (это не сбой,
    просто канала нет): вызывающий трактует как «доставить не удалось».
    """
    if not chat_id:
        return {"ok": False, "reason": "no_chat",
                "error": f"группа споров {provider_label} не настроена"}
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "BOT_TOKEN не задан — дубль в группу споров невозможен"}
    is_video = bool(content_type) and "video" in content_type
    head = "🎥 Видео-верификация" if is_video else "🧾 Чек оплаты"
    caption = f"{head} {provider_label}\nСделка: {deal_key}"
    for ln in (extra_lines or []):
        caption += f"\n{ln}"
    method, field = ("sendVideo", "video") if is_video else ("sendDocument", "document")
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            data={"chat_id": chat_id, "caption": caption},
            files={field: (filename, file_bytes, content_type or PDF)},
            timeout=90 if is_video else 30,
        )
        ok = r.status_code == 200 and (r.json() or {}).get("ok")
        if not ok:
            logger.warning("receipts: не ушло в группу споров %s: %s %s",
                           provider_label, r.status_code, r.text[:200])
        return {"ok": bool(ok),
                "error": None if ok else f"TG {r.status_code}: {r.text[:150]}"}
    except Exception as e:
        logger.warning("receipts: отправка в группу споров %s: %s", provider_label, e)
        return {"ok": False, "error": str(e)}


def _vertu(sess, file_bytes, filename, content_type):
    from providers.vertu import VertuProvider
    if content_type != PDF:
        # Текст уходит клиенту как есть — он должен понять, что делать дальше.
        # Прежнее «Vertu принимает только PDF-чек» звучало как отказ системы,
        # клиент не догадывался переслать PDF (22.07, order 99955079).
        return {"ok": False,
                "error": "Нужен PDF-чек из банковского приложения — фото и "
                         "скриншоты платёжный партнёр не принимает. "
                         "Откройте операцию в банке → «Сохранить чек в PDF»."}
    raw = sess["raw"] or {}
    # platform_id (0084-…), а не наш deal_id — именно он ключ сделки у Vertu
    pid = raw.get("platform_id") or sess["invoice_id"]
    deal_id = raw.get("deal_id")
    # 1. Штатный API-канал.
    api_res = VertuProvider().upload_receipt(pid, file_bytes, filename) or {}
    # 2. Всегда дублируем в группу споров Vertu.
    chat_res = _send_to_dispute_chat(
        "Vertu", DISPUTE_CHATS.get("vertu"), pid, file_bytes, filename,
        extra_lines=[f"deal_id: {deal_id}"] if (deal_id and deal_id != pid) else None)
    # Успех — если чек достиг стороны Vertu ЛЮБЫМ путём: API протолкнул трейдеру
    # ИЛИ файл лёг в их группу споров. Иначе — честный отказ, без «принято».
    if api_res.get("ok") or chat_res.get("ok"):
        return {"ok": True, "raw": {"api": api_res, "chat": chat_res}}
    return {"ok": False,
            "error": api_res.get("error") or chat_res.get("error")
                     or "Vertu: чек не доставлен ни по API, ни в группу споров",
            "raw": {"api": api_res, "chat": chat_res}}


def _brabus(sess, file_bytes, filename, content_type):
    from providers.brabus import BrabusProvider
    # Вариант (=API-ключ), которым создавали инвойс, — если он записан в сессии.
    # Иначе перебираем ключи: инвойс виден только «своему» ключу.
    hint = (sess["raw"] or {}).get("variant") or sess.get("variant") or ""
    return BrabusProvider.confirm_transfer_any(
        sess["invoice_id"], file_bytes, filename, variant_hint=hint)


def _stormtrade(sess, file_bytes, filename, content_type):
    from providers.stormtrade import StormTradeProvider
    return StormTradeProvider().confirm_transfer(
        sess["invoice_id"], file_bytes, filename)


# У XPay приём чека привязан к методу оплаты, а не к ордеру: по доке
# /merchant/receipt/upload обслуживает ТОЛЬКО card_pdf и sbp_pdf. Для прочих
# методов (у нас это tbank/sber/… — ссылочные трансграничные рельсы) эндпоинт
# отвечает «Only PDF, JPEG or PNG files are allowed» — сообщение уводит в
# сторону файла, хотя дело в методе (22.07, order 99955082: файл был корректным
# JPEG). Не дёргаем впустую и сразу говорим правду оператору.
_XPAY_RECEIPT_METHODS = {"card_pdf", "sbp_pdf"}


def _xpay(sess, file_bytes, filename, content_type):
    from providers.xpayconnect import XPayConnectProvider
    method = ((sess["raw"] or {}).get("payment_details") or {}).get("type") or ""
    method = str(method).lower()
    if method and method not in _XPAY_RECEIPT_METHODS:
        # По этому методу API-приёма чека у XPay нет — пробуем группу споров,
        # если настроена; иначе честно к оператору (заявка уже удержана Слоем 0).
        chat_res = {}
        if content_type == PDF:
            chat_res = _send_to_dispute_chat(
                "XPay", DISPUTE_CHATS.get("xpay"), sess["invoice_id"],
                file_bytes, filename)
            if chat_res.get("ok"):
                return {"ok": True, "raw": {"chat": chat_res}}
        return {"ok": False, "reason": "unsupported",
                "error": f"XPay принимает чеки только по методам card_pdf/sbp_pdf, "
                         f"а заявка создана методом «{method}» — чек нужно "
                         f"передать оператору вручную",
                "raw": {"chat": chat_res}}
    # XPay принимает как свой internal_id, так и наш external_id
    return XPayConnectProvider().upload_receipt(sess["invoice_id"], file_bytes, filename)


_ROUTES = {
    "montera": _montera,
    "vertu": _vertu,
    "brabus": _brabus,
    "fallback": _brabus,      # FallbackProvider — это Brabus в другом варианте
    "stormtrade": _stormtrade,
    "xpay": _xpay,
}

# У этих провайдеров канала приёма чека в API нет вовсе (проверено по докам).
# Держим списком отдельно от _ROUTES, чтобы отличать «не поддерживает» от
# «забыли реализовать» — второе должно быть заметно в логах.
# greenpay/lava/platega сейчас не в ротации (нет ключей / offline); если их
# будут включать — сначала сверить доку на канал чека, тест это потребует.
_NO_CHANNEL = {"greenpay", "lava", "platega"}


# ── Спор: последняя инстанция, когда чек отправлен, а сделку не подтвердили ───

def _dispute_stormtrade(sess, file_bytes, filename, reason, amount):
    from providers.stormtrade import StormTradeProvider
    deal_id = (sess["raw"] or {}).get("deal_id") or sess["invoice_id"]
    return StormTradeProvider().open_dispute(
        sess["invoice_id"], deal_id, file_bytes, reason, amount, filename)


def _dispute_brabus(sess, file_bytes, filename, reason, amount):
    from providers.brabus import BrabusProvider
    raw = sess["raw"] or {}
    deal_id = raw.get("deal_id") or sess["invoice_id"]
    return BrabusProvider.open_dispute_any(
        sess["invoice_id"], deal_id, file_bytes, reason, amount, filename,
        variant_hint=raw.get("variant") or sess.get("variant") or "")


_DISPUTES = {
    "stormtrade": _dispute_stormtrade,
    "brabus": _dispute_brabus,
    "fallback": _dispute_brabus,
}


def dispute_available(order_id) -> bool:
    sess = find_session(order_id)
    return bool(sess and sess["provider"] in _DISPUTES and sess["invoice_id"])


def open_dispute(order_id, file_bytes: bytes, filename: str = "receipt.pdf",
                 reason: str = "no_payment", amount=None) -> dict:
    """Оспорить неподтверждённую оплату у провайдера.

    Только для провайдеров, у которых спор есть в API. У Montera/Vertu/XPay
    его нет — там эскалация идёт через поддержку, и об этом надо говорить
    прямо, а не делать вид, что спор открыт.
    """
    sess = find_session(order_id)
    if not sess:
        return {"ok": False, "reason": "no_session", "error": "нет платёжной сессии"}
    handler = _DISPUTES.get(sess["provider"])
    if not handler:
        return {"ok": False, "provider": sess["provider"], "reason": "unsupported",
                "error": f"{sess['provider']}: спор через API не поддерживается, "
                         f"эскалация только через поддержку провайдера"}
    try:
        res = handler(sess, file_bytes, filename, reason, amount) or {}
    except Exception as e:
        logger.error("dispute: order=%s %s: %s", order_id, sess["provider"], e)
        return {"ok": False, "provider": sess["provider"], "reason": "exception",
                "error": f"{type(e).__name__}: {e}"}
    logger.info("dispute: order=%s provider=%s ok=%s", order_id, sess["provider"],
                bool(res.get("ok")))
    return {"ok": bool(res.get("ok")), "provider": sess["provider"],
            "error": res.get("error"), "raw": res.get("raw")}


# Провайдеры, которым чек отдаём ТОЛЬКО в PDF. Строже, чем требуют их API
# (Vertu — действительно только PDF; XPay формально берёт и JPEG/PNG, Montera —
# ещё и фото/видео), но это осознанное правило: PDF — единственный формат,
# который трейдер принимает без спора. 22.07.2026 два чека-фото не дошли ни до
# Vertu, ни до XPay, клиент остался без подтверждения (99955079, 99955082).
PDF_REQUIRED = {"montera", "vertu", "xpay"}


def requires_pdf(order_id) -> bool:
    """Нужен ли по этой заявке именно PDF (а фото — бесполезно)."""
    sess = find_session(order_id)
    return bool(sess and sess["provider"] in PDF_REQUIRED)


def channel_available(order_id) -> bool:
    sess = find_session(order_id)
    return bool(sess and sess["provider"] in _ROUTES and sess["invoice_id"])


def send_receipt(order_id, file_bytes: bytes, filename: str = "receipt.pdf",
                 content_type: str = PDF) -> dict:
    """Отправляет доказательство оплаты тому провайдеру, через которого платили.

    Возвращает {'ok': bool, 'provider': str, 'reason': str|None, 'error': str|None}.
    reason='unsupported' — у провайдера нет приёма чеков: чек нужно передать
    оператору руками, и клиенту нельзя говорить «принято».
    """
    # Сохраняем ДО отправки: файл нужен для спора независимо от того,
    # примет ли его API провайдера прямо сейчас
    store_receipt(order_id, file_bytes, filename, content_type)

    sess = find_session(order_id)
    if not sess:
        return {"ok": False, "provider": None, "reason": "no_session",
                "error": "не найдена платёжная сессия заявки"}

    provider = sess["provider"]
    handler = _ROUTES.get(provider)
    if not handler:
        logger.warning("receipts: order=%s провайдер %s без канала приёма чека",
                       order_id, provider)
        return {"ok": False, "provider": provider,
                "reason": "unsupported" if provider in _NO_CHANNEL else "unknown_provider",
                "error": f"{provider}: приём чеков не поддерживается провайдером"}
    if not sess["invoice_id"]:
        return {"ok": False, "provider": provider, "reason": "no_invoice",
                "error": "в сессии нет ID сделки провайдера"}

    try:
        res = handler(sess, file_bytes, filename, content_type) or {}
    except Exception as e:
        logger.error("receipts: order=%s provider=%s: %s", order_id, provider, e)
        return {"ok": False, "provider": provider, "reason": "exception",
                "error": f"{type(e).__name__}: {e}"}

    ok = bool(res.get("ok"))
    logger.info("receipts: order=%s provider=%s ok=%s %s", order_id, provider, ok,
                "" if ok else res.get("error", ""))
    if ok:
        _mark_sent(order_id)
    # Обработчик может сам объяснить характер отказа: 'unsupported' значит
    # «канала нет», и бот тогда мягко переводит клиента на оператора вместо
    # показа технической ошибки партнёра.
    return {"ok": ok, "provider": provider,
            "reason": None if ok else (res.get("reason") or "rejected"),
            "error": None if ok else res.get("error"), "raw": res.get("raw")}


RECEIPT_DIR = os.getenv("RECEIPT_DIR", "/root/receipts")


def store_receipt(order_id, file_bytes: bytes, filename: str, content_type: str) -> str | None:
    """Кладёт чек на диск, чтобы позже приложить его к спору.

    Без этого спор автоматом не открыть: файл жил только в памяти обработчика
    бота и в Telegram, а к моменту, когда становится ясно, что оплату не
    подтвердили, повторно просить его у клиента поздно и унизительно.
    """
    try:
        from pathlib import Path
        d = Path(RECEIPT_DIR)
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)          # чеки — персональные данные клиента
        ext = ".pdf" if content_type == PDF else (
            ".mp4" if "video" in content_type else ".jpg")
        p = d / f"{order_id}{ext}"
        p.write_bytes(file_bytes)
        os.chmod(p, 0o600)
        sha = hashlib.sha256(file_bytes).hexdigest()
        with _db() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS order_receipts (
                order_id INTEGER PRIMARY KEY, path TEXT, filename TEXT,
                content_type TEXT, created_at TEXT DEFAULT (datetime('now')),
                dispute_opened_at TEXT)""")
            # sha256 добавлен позже — колонки может не быть в старой БД
            if "sha256" not in [r["name"] for r in
                                conn.execute("PRAGMA table_info(order_receipts)")]:
                conn.execute("ALTER TABLE order_receipts ADD COLUMN sha256 TEXT")
            conn.execute("INSERT OR REPLACE INTO order_receipts "
                         "(order_id, path, filename, content_type, sha256) VALUES (?,?,?,?,?)",
                         (order_id, str(p), filename, content_type, sha))
            conn.commit()
        return str(p)
    except Exception as e:
        logger.warning("receipts: сохранение чека order=%s: %s", order_id, e)
        return None


def receipt_fraud_flags(order_id, file_bytes=None) -> list:
    """Возвращает список предупреждений о подозрительном чеке (для оператора).

    Не блокирует ничего сам — только подсвечивает риск, решение за человеком.
    Признаки: тот же файл уже присылали по другой заявке (дубль-чек), и у
    клиента серия истёкших заявок без единой оплаты (шаблон 8748843234:
    заявка → старый/чужой чек → требование крипты).
    """
    flags = []
    try:
        with _db() as conn:
            if file_bytes is not None:
                h = hashlib.sha256(file_bytes).hexdigest()
                try:
                    dup = conn.execute(
                        "SELECT order_id FROM order_receipts WHERE sha256=? AND order_id<>?",
                        (h, order_id)).fetchall()
                except sqlite3.OperationalError:
                    dup = []  # колонки sha256 ещё нет (старая БД до первого чека)
                if dup:
                    flags.append("♻️ Этот же файл-чек уже присылали по заявкам "
                                 + ", ".join(f"#{r['order_id']}" for r in dup[:5]))
            row = conn.execute("SELECT user_id FROM orders WHERE order_id=?",
                               (order_id,)).fetchone()
            uid = row["user_id"] if row else None
            if uid and uid > 0:
                st = conn.execute(
                    "SELECT SUM(status='expired') exp, "
                    "SUM(status IN ('paid','sent')) paid FROM orders WHERE user_id=?",
                    (uid,)).fetchone()
                exp, paid = (st["exp"] or 0), (st["paid"] or 0)
                if exp >= 3 and paid == 0:
                    flags.append(f"⚠️ У клиента {exp} истёкших заявок и НИ ОДНОЙ оплаченной "
                                 f"— повышенный риск фиктивного чека")
    except Exception as e:
        logger.warning("receipts: fraud-flags order=%s: %s", order_id, e)
    return flags


def load_receipt(order_id):
    """Возвращает (bytes, filename, content_type) сохранённого чека или None."""
    try:
        with _db() as conn:
            row = conn.execute("SELECT path, filename, content_type FROM order_receipts "
                               "WHERE order_id=?", (order_id,)).fetchone()
        if not row:
            return None
        with open(row["path"], "rb") as f:
            return f.read(), row["filename"], row["content_type"]
    except Exception as e:
        logger.warning("receipts: чтение чека order=%s: %s", order_id, e)
        return None


def _mark_sent(order_id):
    """Фиксируем факт доставки — иначе доказать, что чек уходил, будет нечем."""
    try:
        with _db() as conn:
            conn.execute("UPDATE orders SET receipt_sent_at=datetime('now') "
                         "WHERE order_id=?", (order_id,))
            conn.commit()
    except Exception as e:
        logger.warning("receipts: отметка receipt_sent_at order=%s: %s", order_id, e)
