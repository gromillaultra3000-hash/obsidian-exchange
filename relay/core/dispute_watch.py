"""Автоматическое открытие спора по неподтверждённой оплате.

Сценарий, ради которого это существует (дока StormTrade, disputes): «клиент
произвёл оплату и подтвердил перевод, но по какой-то причине система не
подтверждает сделку». До сих пор такая заявка молча доживала до истечения, и
деньги оставались у трейдера — так 20.07.2026 ушли 30 000 ₽.

Апелляция в чате провайдера — ручной интерфейс оператора. Документированный
автоматический эквивалент один: POST .../dispute с приложенным чеком. Его и
дёргаем, приложив тот файл, который клиент уже прислал.

Осторожность здесь важнее скорости: спор — это обращение НАРУЖУ, к партнёру.
Ложные споры портят отношения с провайдером быстрее, чем приносят пользу.
Поэтому набор условий строгий и проверяется целиком:
  1) клиент реально прислал чек (он же станет доказательством);
  2) заявка всё ещё не оплачена по нашим данным;
  3) провайдер подтверждает, что не видит оплату (спрашиваем его живьём);
  4) прошло достаточно времени, чтобы зачисление успело дойти;
  5) по этой заявке спор ещё не открывали.
Не выполнено любое — не трогаем и оставляем человеку.
"""
from __future__ import annotations
import logging
import os
import sys

# путь к relay — от себя, а не от боевого каталога (мина «зашитый боевой путь»)
_RELAY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RELAY not in sys.path:
    sys.path.insert(0, _RELAY)
from repositories.receipt_store import from_environment as _receipt_store_from_environment

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")
def _store():return _receipt_store_from_environment(sqlite_path=DB_PATH)

# Сколько ждать после отправки чека, прежде чем считать, что оплату не зачли.
# Меньше 15 минут ставить нельзя: у части провайдеров зачисление доходит
# минутами, и мы будем спорить по успешным платежам.
DELAY_MIN = max(15, int(os.getenv("DISPUTE_AFTER_MIN", "25") or 25))
# Аварийный выключатель: DISPUTE_AUTO=0 полностью останавливает автоматику,
# при этом чек всё равно уходит персоналу и спор можно открыть руками.
ENABLED = (os.getenv("DISPUTE_AUTO", "1") or "1").strip() not in ("0", "false", "no")


def _candidates() -> list[dict]:
    """Заявки с присланным чеком, которые так и не стали оплаченными."""
    try:
        return _store().candidates(DELAY_MIN)
    except Exception as e:
        logger.warning("dispute_watch: выборка кандидатов: %s", e)
        return []


def _provider_still_unpaid(order_id) -> tuple[bool, str]:
    """Спрашиваем провайдера живьём. Спорить можно только если он НЕ видит оплату.

    Fail-closed: любой неясный ответ (нет связи, unknown) — не спорим.
    """
    from core.receipts import find_session
    sess = find_session(order_id)
    if not sess:
        return False, "нет сессии"
    try:
        from services.payment_service import PaymentService
        from services.smart_router import CLASS_BY_SHORT
        # В payment_sessions лежит КОРОТКОЕ имя, иногда с вариантом
        # ('brabus:vietqr'), а _load_provider ждёт имя класса. Без этой
        # трансляции сюда молча возвращался FallbackProvider, статус выходил
        # 'unknown' — и автомат не спорил бы ни разу.
        raw_name = sess["provider"] or ""
        short, _, variant = raw_name.partition(":")
        cls_name = CLASS_BY_SHORT.get(short)
        if not cls_name:
            return False, f"неизвестный провайдер '{short}'"
        if short == "brabus":
            # Варианты Brabus живут на разных API-ключах: инвойс виден только
            # «своему». Дефолтный вариант вернул бы 'unknown' по чужому инвойсу.
            from providers.brabus import BrabusProvider
            provider = BrabusProvider(variant=variant or "tbank_deeplink")
        else:
            provider = PaymentService()._load_provider(cls_name)
            if provider.__class__.__name__ != cls_name:
                return False, f"провайдер {cls_name} не загрузился"
    except Exception as e:
        return False, f"провайдер не загрузился: {type(e).__name__}"
    if not provider:
        return False, f"провайдер {cls_name} не загрузился"
    try:
        st = (provider.get_status(sess["invoice_id"]) or {}).get("status")
    except Exception as e:
        return False, f"статус недоступен: {type(e).__name__}"
    if st in ("paid", "success"):
        return False, "провайдер видит оплату"
    if st in (None, "unknown"):
        return False, "статус неизвестен"
    return True, str(st)


