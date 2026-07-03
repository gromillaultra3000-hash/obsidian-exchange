import hmac, hashlib, base64, json, os, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

BRABUS_BASE_URL = os.getenv('BRABUS_BASE_URL', 'https://api.brabus.work').rstrip('/')
BRABUS_SECRET = os.getenv('BRABUS_SECRET', '')
BRABUS_NOTIFICATION_TOKEN = os.getenv('BRABUS_NOTIFICATION_TOKEN', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')

# Каждый ключ Brabus = отдельный "магазин" со своей предустановленной конфигурацией.
# method/option передаются явно в запросе (без этого система может подобрать
# случайный кроссбордер-канал вместо обычного рублёвого перевода).
BRABUS_VARIANTS = {
    "classic": {
        "key_env": "BRABUS_KEY_CLASSIC",
        "method": None,        # любой банк из пула
        "option": "SBP",
        "label": "Классика (СБП)",
    },
    "classic_card": {
        "key_env": "BRABUS_KEY_CLASSIC",
        "method": None,
        "option": "TO_CARD",
        "label": "Классика (карта)",
    },
    "classic_vtb": {
        "key_env": "BRABUS_KEY_CLASSIC_VTB",
        "method": "vtb",
        "option": "SBP",
        "label": "Классика ВТ (ВТБ СБП)",
    },
    "alfa_deeplink": {
        "key_env": "BRABUS_KEY_ALFA_DEEPLINK",
        "method": "alfabank",
        "option": "CROSS_BORDER",  # по рекомендации менеджера Brabus — обычный SBP/TO_CARD не выдаёт deeplink
        "label": "Альфа-Банк (deeplink)",
        "is_deeplink": True,
    },
    "tbank_deeplink": {
        "key_env": "BRABUS_KEY_TBANK_DEEPLINK",
        "method": "tinkoff",
        "option": "CROSS_BORDER",
        "label": "Т-Банк (deeplink)",
        "is_deeplink": True,
    },
    "with_receipt": {
        "key_env": "BRABUS_KEY_WITH_RECEIPT",
        "method": None,
        "option": "TO_CARD",
        "label": "Карта (с подтверждением чеком)",
    },
    "vietqr": {
        "key_env": "BRABUS_KEY_VIETQR",
        "method": None,
        "option": "VIET_QR",
        "label": "VietQR (Sber/VTB)",
    },
}

# payment_method (как передаётся из main_bot.py) -> переопределение paymentOption
_METHOD_OPTION_OVERRIDE = {
    "sbp": "SBP",
    "card": "TO_CARD",
}


class BrabusProvider(PaymentProvider):
    def __init__(self, variant="classic"):
        if variant not in BRABUS_VARIANTS:
            raise ValueError(f"Unknown Brabus variant: {variant}")
        self.variant = variant
        cfg = BRABUS_VARIANTS[variant]
        self.api_key = os.getenv(cfg["key_env"], "")
        self.default_method = cfg["method"]
        self.default_option = cfg["option"]
        self.label = cfg["label"]
        self.is_deeplink = cfg.get("is_deeplink", False)

    def _sign(self, method, url, body=""):
        string_to_sign = f"{method}{url}{body}"
        h = hmac.new(BRABUS_SECRET.encode(), string_to_sign.encode(), hashlib.sha1)
        return base64.b64encode(h.digest()).decode()

    def _headers(self, method, url, body=""):
        return {
            "X-Identity": self.api_key,
            "X-Signature": self._sign(method, url, body),
            "Content-Type": "application/json",
        }

    def create_invoice(self, order_id, amount, payment_method=None):
        if not self.api_key or not BRABUS_SECRET:
            return {"error": "Brabus: не настроены API-ключи"}

        option = _METHOD_OPTION_OVERRIDE.get(payment_method, self.default_option)
        url = f"{BRABUS_BASE_URL}/api/merchant/invoices"
        payload = {
            "type": "in",
            "amount": f"{float(amount):.2f}",
            "currency": "RUB",
            "notificationUrl": f"{PUBLIC_RELAY}/brabus/webhook",
            "notificationToken": BRABUS_NOTIFICATION_TOKEN,
            "internalId": f"obsidian_{order_id}",
            "startDeal": True,
            "paymentMethod": self.default_method,
            "paymentOption": option,
        }
        body = json.dumps(payload, separators=(',', ':'))
        try:
            r = requests.post(url, data=body.encode(), headers=self._headers("POST", url, body), timeout=PROVIDER_TIMEOUT)
            if r.status_code != 200:
                logger.error(f"Brabus[{self.variant}] error {r.status_code}: {r.text[:300]}")
                return {"error": f"Brabus error: {r.status_code}"}
            data = r.json()
            deals = data.get("deals") or []
            deeplinks = data.get("deeplinks") or {}

            # Deeplink-варианты (Alfa/T-Bank): CROSS_BORDER даёт deals от таджикских
            # трейдеров + deeplinks для оплаты через российские банковские приложения.
            # deeplink_url храним отдельно от requisites, чтобы format_requisites
            # не вставлял длинный URL прямо в текст сообщения.
            if self.is_deeplink:
                deeplink_url = (deeplinks or {}).get(self.default_method)
                if not deeplink_url or not deals:
                    logger.warning(f"Brabus[{self.variant}] нет deeplink/deals для {self.default_method}: {data.get('id')}, deals={len(deals)}")
                    return {"error": "Нет свободных реквизитов для оплаты, попробуйте другой способ"}
                raw = {
                    "requisites": {"bank_name": self.label},
                    "deeplink_url": deeplink_url,
                    "invoice_id": data.get("id"),
                    "deal_id": deals[0].get("id"),
                    "qr_image_url": None,
                    "expire_at": data.get("expireAt"),
                }
                return {
                    "invoice_id": data.get("id"),
                    "amount": amount,
                    "status": "awaiting_payment",
                    "qr_payload": deeplink_url,
                    "banks": [],
                    "raw": raw,
                }

            if not deals:
                logger.warning(f"Brabus[{self.variant}] нет свободных реквизитов для order {order_id}: {data.get('id')}")
                return {"error": "Нет свободных реквизитов для оплаты, попробуйте другой способ"}

            deal = deals[0]
            requisites = {}
            req_text = (deal.get("requisites") or {}).get("requisites")
            holder = (deal.get("requisites") or {}).get("holder")
            deal_option = deal.get("paymentOption")

            if deal_option in ("VIET_QR", "SBP_QR", "CLICK_UZ_QR"):
                requisites["qr_data"] = req_text
            elif deal_option in ("SBP", "TO_PHONE_NUMBER", "MOBILE_TOP_UP"):
                requisites["phone"] = req_text
            else:
                requisites["card_number"] = req_text

            if holder:
                requisites["recipient"] = holder
            if deal.get("paymentMethodName"):
                requisites["bank_name"] = deal["paymentMethodName"]

            qr_code_link = deal.get("qrCodeLink")
            if qr_code_link and deal_option != "VIET_QR":
                requisites["payment_link"] = qr_code_link

            # Telegram не принимает SVG — конвертируем ссылку qrserver.com в PNG
            qr_image_url = None
            if deal_option == "VIET_QR" and qr_code_link:
                qr_image_url = qr_code_link.replace("format=svg", "format=png")

            raw = {
                "requisites": requisites,
                "invoice_id": data.get("id"),
                "deal_id": deal.get("id"),
                "qr_image_url": qr_image_url,
                "expire_at": data.get("expireAt"),
            }
            return {
                "invoice_id": data.get("id"),
                "amount": amount,
                "status": "awaiting_payment",
                "qr_payload": qr_code_link,
                "banks": [],
                "raw": raw,
            }
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] request failed: {e}")
            return {"error": str(e)}

    def get_status(self, invoice_id):
        if not invoice_id:
            return {"status": "unknown"}
        url = f"{BRABUS_BASE_URL}/api/merchant/invoices/{invoice_id}"
        try:
            r = requests.get(url, headers=self._headers("GET", url), timeout=PROVIDER_TIMEOUT)
            if r.status_code != 200:
                return {"status": "unknown"}
            data = r.json()
            status = data.get("status")
            normalized = {
                "new": "awaiting_payment",
                "paid": "paid",
                "canceled": "failed",
                "expired": "failed",
                "dispute": "dispute",
            }.get(status, status or "unknown")
            return {"status": normalized, "raw": data}
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] status check failed: {e}")
            return {"status": "unknown"}

    def get_payment_methods(self, invoice_id):
        return []

    def confirm_transfer(self, invoice_id, file_bytes, filename="receipt.jpg"):
        """Загружает чек подтверждения перевода (для варианта with_receipt / matching)."""
        url = f"{BRABUS_BASE_URL}/api/merchant/invoices/{invoice_id}/confirm-transfer"
        try:
            r = requests.post(
                url,
                headers={"X-Identity": self.api_key, "X-Signature": self._sign("POST", url)},
                files={"attachment": (filename, file_bytes)},
                timeout=PROVIDER_TIMEOUT,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "raw": r.json()}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] confirm_transfer failed: {e}")
            return {"ok": False, "error": str(e)}

    def parse_webhook(self, data):
        internal_id = data.get('internalId', '') or ''
        order_id = None
        if internal_id.startswith('obsidian_'):
            order_id = internal_id.split('_', 1)[1]
        status = data.get('status')
        normalized_status = {
            "paid": "paid",
            "canceled": "failed",
            "expired": "failed",
        }.get(status, status)
        if order_id and normalized_status:
            return order_id, normalized_status
        return None, None
