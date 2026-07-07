import os, sqlite3, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

MONTERA_BASE_URL = os.getenv('MONTERA_BASE_URL', 'https://montera.one/api')
MONTERA_API_TOKEN = os.getenv('MONTERA_API_TOKEN', '')
MONTERA_MERCHANT_ID = os.getenv('MONTERA_MERCHANT_ID', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')
DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')


def _get_user_rating(user_id: int) -> tuple[dict, bool]:
    """Возвращает (user_rating, client_trusted) по истории заявок пользователя."""
    if not user_id or user_id < 0:
        return {"success": 0, "failure": 0}, False
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        c = conn.cursor()
        c.execute(
            "SELECT "
            "SUM(CASE WHEN status IN ('paid','sent','completed') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN status IN ('failed','cancelled') THEN 1 ELSE 0 END) "
            "FROM orders WHERE user_id=?",
            (user_id,),
        )
        row = c.fetchone()
        conn.close()
        success = int(row[0] or 0)
        failure = int(row[1] or 0)
        trusted = success > 0 and success >= failure
        return {"success": success, "failure": failure}, trusted
    except Exception as e:
        logger.warning(f"Montera: не удалось получить рейтинг пользователя {user_id}: {e}")
        return {"success": 0, "failure": 0}, False


class MonteraProvider(PaymentProvider):
    def __init__(self):
        self.base_url = MONTERA_BASE_URL.rstrip('/')
        self.api_token = MONTERA_API_TOKEN
        self.merchant_id = MONTERA_MERCHANT_ID

    def _headers(self):
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Access-Token": self.api_token,
        }

    def create_invoice(self, order_id, amount, payment_method=None, user_id=None):
        user_rating, client_trusted = _get_user_rating(user_id)

        if payment_method == "sbp":
            payload = {
                "external_id": f"obsidian_{order_id}",
                "amount": int(round(float(amount))),
                "payment_gateway": "sbp_rub",
                "merchant_id": self.merchant_id,
                "callback_url": f"{PUBLIC_RELAY}/montera/webhook",
            }
        else:
            payload = {
                "external_id": f"obsidian_{order_id}",
                "amount": int(round(float(amount))),
                "currency": "rub",
                "payment_detail_type": "card",
                "merchant_id": self.merchant_id,
                "callback_url": f"{PUBLIC_RELAY}/montera/webhook",
            }
        try:
            r = requests.post(
                f"{self.base_url}/h2h/order",
                json=payload, headers=self._headers(), timeout=PROVIDER_TIMEOUT,
            )
            data = r.json()
            if r.status_code != 200 or not data.get("success"):
                active = self._get_active_limits()
                logger.error(
                    f"Montera error {r.status_code}: {data} | запрошено: amount={payload['amount']} "
                    f"method={payment_method} | сейчас активно у трейдеров: {active}"
                )
                return {"error": data.get("message") or f"Montera error: {r.status_code}"}

            inner = data.get("data", {})
            detail = inner.get("payment_detail") or {}
            requisites = {}
            if detail.get("detail_type") == "phone":
                requisites["phone"] = detail.get("detail")
            else:
                requisites["card_number"] = detail.get("detail")
            # method_name = конкретный банк для СБП (напр. "Сбербанк"), payment_gateway_name = "СБП"
            bank_display = inner.get("method_name") or inner.get("payment_gateway_name")
            if bank_display:
                requisites["bank_name"] = bank_display
            # initials для телефона — имя держателя; для карты — дублирует банк, не нужен
            if detail.get("initials") and detail.get("detail_type") == "phone":
                requisites["recipient"] = detail["initials"]

            raw = dict(inner)
            raw["requisites"] = requisites
            raw["receipt_upload_url"] = inner.get("receipt_upload_url")
            return {
                "invoice_id": inner.get("order_id"),
                "amount": amount,
                "status": "awaiting_payment",
                "qr_payload": None,
                "banks": [],
                "raw": raw,
            }
        except Exception as e:
            logger.error(f"Montera request failed: {e}")
            return {"error": str(e)}

    def upload_additional_info(self, montera_order_id: str, file_bytes: bytes,
                               filename: str = "file", content_type: str = "video/mp4") -> dict:
        """Загружает видео или PDF по запросу оператора Montera (requested_type: video / pdf-success)."""
        import time as _time
        url = f"{self.base_url}/h2h/order/{montera_order_id}/additional-info"
        last_error = None
        for attempt in range(3):
            if attempt:
                _time.sleep(4)
            try:
                r = requests.post(
                    url,
                    headers={"Access-Token": self.api_token, "Accept": "application/json"},
                    files={"file": (filename, file_bytes, content_type)},
                    timeout=60,
                    allow_redirects=False,
                )
                if r.status_code in (200, 201, 302, 303):
                    return {"ok": True}
                if r.status_code in (502, 503, 504):
                    last_error = f"Montera временно недоступна (HTTP {r.status_code}), попробуйте через 1-2 минуты"
                    logger.warning(f"Montera additional-info attempt {attempt+1} got {r.status_code}, retrying...")
                    continue
                return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
            except requests.exceptions.Timeout:
                last_error = "Montera не отвечает (timeout), попробуйте через 1-2 минуты"
                logger.warning(f"Montera additional-info attempt {attempt+1} timeout")
            except Exception as e:
                logger.error(f"Montera upload_additional_info failed: {e}")
                return {"ok": False, "error": str(e)}
        return {"ok": False, "error": last_error or "Montera недоступна, попробуйте позже"}

    def upload_receipt(self, receipt_upload_url: str, file_bytes: bytes, filename: str = "receipt.pdf") -> dict:
        """Загружает PDF-чек подтверждения оплаты на одноразовый URL Montera."""
        try:
            r = requests.post(
                receipt_upload_url,
                files={"receipt": (filename, file_bytes, "application/pdf")},
                timeout=30,
                allow_redirects=False,
            )
            # 303 Redirect = успех (форма обработана сервером Montera)
            if r.status_code in (200, 201, 302, 303):
                return {"ok": True}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            logger.error(f"Montera upload_receipt failed: {e}")
            return {"ok": False, "error": str(e)}

    def _get_active_limits(self):
        try:
            r = requests.get(
                f"{self.base_url}/payment-details/active",
                params={"merchant_id": self.merchant_id},
                headers=self._headers(), timeout=5,
            )
            if r.status_code == 200:
                return r.json().get("data")
        except Exception:
            pass
        return None

    def check_availability(self, amount, payment_method=None):
        """
        Проверяет, есть ли активный трейдер под данную сумму и тип.
        Возвращает dict:
          available: bool
          detail_type: "card" | "phone"
          slots: список активных слотов (min/max) для данного типа
          min_available: int | None — минимальная сумма из всех активных слотов
          max_available: int | None — максимальная сумма из всех активных слотов
        """
        detail_type = "phone" if payment_method == "sbp" else "card"
        try:
            limits = self._get_active_limits()
            rub = (limits or {}).get("rub", {})
            slots = rub.get(detail_type, [])
            if not slots:
                return {"available": False, "detail_type": detail_type, "slots": [],
                        "min_available": None, "max_available": None}

            amt = int(round(float(amount)))
            matching = [s for s in slots
                        if int(s["min_limit"]) <= amt <= int(s["max_limit"])]
            all_mins = [int(s["min_limit"]) for s in slots]
            all_maxs = [int(s["max_limit"]) for s in slots]
            return {
                "available": len(matching) > 0,
                "detail_type": detail_type,
                "slots": slots,
                "min_available": min(all_mins),
                "max_available": max(all_maxs),
            }
        except Exception:
            # При ошибке не блокируем — пускаем invoice и получим ошибку там
            return {"available": True, "detail_type": detail_type, "slots": [],
                    "min_available": None, "max_available": None}

    def get_status(self, invoice_id):
        try:
            r = requests.get(
                f"{self.base_url}/h2h/order/{invoice_id}",
                headers=self._headers(), timeout=PROVIDER_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                inner = data.get("data", {})
                status = inner.get("status")
                normalized = "paid" if status == "success" else ("failed" if status == "fail" else status)
                return {"status": normalized or "unknown", "raw": inner}
            return {"status": "unknown"}
        except Exception as e:
            logger.error(f"Montera status check failed: {e}")
            return {"status": "unknown"}

    def get_payment_methods(self, invoice_id):
        return []

    def parse_webhook(self, data):
        external_id = data.get('external_id', '') or ''
        order_id = None
        if external_id.startswith('obsidian_'):
            order_id = external_id.split('_', 1)[1]
        status = data.get('status')
        normalized_status = 'paid' if status == 'success' else status
        if order_id and normalized_status:
            return order_id, normalized_status
        return None, None
