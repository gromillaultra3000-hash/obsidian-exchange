import hmac, hashlib, base64, json, os, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

BRABUS_BASE_URL = os.getenv('BRABUS_BASE_URL', 'https://api.brabus.work').rstrip('/')
BRABUS_SECRET = os.getenv('BRABUS_SECRET', '')
BRABUS_NOTIFICATION_TOKEN = os.getenv('BRABUS_NOTIFICATION_TOKEN', '')
PUBLIC_RELAY = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')

# Метки всех известных банков Brabus
BANK_LABELS = {
    "tinkoff":       ("🟡", "Т-Банк"),
    "sberbank":      ("🟢", "Сбербанк"),
    "alfabank":      ("🅰️", "Альфа-Банк"),
    "vtb":           ("🔵", "ВТБ"),
    "gazprombank":   ("🏦", "Газпромбанк"),
    "raiffeisenbank":("🟠", "Райффайзен"),
    "mkb":           ("🏦", "МКБ"),
    "rsb":           ("🏦", "Рус. Стандарт"),
    "promsvyaz":     ("🏦", "Промсвязьбанк"),
    "rosselhozbank": ("🌾", "Россельхоз"),
    "bank_open":     ("🏦", "Открытие"),
    "ubrib":         ("🏦", "УБРиР"),
}

# Варианты: каждый ключ = отдельный магазин в Brabus
# Протестировано на prod: работают только CROSS_BORDER (deeplinks) и VIET_QR.
# classic/with_receipt — нет трейдеров, но оставляем для будущего.
BRABUS_VARIANTS = {
    # ── Deeplink-варианты (CROSS_BORDER) ────────────────────────────────────────
    # Один инвойс возвращает deeplinks сразу для трёх банков: Сбер + Альфа + Т-Банк
    "tbank_deeplink": {
        "key_env": "BRABUS_KEY_TBANK_DEEPLINK",
        "method": "tinkoff",
        "option": "CROSS_BORDER",
        "label": "Т-Банк (deeplink)",
        "is_deeplink": True,
    },
    "alfa_deeplink": {
        "key_env": "BRABUS_KEY_ALFA_DEEPLINK",
        "method": "alfabank",
        "option": "CROSS_BORDER",
        "label": "Альфа-Банк (deeplink)",
        "is_deeplink": True,
    },
    # Сбер переиспользует tbank-ключ — CROSS_BORDER возвращает deeplinks для всех трёх банков
    "sber_deeplink": {
        "key_env": "BRABUS_KEY_TBANK_DEEPLINK",
        "method": "sberbank",
        "option": "CROSS_BORDER",
        "label": "Сбербанк (deeplink)",
        "is_deeplink": True,
    },
    # ── VietQR ─────────────────────────────────────────────────────────────────
    "vietqr": {
        "key_env": "BRABUS_KEY_VIETQR",
        "method": None,
        "option": "VIET_QR",
        "label": "VietQR (Sber/VTB)",
    },
    # ── Классика (нет трейдеров, резерв) ───────────────────────────────────────
    "classic": {
        "key_env": "BRABUS_KEY_CLASSIC",
        "method": None,
        "option": "SBP",
        "label": "Классика СБП",
    },
    "classic_card": {
        "key_env": "BRABUS_KEY_CLASSIC",
        "method": None,
        "option": "TO_CARD",
        "label": "Классика Карта",
    },
    "with_receipt": {
        "key_env": "BRABUS_KEY_WITH_RECEIPT",
        "method": None,
        "option": "TO_CARD",
        "label": "Карта с чеком",
    },
}

# Порядок вариантов для попытки cancel_any (наиболее вероятные первыми)
_CANCEL_PRIORITY = ["tbank_deeplink", "alfa_deeplink", "vietqr", "classic", "with_receipt"]


