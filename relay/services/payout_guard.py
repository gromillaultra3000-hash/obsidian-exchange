"""
Fail-closed гейт выплаты: перед авто-отправкой крипты НЕЗАВИСИМО перепроверяет у
провайдера, что оплата реально прошла. Флаг orders.status='paid' сам по себе НЕ
достаточен для авто-выплаты — здесь мы переспрашиваем первоисточник (provider
.get_status) в момент выплаты.

Строгая политика (выбор оператора 13.07.2026):
  crypto авто-уходит ТОЛЬКО когда провайдер в моменте подтвердил 'paid'.
  Всё остальное (unknown / ошибка сети / нет провайдерского статуса / ручное
  подтверждение / Fallback-маршрут) → в ручной разбор к работнику.

Вердикты verify_payment_settled():
  - 'confirmed'  — провайдер live-подтвердил paid → можно авто-выплату
  - 'hold'       — трейдер запросил видео/PDF (verification_requested) и ещё не
                   закрыл → держать, НЕ платить, перепроверить позже
  - 'manual'     — авто-подтверждения нет → к работнику вручную
                   (warn=True + reason, если провайдер явно сообщил failed/cancelled)

Никогда не «отпускает лишнего»: в сомнении — человек. Чистая добавка к
auto_check_payments, существующие гарантии (status='paid' ставит только вебхук/
ручное подтверждение) не ослабляются.
"""
import sqlite3
import logging
from pathlib import Path

DB_PATH = Path("/root/exchange.db")
logger = logging.getLogger(__name__)

# короткое имя (payment_sessions.provider) → имя класса провайдера
SHORT_TO_CLASS = {
    "montera": "MonteraProvider",
    "brabus": "BrabusProvider",
    "vertu": "VertuProvider",
    "xpay": "XPayConnectProvider",
    "lava": "LavaProvider",
    "greenpay": "GreenPayProvider",
    "stormtrade": "StormTradeProvider",
    # fallback / platega — НЕ перепроверяем (ручной/резервный путь) → 'manual'
}

# провайдерские статусы (нормализованные get_status) → расчёт прошёл
_PAID = {"paid", "success", "completed", "approved", "sent", "finished"}
# провайдер явно сообщает, что оплаты НЕТ
_FAILED = {"failed", "fail", "cancelled", "canceled", "declined", "revoked", "rejected"}


def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _load_provider(cls_name):
    """Инстанцирует провайдера по имени класса (зеркало payment_service._load_provider).
    Возвращает None при неудаче — вызов трактует это как 'нет подтверждения'."""
    try:
        if cls_name == "MonteraProvider":
            from providers.montera import MonteraProvider
            return MonteraProvider()
        if cls_name == "BrabusProvider":
            from providers.brabus import BrabusProvider
            return BrabusProvider()
        if cls_name == "VertuProvider":
            from providers.vertu import VertuProvider
            return VertuProvider()
        if cls_name == "XPayConnectProvider":
            from providers.xpayconnect import XPayConnectProvider
            return XPayConnectProvider()
        if cls_name == "LavaProvider":
            from providers.lava import LavaProvider
            return LavaProvider()
        if cls_name == "GreenPayProvider":
            from providers.greenpay import GreenPayProvider
            return GreenPayProvider()
        if cls_name == "StormTradeProvider":
            from providers.stormtrade import StormTradeProvider
            return StormTradeProvider()
    except Exception as e:
        logger.warning("payout_guard: не удалось загрузить %s: %s", cls_name, e)
    return None


def verify_payment_settled(order_id) -> dict:
    """Независимая перепроверка расчёта по заявке. См. модульный docstring."""
    # 1) сессии оплаты заявки (эскалация могла создать несколько)
    try:
        with _db() as conn:
            sessions = conn.execute(
                "SELECT provider, provider_invoice_id FROM payment_sessions "
                "WHERE order_id=? ORDER BY id DESC", (order_id,)).fetchall()
    except Exception as e:
        logger.warning("payout_guard: чтение payment_sessions order=%s: %s", order_id, e)
        sessions = []

    contradiction = None
    checked_any = False
    for s in sessions:
        provider = (s["provider"] or "").split(":")[0].strip().lower()
        inv_id = s["provider_invoice_id"]
        cls = SHORT_TO_CLASS.get(provider)
        if not cls or not inv_id:
            continue  # fallback/platega/без invoice → перепроверить нечем
        prov = _load_provider(cls)
        if not prov or not hasattr(prov, "get_status"):
            continue
        checked_any = True
        try:
            st = str((prov.get_status(inv_id) or {}).get("status", "unknown")).lower()
        except Exception as e:
            logger.warning("payout_guard: get_status %s inv=%s order=%s: %s",
                           cls, inv_id, order_id, e)
            st = "unknown"
        if st in _PAID:
            # ГЛАВНОЕ подтверждение: провайдер отдаёт 'paid' только когда трейдер
            # закрыл сделку на своей стороне (включая видео/PDF, если запрашивал).
            # Это перекрывает зависший флаг verification_requested — платёж реально
            # прошёл. Первого же live-paid достаточно (сиблинги-эскалации могли
            # истечь — норма).
            return {"verdict": "confirmed", "provider": provider, "detail": st}
        if st in _FAILED:
            contradiction = (provider, st)

    # 2) провайдер ещё НЕ подтвердил paid. Если трейдер запросил видео/PDF и это
    #    не закрыто — держим (не отдаём крипту до подтверждения трейдера).
    try:
        with _db() as conn:
            row = conn.execute(
                "SELECT verification_requested FROM orders WHERE order_id=?",
                (order_id,)).fetchone()
        if row and (row["verification_requested"] or "").strip():
            return {"verdict": "hold",
                    "detail": f"трейдер запросил {row['verification_requested']} — "
                              f"не закрыто, провайдер ещё не подтвердил paid"}
    except Exception as e:
        logger.warning("payout_guard: чтение verification_requested order=%s: %s", order_id, e)

    if not sessions:
        return {"verdict": "manual", "warn": False,
                "detail": "нет payment_session (ручное подтверждение / on-chain)"}
    if contradiction:
        return {"verdict": "manual", "warn": True,
                "detail": f"провайдер {contradiction[0]} сообщает '{contradiction[1]}' — "
                          f"платёж НЕ подтверждён, проверить вручную"}
    return {"verdict": "manual", "warn": False,
            "detail": ("провайдер не подтвердил оплату (unknown/ошибка связи)"
                       if checked_any else "нет провайдера для перепроверки")}
