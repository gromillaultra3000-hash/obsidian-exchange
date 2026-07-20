import hmac, hashlib, base64, json, os, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

# StormTrade (docs.stormtrade.club) — тот же Merchant Integration API, что у Brabus
# (X-Identity + X-Signature HMAC-SHA1/Base64, /api/merchant/invoices, массив deals).
# Самая невыгодная ставка из всех провайдеров, поэтому используется ТОЛЬКО:
#   1) как последний резерв, когда остальные не выдали реквизиты (эскалация
#      в PaymentService.create_session перед FallbackProvider);
#   2) для методов, которых нет у других провайдеров (SBP_QR, TO_ACCOUNT, ...).
# В обычный weighted-выбор smart_router НЕ попадает (last_resort=True).
STORMTRADE_BASE_URL = os.getenv('STORMTRADE_BASE_URL', 'https://api.stormtrade.club').rstrip('/')
STORMTRADE_API_KEY = os.getenv('STORMTRADE_API_KEY', '')
STORMTRADE_SECRET = os.getenv('STORMTRADE_SECRET', '')
STORMTRADE_NOTIFICATION_TOKEN = os.getenv('STORMTRADE_NOTIFICATION_TOKEN', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')

# payment_method (наш код) -> paymentOption StormTrade.
# sbp/card дублируют другие провайдеры (только для эскалации);
# sbp_qr / mobile — эксклюзивные методы, которых у нас ещё нет.
# TO_ACCOUNT убран 08.07.2026 по требованию StormTrade: направлять только
# СБП / перевод на карту, не «перевод по номеру счёта».
METHOD_TO_OPTION = {
    "sbp":     "SBP",             # перевод по номеру телефона (СБП)
    "card":    "TO_CARD",         # перевод на карту
    "sbp_qr":  "SBP_QR",          # оплата по НСПК QR-коду
    "mobile":  "MOBILE_TOP_UP",   # пополнение счёта моб. телефона
}
# Методы, которых нет у остальных провайдеров — по ним StormTrade основной
EXCLUSIVE_METHODS = ("sbp_qr", "mobile")

_STATUS_MAP = {
    "new": "awaiting_payment",
    "paid": "paid",
    "canceled": "failed",
    "expired": "failed",
    "dispute": "dispute",
}


class StormTradeProvider(PaymentProvider):
    def __init__(self):
        self.base_url = STORMTRADE_BASE_URL
        self.api_key = STORMTRADE_API_KEY
        self.secret = STORMTRADE_SECRET

    # ── Авторизация ────────────────────────────────────────────────────────────

    def _sign(self, method, url, body=""):
        # Для GET и multipart строка подписи — только метод + URL (по доке)
        string_to_sign = f"{method}{url}{body}"
        h = hmac.new(self.secret.encode(), string_to_sign.encode(), hashlib.sha1)  # noqa: S324
        return base64.b64encode(h.digest()).decode()

    def _headers(self, method, url, body=""):
        return {
            "X-Identity": self.api_key,
            "X-Signature": self._sign(method, url, body),
            "Content-Type": "application/json",
        }

    # ── Создание инвойса (Сценарий A — прямой запрос реквизитов) ───────────────

    def create_invoice(self, order_id, amount, payment_method=None, user_id=None):
        if not self.api_key or not self.secret:
            return {"error": "StormTrade: не настроены STORMTRADE_API_KEY/STORMTRADE_SECRET"}

        # Без paymentOption терминал выдаёт «любые свободные реквизиты» и может
        # подсунуть TO_ACCOUNT — StormTrade просил только СБП/карту, поэтому
        # неизвестный/пустой метод всегда маппим в SBP.
        option = METHOD_TO_OPTION.get(payment_method) or "SBP"
        url = f"{self.base_url}/api/merchant/invoices"
        payload = {
            "type": "in",
            "amount": f"{float(amount):.2f}",
            "currency": "RUB",
            "notificationUrl": f"{PUBLIC_RELAY}/stormtrade/webhook",
            "notificationToken": STORMTRADE_NOTIFICATION_TOKEN,
            "internalId": f"obsidian_{order_id}",
            "startDeal": True,
            "paymentMethod": None,
            "paymentOption": option,
        }
        if user_id:
            payload["userId"] = str(user_id)
        body = json.dumps(payload, separators=(',', ':'))
        try:
            r = requests.post(url, data=body.encode(),
                              headers=self._headers("POST", url, body),
                              timeout=PROVIDER_TIMEOUT)
        except Exception as e:
            logger.error(f"StormTrade create_invoice failed: {e}")
            return {"error": str(e)}

        if r.status_code != 200:
            # 400 PAYMENT_METHOD_NOT_AVAILABLE = нет свободных реквизитов
            logger.error(f"StormTrade create error {r.status_code}: {r.text[:300]} | "
                         f"amount={amount} option={option}")
            return {"error": f"StormTrade HTTP {r.status_code}"}

        data = r.json()
        deals = data.get("deals") or []
        inv_id = data.get("id")
        if not deals:
            logger.warning(f"StormTrade нет deals для order {order_id} (option={option})")
            return {"error": "Нет свободных реквизитов, попробуйте другой способ"}

        deal = deals[0]
        deal_req = deal.get("requisites") or {}
        req_text = deal_req.get("requisites")
        holder = deal_req.get("holder")
        deal_option = deal.get("paymentOption", "")

        requisites = {}
        if deal_option in ("SBP_QR", "MANUAL_SBP_QR", "VIET_QR", "CLICK_UZ_QR"):
            # НСПК-QR обычно приходит ссылкой https://qr.nspk.ru/...
            if req_text and req_text.startswith("http"):
                requisites["payment_link"] = req_text
            else:
                requisites["qr_data"] = req_text
        elif deal_option in ("SBP", "TO_PHONE_NUMBER", "MOBILE_TOP_UP"):
            requisites["phone"] = req_text
        elif deal_option in ("TO_ACCOUNT", "TO_BANK_DETAILS"):
            requisites["account"] = req_text
        else:
            requisites["card_number"] = req_text

        if holder:
            requisites["recipient"] = holder
        bank_name = deal.get("paymentMethodName") or (deal.get("paymentMethod") or "").capitalize()
        # у QR-методов банк часто приходит как "unknown" — юзеру не показываем
        if bank_name and bank_name.lower() != "unknown":
            requisites["bank_name"] = bank_name

        qr_code_link = deal.get("qrCodeLink")
        if qr_code_link and "payment_link" not in requisites and deal_option not in ("SBP_QR", "MANUAL_SBP_QR", "VIET_QR"):
            requisites["payment_link"] = qr_code_link
        # Telegram не принимает SVG — конвертируем в PNG, если формат в query
        qr_image_url = None
        if qr_code_link and deal_option in ("SBP_QR", "MANUAL_SBP_QR", "VIET_QR"):
            qr_image_url = qr_code_link.replace("format=svg", "format=png")

        raw = {
            "requisites": requisites,
            "invoice_id": inv_id,
            "deal_id": deal.get("id"),
            "payment_option": deal_option,
            "qr_image_url": qr_image_url,
            "expire_at": data.get("expireAt"),
        }
        return {
            "invoice_id": inv_id,
            "amount": amount,
            "status": "awaiting_payment",
            "qr_payload": requisites.get("payment_link") or qr_code_link,
            "banks": [],
            "raw": raw,
        }

    # ── Статус инвойса ─────────────────────────────────────────────────────────

    def get_status(self, invoice_id):
        if not invoice_id:
            return {"status": "unknown"}
        url = f"{self.base_url}/api/merchant/invoices/{invoice_id}"
        try:
            r = requests.get(url, headers=self._headers("GET", url), timeout=PROVIDER_TIMEOUT)
            if r.status_code != 200:
                return {"status": "unknown"}
            data = r.json()
            status = data.get("status")
            return {"status": _STATUS_MAP.get(status, status or "unknown"),
                    "raw_status": status, "raw": data}
        except Exception as e:
            logger.error(f"StormTrade get_status failed: {e}")
            return {"status": "unknown"}

    # ── Отмена инвойса ─────────────────────────────────────────────────────────

    def cancel_order(self, invoice_id: str) -> bool:
        if not invoice_id or not self.api_key:
            return False
        url = f"{self.base_url}/api/merchant/invoices/{invoice_id}/cancel"
        try:
            r = requests.post(url, headers=self._headers("POST", url),
                              timeout=PROVIDER_TIMEOUT)
            if r.status_code == 200:
                logger.info(f"StormTrade cancelled {invoice_id}")
                return True
            logger.warning(f"StormTrade cancel {invoice_id}: HTTP {r.status_code}")
            return False
        except Exception as e:
            logger.error(f"StormTrade cancel_order failed: {e}")
            return False

    # ── Доступные способы оплаты терминала (для сверки эксклюзивных методов) ───

    def confirm_transfer(self, invoice_id: str, file_bytes: bytes,
                         filename: str = "receipt.pdf") -> dict:
        """Прикрепляет чек об операции к инвойсу (POST .../confirm-transfer).

        Канал существовал с начала интеграции (та же white-label API, что у
        Brabus), но реализован не был — доказать оплату у StormTrade было нечем.
        Для multipart подпись считается без тела, как и в остальных запросах.
        """
        if not invoice_id:
            return {"ok": False, "error": "Нет invoice_id"}
        if len(file_bytes) > 10 * 1024 * 1024:
            return {"ok": False, "error": "Файл больше 10 МБ — StormTrade его не примет"}
        url = f"{self.base_url}/api/merchant/invoices/{invoice_id}/confirm-transfer"
        headers = self._headers("POST", url)
        # requests сам проставит multipart-границу; свой Content-Type её сломает
        headers.pop("Content-Type", None)
        try:
            r = requests.post(url, headers=headers,
                              files={"attachment": (filename, file_bytes)},
                              timeout=PROVIDER_TIMEOUT)
            if r.status_code in (200, 201):
                try:
                    raw = r.json()
                except Exception:
                    raw = {}
                logger.info("StormTrade confirm_transfer %s: чек принят", invoice_id)
                return {"ok": True, "raw": raw}
            logger.warning("StormTrade confirm_transfer %s: HTTP %s %s",
                           invoice_id, r.status_code, r.text[:200])
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            logger.error(f"StormTrade confirm_transfer failed: {e}")
            return {"ok": False, "error": str(e)}

    def get_payment_options(self) -> list:
        """GET /api/merchant/payment-options -> [{code, name, currency}] или []."""
        url = f"{self.base_url}/api/merchant/payment-options"
        try:
            r = requests.get(url, headers=self._headers("GET", url), timeout=PROVIDER_TIMEOUT)
            return r.json() if r.status_code == 200 else []
        except Exception as e:
            logger.error(f"StormTrade get_payment_options failed: {e}")
            return []

    # ── Прочие обязательные методы ─────────────────────────────────────────────

    def get_payment_methods(self, invoice_id):
        return []

    # ── Вебхук ─────────────────────────────────────────────────────────────────

    def parse_webhook(self, data):
        # {"notificationType": "invoice", "invoice": {"internalId": "...", "status": "paid"}}
        invoice = data.get('invoice') or data
        internal_id = invoice.get('internalId', '') or ''
        order_id = None
        if internal_id.startswith('obsidian_'):
            order_id = internal_id.split('_', 1)[1]
        status = invoice.get('status')
        normalized = {"paid": "paid", "canceled": "failed", "expired": "failed"}.get(status, status)
        if order_id and normalized:
            return order_id, normalized
        return None, None
