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
import logging
import os
import sqlite3
import sys

if "/root/relay" not in sys.path:
    sys.path.insert(0, "/root/relay")

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
    return {"provider": (row["provider"] or "").lower(),
            "invoice_id": row["provider_invoice_id"],
            "status": row["status"],
            "raw": raw if isinstance(raw, dict) else {}}


# ── каналы провайдеров ────────────────────────────────────────────────────────

def _montera(sess, file_bytes, filename, content_type):
    from providers.montera import MonteraProvider
    p = MonteraProvider()
    # Видео и повторное доказательство идут через additional-info; первичный
    # PDF-чек — на одноразовый receipt_upload_url, если Montera его выдала.
    url = (sess["raw"] or {}).get("receipt_upload_url")
    if content_type == PDF and url:
        return p.upload_receipt(url, file_bytes, filename)
    return p.upload_additional_info(sess["invoice_id"], file_bytes, filename, content_type)


def _vertu(sess, file_bytes, filename, content_type):
    from providers.vertu import VertuProvider
    if content_type != PDF:
        return {"ok": False, "error": "Vertu принимает только PDF-чек"}
    # platform_id (0084-…), а не наш deal_id — именно он ключ сделки у Vertu
    pid = (sess["raw"] or {}).get("platform_id") or sess["invoice_id"]
    return VertuProvider().upload_receipt(pid, file_bytes, filename)


def _brabus(sess, file_bytes, filename, content_type):
    from providers.brabus import BrabusProvider
    # Вариант (=API-ключ), которым создавали инвойс, — если он записан в сессии.
    # Иначе перебираем ключи: инвойс виден только «своему» ключу.
    hint = (sess["raw"] or {}).get("variant") or ""
    return BrabusProvider.confirm_transfer_any(
        sess["invoice_id"], file_bytes, filename, variant_hint=hint)


def _stormtrade(sess, file_bytes, filename, content_type):
    from providers.stormtrade import StormTradeProvider
    return StormTradeProvider().confirm_transfer(
        sess["invoice_id"], file_bytes, filename)


def _xpay(sess, file_bytes, filename, content_type):
    from providers.xpayconnect import XPayConnectProvider
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
        variant_hint=raw.get("variant") or "")


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
    return {"ok": ok, "provider": provider, "reason": None if ok else "rejected",
            "error": None if ok else res.get("error"), "raw": res.get("raw")}


def _mark_sent(order_id):
    """Фиксируем факт доставки — иначе доказать, что чек уходил, будет нечем."""
    try:
        with _db() as conn:
            conn.execute("UPDATE orders SET receipt_sent_at=datetime('now') "
                         "WHERE order_id=?", (order_id,))
            conn.commit()
    except Exception as e:
        logger.warning("receipts: отметка receipt_sent_at order=%s: %s", order_id, e)