def _mark_opened(order_id):
    try:
        return _store().claim_dispute(order_id)
    except Exception as e:
        logger.warning("dispute_watch: отметка спора order=%s: %s", order_id, e)


def run_once() -> list[dict]:
    """Один проход. Возвращает список того, что сделано — для уведомления персонала."""
    if not ENABLED:
        return []
    from core.receipts import load_receipt, open_dispute, dispute_available

    results = []
    for c in _candidates():
        oid = c["order_id"]

        rec = load_receipt(oid)
        if not rec:
            logger.info("dispute_watch: #%s пропуск — чек не найден на диске", oid)
            continue

        ok_to_dispute, why = _provider_still_unpaid(oid)
        if not ok_to_dispute:
            logger.info("dispute_watch: #%s не спорим — %s", oid, why)
            # Провайдер видит оплату, а у нас статус не обновлён — это отдельная
            # поломка, о ней должен узнать человек, а не молча пройти мимо.
            if why == "провайдер видит оплату":
                if not _mark_opened(oid):continue
                results.append({"order_id": oid, "action": "mismatch",
                                "amount": c["rub_amount"], "username": c["username"],
                                "detail": "провайдер подтверждает оплату, а заявка не paid"})
            continue

        file_bytes, filename, _ct = rec
        if not dispute_available(oid):
            # У Montera/Vertu/XPay спора в API нет — только чат поддержки.
            # Говорим об этом прямо и один раз, чтобы оператор пошёл туда.
            if not _mark_opened(oid):continue
            results.append({"order_id": oid, "action": "manual",
                            "amount": c["rub_amount"], "username": c["username"],
                            "detail": "спор через API не поддерживается — открыть в чате провайдера"})
            continue

        if not _mark_opened(oid):continue
        res = open_dispute(oid, file_bytes, filename, reason="no_payment")
        results.append({"order_id": oid,
                        "action": "opened" if res.get("ok") else "failed",
                        "amount": c["rub_amount"], "username": c["username"],
                        "provider": res.get("provider"),
                        "detail": res.get("error") or "спор открыт"})
        logger.info("dispute_watch: #%s → %s (%s)", oid,
                    "спор открыт" if res.get("ok") else "не удалось",
                    res.get("error") or "")
    return results


def format_report(results: list[dict]) -> str:
    """Сводка для Telegram. Пусто — значит нечего сообщать, молчим."""
    if not results:
        return ""
    icon = {"opened": "⚖️", "failed": "⚠️", "manual": "✋", "mismatch": "❗"}
    head = {"opened": "Спор открыт автоматически", "failed": "Спор не открылся",
            "manual": "Нужен спор вручную", "mismatch": "Расхождение статусов"}
    lines = ["⚖️ <b>Споры по неподтверждённым оплатам</b>\n"]
    for r in results:
        amt = f"{int(r['amount']):,} ₽".replace(",", " ") if r.get("amount") else "?"
        who = f"@{r['username']}" if r.get("username") else ""
        lines.append(f"{icon.get(r['action'], '•')} <b>#{r['order_id']}</b> · {amt} {who}\n"
                     f"    {head.get(r['action'], r['action'])}: {r['detail']}")
    return "\n".join(lines)
