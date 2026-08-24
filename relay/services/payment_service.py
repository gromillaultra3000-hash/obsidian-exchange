import os, time
from datetime import datetime, timedelta
from providers.fallback import FallbackProvider
from utils.tokens import generate_session_token
from utils.logger import get_logger
from services.state_machine import PaymentStateMachine
from services.requisite_guard import test_requisite_reason
from services.capacity import shortfall_message
from services.smart_router import (choose_provider, record_outcome, get_health_scores,
                                   get_escalation_chain, CLASS_BY_SHORT, PROVIDER_CONFIG,
                                   is_provider_disabled, is_no_trader_error,
                                   is_provider_retired, has_required_env,
                                   client_trust_refusal)
from repositories.payment_session_store import from_environment as payment_session_store

DB_PATH = os.getenv('DB_PATH', '/root/exchange.db')
logger = get_logger(__name__)


class PaymentService:
    def __init__(self, provider=None, amount=None, telegram_id=None):
        self.sessions = payment_session_store(sqlite_path=DB_PATH)
        if provider is None:
            # Клиент нужен уже на выборе: часть провайдеров работает только с
            # повторными (core.client_trust). Не назван — считаем новым.
            provider_name = choose_provider(amount or 10000, telegram_id=telegram_id)
            self.provider = self._load_provider(provider_name)
        else:
            self.provider = provider

    def _load_provider(self, name: str):
        """Загружает провайдер по имени класса."""
        try:
            if name == 'BrabusProvider':
                from providers.brabus import BrabusProvider
                return BrabusProvider()
            elif name == 'MonteraProvider':
                from providers.montera import MonteraProvider
                return MonteraProvider()
            elif name == 'GreenPayProvider':
                from providers.greenpay import GreenPayProvider
                return GreenPayProvider()
            elif name == 'LavaProvider':
                from providers.lava import LavaProvider
                return LavaProvider()
            elif name == 'VertuProvider':
                from providers.vertu import VertuProvider
                return VertuProvider()
            elif name == 'StormTradeProvider':
                from providers.stormtrade import StormTradeProvider
                return StormTradeProvider()
            elif name == 'XPayConnectProvider':
                from providers.xpayconnect import XPayConnectProvider
                return XPayConnectProvider()
            elif name == 'RSPayProvider':
                from providers.rspay import RSPayProvider
                return RSPayProvider()
            else:
                from providers.fallback import FallbackProvider
                return FallbackProvider()
        except Exception as e:
            logger.warning(f"Failed to load {name}: {e}, using Fallback")
            from providers.fallback import FallbackProvider
            return FallbackProvider()

    def _escalate(self, order_id, amount, payment_method, telegram_id, invoice):
        """
        Эскалация, когда выбранный провайдер после ретраев не выдал реквизиты.
        Цепочка конфигурируется через ESCALATION_CHAIN (default: stormtrade,fallback)
        — короткие имена из smart_router.CLASS_BY_SHORT. Возвращает
        (invoice, provider_name | None) — provider_name короткое имя для payment_sessions.

        НЕ гейтим по is_healthy: last-resort провайдеры (StormTrade) исключены из
        weighted-выбора, единственный живой запрос к ним идёт отсюда. Гейт по
        is_healthy = self-heal deadlock (словили 10-11.07): unhealthy никогда не
        получит запрос → никогда не запишет успех. Пытаемся всегда, исход пишет
        record_outcome ниже.
        """
        current_class = self.provider.__class__.__name__
        for short in get_escalation_chain():
            cls_name = CLASS_BY_SHORT.get(short)
            if not cls_name or cls_name == current_class:
                continue
            if is_provider_disabled(cls_name) or is_provider_retired(cls_name):
                continue
            if not has_required_env(cls_name):
                continue
            # Порог доверия обязателен и здесь. Эскалация — это ещё одна дверь
            # к тому же трейдеру: провайдер, попросивший «только повторных
            # клиентов», получил бы новичка запасным путём и увидел бы ровно
            # то, на что жаловался, — просто реже.
            trust_block = client_trust_refusal(cls_name, telegram_id)
            if trust_block:
                logger.info(f"Эскалация order {order_id} мимо {short}: {trust_block}")
                continue
            provider = self._load_provider(cls_name)
            if provider.__class__.__name__ != cls_name and cls_name != 'FallbackProvider':
                # _load_provider упал и вернул Fallback вместо запрошенного — не
                # записываем исход чужому имени, идём дальше по цепочке
                continue

            logger.warning(f"Эскалация order {order_id} на {short}: {invoice.get('error')}")
            start_time = time.time()
            extra = {}
            # Тот же список, что на основном пути. RSPay здесь отсутствовал:
            # при эскалации канал получал `web_<order>` вместо телефона клиента
            # и терял его счётчики сделок — то есть ровно те данные, по которым
            # провайдер отличает знакомого клиента от скамера. Нашёл codex.
            if cls_name in ('MonteraProvider', 'VertuProvider', 'StormTradeProvider',
                            'XPayConnectProvider', 'RSPayProvider'):
                extra['user_id'] = telegram_id
            next_invoice = provider.create_invoice(order_id, amount,
                                                   payment_method=payment_method, **extra)
            if 'error' not in next_invoice:
                _test_reason = test_requisite_reason(next_invoice)
                if _test_reason:
                    logger.error(f"{cls_name} отдал ТЕСТОВЫЕ реквизиты для order {order_id} "
                                 f"({_test_reason}) — идём дальше по цепочке")
                    next_invoice = {"error": f"тестовые реквизиты провайдера ({_test_reason})"}
            # «Нет свободных реквизитов» = нет трейдера под сумму в моменте (API
            # ответил штатно) — НЕ падение провайдера, здоровье не штрафуем, иначе
            # штатное для резерва состояние копит failed_count и врёт на дашборде.
            # Реальные ошибки (auth/сеть/HTTP5xx) — штрафуем.
            err = next_invoice.get('error') or ''
            no_trader = is_no_trader_error(err)
            record_outcome(cls_name, ('error' not in next_invoice) or no_trader,
                           time.time() - start_time, error=err or None)
            if 'error' in next_invoice:
                logger.warning(f"{short} тоже не выдал реквизиты для order {order_id}: {err}")
                continue
            if cls_name == 'BrabusProvider':
                short = f"brabus:{getattr(provider, 'variant', 'tbank_deeplink')}"
            return next_invoice, short
        return invoice, None

    def create_session(self, order_id, amount, client_ip=None, user_agent=None, telegram_id=None, payment_method=None):
        token = generate_session_token()
        expires_at = (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Попытка создать инвойс с retry — для P2P-агрегаторов (Brabus/Montera/GreenPay)
        # окно доступности конкретного реквизита у трейдера может быть очень коротким,
        # поэтому даём больше попыток с увеличенной паузой, прежде чем уходить в fallback.
        max_retries = 3
        invoice = None
        last_error = None
        # Порог доверия — последний рубеж, а не дубль кнопки. Сюда приходит и
        # провайдер, выбранный роутером (там порог уже проверен), и провайдер,
        # НАВЯЗАННЫЙ кнопкой бота: без этой проверки клиент с двумя сделками
        # получал бы реквизиты Vertu по прямой ссылке из старого сообщения —
        # ровно то, на что Vertu жалуется. Дальше заявка уходит в эскалацию и
        # реквизиты всё равно выдаются другим каналом.
        trust_block = client_trust_refusal(self.provider.__class__.__name__, telegram_id)
        if trust_block:
            logger.info(f"order {order_id}: {trust_block}")
        for attempt in range(max_retries):
            if trust_block:
                invoice = {"error": trust_block}
                break
            start_time = time.time()
            extra = {}
            if self.provider.__class__.__name__ in ('MonteraProvider', 'VertuProvider', 'StormTradeProvider', 'XPayConnectProvider', 'RSPayProvider'):
                extra['user_id'] = telegram_id
            invoice = self.provider.create_invoice(order_id, amount, payment_method=payment_method, **extra)
            elapsed = time.time() - start_time

            # Тестовые реквизиты (карта 1111…, получатель «Test Name») = провайдер
            # непригоден, а не «реквизиты выданы». Показать такое клиенту хуже, чем
            # уйти на другой маршрут → превращаем в ошибку до всех проверок ниже,
            # чтобы сработали и штраф здоровью, и эскалация.
            if 'error' not in invoice:
                _test_reason = test_requisite_reason(invoice)
                if _test_reason:
                    logger.error(f"{self.provider.__class__.__name__} отдал ТЕСТОВЫЕ реквизиты "
                                 f"для order {order_id} ({_test_reason}) — клиенту не показываем")
                    invoice = {"error": f"тестовые реквизиты провайдера ({_test_reason})"}

            # Обновляем метрики здоровья провайдера через smart_router.
            # «Нет трейдера под сумму в моменте» (API ответил штатно, напр. Vertu
            # «Не удалось выдать сделку» на суммах без свободного трейдера) — НЕ
            # падение провайдера: не штрафуем здоровье, иначе провайдер выпадает из
            # выбора целиком, хотя на других суммах реквизиты есть.
            err = invoice.get('error') or ''
            is_error = 'error' in invoice
            no_trader = is_error and is_no_trader_error(err)
            record_outcome(self.provider.__class__.__name__,
                           (not is_error) or no_trader, elapsed,
                           error=err or None)

            if not is_error:
                break
            last_error = err
            logger.warning(f"Попытка {attempt+1}/{max_retries} для order {order_id} не удалась: {last_error}")
            # нет трейдера в моменте ретраем не лечится (доступность не изменится за
            # секунды) — сразу к эскалации, не задерживая клиента
            if no_trader:
                break
            if attempt < max_retries - 1:
                time.sleep(2.5)  # пауза перед повторной попыткой
        
        if invoice is None or 'error' in invoice:
            logger.error(f"Все попытки создать инвойс для order {order_id} не удались")
            invoice = invoice or {"error": last_error or "Unknown error"}
        if 'error' in invoice:
            # Цепочка эскалации (ESCALATION_CHAIN, default stormtrade→fallback) —
            # только когда выбранный провайдер после ретраев не выдал реквизиты
            invoice, provider_name = self._escalate(order_id, amount, payment_method,
                                                    telegram_id, invoice)
            if provider_name is None or 'error' in invoice:
                logger.error(f"Вся цепочка эскалации не выдала реквизиты для order {order_id}: "
                             f"{invoice.get('error')}")
                self.sessions.create_failed(token=token, order_id=order_id, amount=amount,
                                            provider='fallback')
                # «All providers failed» клиенту ничего не объясняет: он не знает,
                # что дело в сумме, и уходит. Если живые лимиты трейдеров говорят,
                # что сумма выше потолка — называем потолок. Если лимиты неизвестны
                # (или сумма проходит) — не выдумываем причину.
                hint = shortfall_message(amount, payment_method)
                if hint:
                    logger.info(f"Order {order_id}: сумма {amount} выше живой ёмкости — подсказка клиенту")
                # client_hint=True — текст написан ДЛЯ клиента и его можно показать
                # как есть. Без флага вызывающий не отличит его от сырой ошибки
                # провайдера («Не удалось выдать сделку»), которую показывать нельзя.
                return {"error": hint or "All providers failed", "client_hint": bool(hint)}
            logger.info(f"Order {order_id}: реквизиты выданы эскалацией через {provider_name}")
        else:
            if self.provider.__class__.__name__ == 'BrabusProvider':
                # Сохраняем вариант для корректного cancel при истечении заявки
                provider_name = f'brabus:{getattr(self.provider, "variant", "tbank_deeplink")}'
            else:
                provider_names = {'PlategaProvider': 'platega', 'GreenPayProvider': 'greenpay',
                                  'MonteraProvider': 'montera', 'LavaProvider': 'lava',
                                  'VertuProvider': 'vertu', 'StormTradeProvider': 'stormtrade',
                                  'XPayConnectProvider': 'xpay',
                                  'RSPayProvider': 'rspay'}
                provider_name = provider_names.get(self.provider.__class__.__name__, 'platega')

        self.sessions.create_invoice(
            token=token, order_id=order_id, amount=amount, provider=provider_name,
            expires_at=expires_at, client_ip=client_ip, user_agent=user_agent,
            telegram_id=telegram_id, invoice_id=invoice.get('invoice_id'),
            qr_payload=invoice.get('qr_payload'), provider_payload=str(invoice.get('raw', {})))

        logger.info(f"Session {token[:8]}… created for order {order_id}")
        return {
            "session_token": token,
            "invoice_id": invoice.get('invoice_id'),
            "qr_payload": invoice.get('qr_payload'),
            "banks": invoice.get('banks', []),
            "amount": amount,
            "raw": invoice.get('raw', {})
        }

    def get_session(self, token):
        return self.sessions.get(token)

    def update_status(self, token, new_status):
        session = self.get_session(token)
        if not session:
            return False
        current_status = session['status']
        try:
            PaymentStateMachine.transition(current_status, new_status)
        except ValueError as e:
            logger.error(f"Invalid state transition: {e}")
            return False
        
        try:
            return self.sessions.transition(token, new_status)
        except ValueError as e:
            logger.error(f"Invalid concurrent state transition: {e}")
            return False

    def get_payment_methods(self, token):
        session = self.get_session(token)
        if not session:
            return []
        return self.provider.get_payment_methods(session.get('provider_invoice_id'))


    def get_provider_status(self) -> dict:
        """Возвращает health scores всех провайдеров из smart_router."""
        return get_health_scores()
