import os, json, hmac, hashlib, requests
from providers.base import PaymentProvider
from config.config import PROVIDER_TIMEOUT
from utils.logger import get_logger

logger = get_logger(__name__)

LAVA_BASE_URL = 'https://api.lava.ru'
PUBLIC_RELAY   = os.getenv('PUBLIC_RELAY', 'https://obsidian-exchange.org')
LAVA_SHOP_ID   = os.getenv('LAVA_SHOP_ID', '')
LAVA_SECRET_KEY = os.getenv('LAVA_SECRET_KEY', '')
LAVA_ADDITIONAL_KEY = os.getenv('LAVA_ADDITIONAL_KEY', '')   # для проверки вебхуков


class LavaProvider(PaymentProvider):
    def __init__(self):
        self.shop_id    = LAVA_SHOP_ID
        self.secret_key = LAVA_SECRET_KEY
        self.add_key    = LAVA_ADDITIONAL_KEY
        self.base_url   = LAVA_BASE_URL

    # ── Подпись ──────────────────────────────────────────────────────────────
    def _sign(self, body: dict) -> str:
        # Сортируем ключи алфавитно — именно так доки требуют порядок полей
        ordered = dict(sorted(body.items()))
        json_str = json.dumps(ordered, ensure_ascii=False, separators=(',', ':'))
        return hmac.new(
            self.secret_key.encode('utf-8'),
            json_str.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

    def _verify_webhook_sign(self, body: dict, received_sign: str) -> bool:
        ordered = dict(sorted(body.items()))
        json_str = json.dumps(ordered, ensure_ascii=False, separators=(',', ':'))
        expected = hmac.new(
            self.add_key.encode('utf-8'),
            json_str.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, received_sign)

    def _headers(self, signature: str) -> dict:
        return {
            'Content-Type': 'application/json',
            'Accept':       'application/json',
            'Signature':    signature,
        }

    # ── Создание инвойса ──────────────────────────────────────────────────────
    def create_invoice(self, order_id, amount, payment_method=None, user_id=None):
        """
        payment_method: 'sbp' | 'card' | None (оба)
        Возвращает dict с payment_url для кнопки в боте.
        """
        if payment_method == 'sbp':
            services = ['sbp']
        elif payment_method == 'card':
            services = ['bank_card']
        else:
            services = ['sbp', 'bank_card']

        body = {
            'comment':        f'Обмен #{order_id}',
            'expire':         30,
            'failUrl':        f'{PUBLIC_RELAY}/pay/fail',
            'hookUrl':        f'{PUBLIC_RELAY}/lava/webhook',
            'includeService': services,
            'orderId':        f'obsidian_{order_id}',
            'shopId':         self.shop_id,
            'successUrl':     f'{PUBLIC_RELAY}/pay/success',
            'sum':            float(round(amount, 2)),
        }
        signature = self._sign(body)

        try:
            r = requests.post(
                f'{self.base_url}/business/invoice/create',
                json=body,
                headers=self._headers(signature),
                timeout=PROVIDER_TIMEOUT,
            )
            data = r.json()

            if r.status_code not in (200, 201) or not data.get('status_check'):
                err = data.get('error') or f'HTTP {r.status_code}'
                logger.error(f'Lava invoice create error: {err} | body={body}')
                return {'error': str(err)}

            inner       = data.get('data', {})
            invoice_id  = inner.get('id')
            payment_url = inner.get('url')

            if not payment_url:
                return {'error': 'Lava: no payment URL in response'}

            return {
                'invoice_id':   invoice_id,
                'amount':       amount,
                'status':       'awaiting_payment',
                'payment_url':  payment_url,
                'qr_payload':   None,
                'requisites':   {'payment_url': payment_url},
                'raw':          inner,
            }
        except Exception as e:
            logger.error(f'Lava create_invoice exception: {e}')
            return {'error': str(e)}

    # ── Статус ────────────────────────────────────────────────────────────────
    def get_status(self, invoice_id: str) -> dict:
        body = {'invoiceId': invoice_id, 'shopId': self.shop_id}
        signature = self._sign(body)
        try:
            r = requests.post(
                f'{self.base_url}/business/invoice/status',
                json=body,
                headers=self._headers(signature),
                timeout=10,
            )
            return r.json()
        except Exception as e:
            logger.error(f'Lava get_status exception: {e}')
            return {'error': str(e)}

    # ── Вебхук ────────────────────────────────────────────────────────────────
    def parse_webhook(self, data: dict) -> tuple:
        """
        Lava webhook payload:
          id, orderId, status (1=paid/success, 2=cancelled), paymentAmount, shopId
        Возвращает (obsidian_order_id, status_string)
        """
        order_ref = data.get('orderId', '')         # 'obsidian_1234'
        order_id  = order_ref.replace('obsidian_', '') if order_ref.startswith('obsidian_') else None
        raw_status = data.get('status')

        # Lava: 1 = оплачен, 2 = отменён/просрочен
        if raw_status == 1 or raw_status == 'success':
            status = 'paid'
        elif raw_status in (2, 'cancelled', 'expired'):
            status = 'cancelled'
        else:
            status = 'pending'

        return order_id, status

    # ── Прочие обязательные методы ────────────────────────────────────────────
    def get_payment_methods(self, invoice_id):
        return []

    def check_health(self) -> bool:
        return bool(self.shop_id and self.secret_key)
