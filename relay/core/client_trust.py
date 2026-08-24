"""Сколько сделок клиент должен закрыть, чтобы попасть к тому или иному провайдеру.

Зачем модуль. У P2P-агрегаторов реквизиты выдают живые трейдеры, и скам по
поддельному чеку бьёт по ним. Провайдеры это видят и защищаются требованием:
«направляйте нам только проверенных клиентов». У Montera это ≥1 закрытая
сделка (правило жило прямо в коде бота и отдельной копией в PaymentService),
у Vertu с 06.08.2026 — ≥4: они жалуются на поток заявок с поддельными PDF.

Правило одно на все входы к провайдеру, и это здесь главное. Спрятать кнопку
в боте мало: тот же провайдер выбирается авто-роутером, подключается
эскалацией и достаётся сайту с Mini App через общий `create_session`. Порог,
записанный только у кнопки, означает, что новичок всё равно доедет до трейдера
— просто другой дорогой, и провайдер увидит ровно то, на что жаловался.

Fail-closed по неизвестному клиенту: нет Telegram-идентификатора (заявка с
сайта без привязки) — считаем ноль сделок. Ошибиться в эту сторону значит
показать проверенному клиенту другой канал; в обратную — отправить к трейдеру
того, за кого мы поручиться не можем.
"""
from __future__ import annotations

import logging
import os
import time
from repositories.operational_read_store import from_environment as _read_store_from_environment

logger = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Статусы, означающие «клиент реально заплатил». Тот же набор, по которому
# считается рейтинг, отправляемый провайдерам: расхождение здесь означало бы,
# что мы обещаем провайдеру одно число, а гейтим по другому.
PAID_STATUSES = ("paid", "sent", "completed")

# Счёт на клиента живёт секунды: за один показ меню и создание заявки он
# спрашивается несколько раз, а меняется от силы раз в день.
_CACHE_TTL = 30.0
_cache: dict = {}
def _store():return _read_store_from_environment(sqlite_path=DB_PATH)


def paid_deals(telegram_id, use_cache: bool = True) -> int:
    """Сколько заявок клиент довёл до оплаты. Неизвестный клиент — ноль."""
    try:
        tid = int(telegram_id)
    except (TypeError, ValueError):
        return 0
    # Отрицательный id — веб-аккаунт без привязки к Telegram. Его история не
    # связана с человеком, за которого мы ручаемся перед трейдером.
    if tid <= 0:
        return 0
    now = time.time()
    if use_cache:
        hit = _cache.get(tid)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    try:
        n = _store().paid_deals(tid, PAID_STATUSES)
    except Exception as e:
        # База недоступна — не выдумываем клиенту заслуги: ноль отправит его к
        # менее требовательному каналу, а не к трейдеру, который нас об этом
        # просил не делать.
        logger.warning("счёт сделок клиента %s недоступен: %s", tid, e)
        return 0
    _cache[tid] = (now, n)
    return n


def _short(provider_class: str) -> str:
    from services.smart_router import SHORT_NAMES
    return SHORT_NAMES.get(provider_class, provider_class.lower())


def min_deals(provider_class: str) -> int:
    """Порог провайдера. Реестр — один, переменная окружения его перекрывает.

    `MIN_DEALS_<КОРОТКОЕ_ИМЯ>` (например `MIN_DEALS_VERTU=4`) нужен потому, что
    требование приходит письмом от провайдера и меняется без нашего релиза:
    держать его только в коде значит ждать выкатки, пока провайдер считает нас
    источником скама.
    """
    from services.smart_router import PROVIDER_CONFIG
    env = os.getenv(f"MIN_DEALS_{_short(provider_class).upper()}", "").strip()
    if env:
        try:
            return max(0, int(env))
        except ValueError:
            logger.warning("MIN_DEALS_%s = %r — не число, беру значение реестра",
                           _short(provider_class).upper(), env)
    return int(PROVIDER_CONFIG.get(provider_class, {}).get("min_client_deals", 0) or 0)


def allows(provider_class: str, telegram_id) -> bool:
    """Можно ли этому клиенту показывать реквизиты этого провайдера."""
    need = min_deals(provider_class)
    if need <= 0:
        return True
    return paid_deals(telegram_id) >= need


def refuse_reason(provider_class: str, telegram_id) -> str:
    """Причина отказа для журнала или '' — понятная человеку, не коду."""
    need = min_deals(provider_class)
    if need <= 0:
        return ""
    have = paid_deals(telegram_id)
    if have >= need:
        return ""
    return (f"{provider_class} принимает только клиентов от {need} закрытых "
            f"сделок, у клиента {have}")


def forget(telegram_id=None) -> None:
    """Сбросить кеш счёта — после того, как заявка закрылась оплаченной."""
    if telegram_id is None:
        _cache.clear()
        return
    try:
        _cache.pop(int(telegram_id), None)
    except (TypeError, ValueError):
        pass