class BrabusProvider(PaymentProvider):
    def __init__(self, variant="tbank_deeplink"):
        if variant not in BRABUS_VARIANTS:
            raise ValueError(f"Unknown Brabus variant: {variant}")
        self.variant = variant
        cfg = BRABUS_VARIANTS[variant]
        self.api_key = os.getenv(cfg["key_env"], "")
        self.default_method = cfg["method"]
        self.default_option = cfg["option"]
        self.label = cfg["label"]
        self.is_deeplink = cfg.get("is_deeplink", False)

    # ── Авторизация ────────────────────────────────────────────────────────────

    def _sign(self, method, url, body=""):
        # Для GET и multipart: body пустая строка (по доке Brabus)
        string_to_sign = f"{method}{url}{body}"
        h = hmac.new(BRABUS_SECRET.encode(), string_to_sign.encode(), hashlib.sha1)  # noqa: S324
        return base64.b64encode(h.digest()).decode()

    def _headers(self, method, url, body=""):
        return {
            "X-Identity": self.api_key,
            "X-Signature": self._sign(method, url, body),
            "Content-Type": "application/json",
        }

    def _headers_multipart(self, url):
        # Для multipart/form-data подпись без тела (по доке)
        return {
            "X-Identity": self.api_key,
            "X-Signature": self._sign("POST", url),
        }

    # ── Создание инвойса (Сценарий A — прямой запрос реквизитов) ───────────────

    def create_invoice(self, order_id, amount, payment_method=None):
        if not self.api_key or not BRABUS_SECRET:
            return {"error": "Brabus: не настроены API-ключи"}

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
            "paymentOption": self.default_option,
        }
        body = json.dumps(payload, separators=(',', ':'))
        try:
            r = requests.post(url, data=body.encode(),
                              headers=self._headers("POST", url, body),
                              timeout=PROVIDER_TIMEOUT)
            if r.status_code != 200:
                logger.error(f"Brabus[{self.variant}] create error {r.status_code}: {r.text[:300]}")
                return {"error": f"Brabus HTTP {r.status_code}"}

            data = r.json()
            deals = data.get("deals") or []
            deeplinks = data.get("deeplinks") or {}
            inv_id = data.get("id")

            # ── CROSS_BORDER: извлекаем реальные реквизиты карты из deal ──────────
            # deal.paymentOption=TO_CARD, deal.requisites={requisites: card_number, holder: name}
            if self.is_deeplink:
                if not deals:
                    logger.warning(f"Brabus[{self.variant}] нет deals для {inv_id}")
                    return {"error": "Нет свободных реквизитов, попробуйте другой способ"}

                deal = deals[0]
                deal_req = deal.get("requisites") or {}
                card_number = deal_req.get("requisites") or deal_req.get("card_number") or ""
                holder = deal_req.get("holder") or ""
                bank_code = deal.get("paymentMethod", "")
                # dcbank / foreign card — показываем нейтрально
                if bank_code and bank_code.lower() in ("dcbank", "humo", "uzcard", "click_uz"):
                    bank_name_label = "Карта получателя"
                elif bank_code and bank_code in BANK_LABELS:
                    bank_name_label = BANK_LABELS[bank_code][1]
                else:
                    bank_name_label = bank_code.capitalize() if bank_code else "Карта"

                if not card_number:
                    logger.warning(f"Brabus[{self.variant}] нет card_number в deal: {deal_req}")
                    return {"error": "Нет свободных реквизитов, попробуйте другой способ"}

                raw = {
                    "requisites": {
                        "card_number": card_number,
                        "bank_name": bank_name_label,
                        "recipient": holder,
                    },
                    "invoice_id": inv_id,
                    "deal_id": deal.get("id"),
                    "qr_image_url": None,
                    "expire_at": data.get("expireAt"),
                }
                return {
                    "invoice_id": inv_id,
                    "amount": amount,
                    "status": "awaiting_payment",
                    "qr_payload": None,
                    "banks": [],
                    "raw": raw,
                }

            # ── Обычные реквизиты (SBP / TO_CARD / VIET_QR) ───────────────────
            if not deals:
                logger.warning(f"Brabus[{self.variant}] нет deals для order {order_id}")
                return {"error": "Нет свободных реквизитов, попробуйте другой способ"}

            deal = deals[0]
            requisites = {}
            req_text = (deal.get("requisites") or {}).get("requisites")
            holder = (deal.get("requisites") or {}).get("holder")
            deal_option = deal.get("paymentOption", "")

            if deal_option in ("VIET_QR", "SBP_QR", "MANUAL_SBP_QR", "CLICK_UZ_QR"):
                requisites["qr_data"] = req_text
            elif deal_option in ("SBP", "TO_PHONE_NUMBER", "MOBILE_TOP_UP"):
                requisites["phone"] = req_text
            else:
                requisites["card_number"] = req_text

            if holder:
                requisites["recipient"] = holder

            bank_code = deal.get("paymentMethod", "")
            if bank_code and bank_code in BANK_LABELS:
                requisites["bank_name"] = BANK_LABELS[bank_code][1]
            elif deal.get("paymentMethodName"):
                requisites["bank_name"] = deal["paymentMethodName"]

            qr_code_link = deal.get("qrCodeLink")
            if qr_code_link and deal_option not in ("VIET_QR", "SBP_QR"):
                requisites["payment_link"] = qr_code_link

            # Telegram не принимает SVG — конвертируем в PNG
            qr_image_url = None
            if deal_option == "VIET_QR" and qr_code_link:
                qr_image_url = qr_code_link.replace("format=svg", "format=png")

            raw = {
                "requisites": requisites,
                "invoice_id": inv_id,
                "deal_id": deal.get("id"),
                "qr_image_url": qr_image_url,
                "expire_at": data.get("expireAt"),
            }
            return {
                "invoice_id": inv_id,
                "amount": amount,
                "status": "awaiting_payment",
                "qr_payload": qr_code_link,
                "banks": [],
                "raw": raw,
            }
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] create_invoice failed: {e}")
            return {"error": str(e)}

    # ── Статус инвойса ─────────────────────────────────────────────────────────

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
            return {"status": normalized, "raw_status": status, "raw": data}
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] get_status failed: {e}")
            return {"status": "unknown"}

    # ── Отмена инвойса ─────────────────────────────────────────────────────────

    def cancel_order(self, invoice_id: str) -> bool:
        """Отменяет инвойс. Возвращает True если успешно."""
        if not invoice_id or not self.api_key:
            return False
        url = f"{BRABUS_BASE_URL}/api/merchant/invoices/{invoice_id}/cancel"
        try:
            r = requests.post(url, headers=self._headers("POST", url),
                              timeout=PROVIDER_TIMEOUT)
            if r.status_code == 200:
                logger.info(f"Brabus[{self.variant}] cancelled {invoice_id}")
                return True
            logger.warning(f"Brabus[{self.variant}] cancel {invoice_id}: HTTP {r.status_code}")
            return False
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] cancel_order failed: {e}")
            return False

    @classmethod
    def cancel_any(cls, invoice_id: str) -> bool:
        """
        Пробует отменить инвойс через все доступные ключи.
        Нужно когда не знаем каким ключом был создан инвойс.
        """
        for variant in _CANCEL_PRIORITY:
            try:
                p = cls(variant=variant)
                if not p.api_key:
                    continue
                if p.cancel_order(invoice_id):
                    return True
            except Exception:
                pass
        logger.warning(f"Brabus: не удалось отменить {invoice_id} ни одним ключом")
        return False

    # ── Подтверждение перевода (matching / with_receipt) ───────────────────────

    def confirm_transfer(self, invoice_id: str, file_bytes: bytes, filename="receipt.jpg") -> dict:
        """
        Отправляет файл-подтверждение перевода.
        Для multipart/form-data подпись формируется без тела (по доке Brabus).
        """
        if not invoice_id:
            return {"ok": False, "error": "Нет invoice_id"}
        url = f"{BRABUS_BASE_URL}/api/merchant/invoices/{invoice_id}/confirm-transfer"
        try:
            r = requests.post(
                url,
                headers=self._headers_multipart(url),
                files={"attachment": (filename, file_bytes)},
                timeout=PROVIDER_TIMEOUT,
            )
            if r.status_code in (200, 201):
                return {"ok": True, "raw": r.json()}
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] confirm_transfer failed: {e}")
            return {"ok": False, "error": str(e)}

    # ── Список доступных вариантов оплаты (Сценарий Б) ────────────────────────

    def get_available_variants(self, invoice_id: str) -> list:
        """
        GET /api/merchant/invoices/{id}/available-payment-variants
        Возвращает список [{option, method}] или [].
        Используется в двухшаговом сценарии (case-b).
        """
        if not invoice_id:
            return []
        url = f"{BRABUS_BASE_URL}/api/merchant/invoices/{invoice_id}/available-payment-variants"
        try:
            r = requests.get(url, headers=self._headers("GET", url), timeout=PROVIDER_TIMEOUT)
            if r.status_code == 200:
                return r.json() or []
            return []
        except Exception as e:
            logger.error(f"Brabus[{self.variant}] get_available_variants failed: {e}")
            return []

    # ── Прочие обязательные методы ─────────────────────────────────────────────

    def get_payment_methods(self, invoice_id):
        return []

    # ── Вебхук ─────────────────────────────────────────────────────────────────

    def parse_webhook(self, data):
        # Структура: {"notificationType": "invoice", "invoice": {"internalId": "...", "status": "paid"}}
        invoice = data.get('invoice') or data
        internal_id = invoice.get('internalId', '') or ''
        order_id = None
        if internal_id.startswith('obsidian_'):
            order_id = internal_id.split('_', 1)[1]
        status = invoice.get('status')
        normalized_status = {
            "paid": "paid",
            "canceled": "failed",
            "expired": "failed",
        }.get(status, status)
        if order_id and normalized_status:
            return order_id, normalized_status
        return None, None
