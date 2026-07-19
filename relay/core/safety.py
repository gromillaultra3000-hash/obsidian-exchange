"""core.safety — единый доступ к решениям безопасности выплат.

Фасад над реальными стражами (relay/services). Реализации пока живут в services/*;
здесь — единая точка для нового кода (кошелёк, api, будущий payout-worker), чтобы
политика fail-closed вызывалась единообразно.
"""
from __future__ import annotations


def verify_payment_settled(order_id):
    """Live-перепроверка оплаты у провайдера (payout_guard). None-безопасно."""
    from services.payout_guard import verify_payment_settled as _f
    return _f(order_id)


def payout_circuit_status() -> dict:
    """Состояние circuit-breaker выплат."""
    from services import payout_circuit
    return payout_circuit.status()


def check_payout_allowed(order_id, rub_amount, address, currency) -> dict:
    """Проверка стоп-крана ПЕРЕД авто-выплатой. FAIL-CLOSED: любая ошибка → manual."""
    try:
        from services import payout_circuit
        return payout_circuit.check_payout_allowed(order_id, rub_amount, address, currency)
    except Exception as e:
        return {"action": "manual", "reason": f"страж выплат недоступен ({type(e).__name__}) — авто-выплата запрещена (fail-closed)"}
