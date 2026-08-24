import json, logging, requests

logger = logging.getLogger(__name__)
PROXY_URL = "https://pay.platega.io/api/v1/platega"

def create_invoice(order_id, amount):
    """Создать счёт через прокси, возвращает dict с ключами redirect и transactionId"""
    try:
        r = requests.post(f"{PROXY_URL}/invoice",
                         json={"order_id": order_id, "amount": str(amount)}, timeout=15)
        return r.json()
    except Exception as e:
        logger.exception("Proxy invoice error: %s", e)
        return None

def check_payment(transaction_id):
    """Проверить статус транзакции через прокси. Возвращает статус (например, CONFIRMED, PENDING) или None"""
    try:
        r = requests.post(f"{PROXY_URL}/status",
                         json={"transaction_id": transaction_id}, timeout=10)
        data = r.json()
        return data.get("status")
    except Exception as e:
        logger.exception("Proxy status error: %s", e)
        return None
