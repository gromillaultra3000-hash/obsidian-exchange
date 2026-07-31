"""Кошелёк TON — наблюдение за счётом владельца, без права подписи.

Зачем он нужен, если отправлять им нельзя. Монету нельзя открыть клиенту, пока
владелец не подтвердил ликвидность (`/setreserve TON N`), а подтверждать её он
может только по факту: сколько на счету сейчас. До этого модуля TON был
единственной валютой реестра, чей баланс не показывался нигде — резерв
задавался бы вслепую. Ровно так же начинали BTC/LTC: сперва watch-only, право
подписи появилось потом.

Почему подписи нет и не будет по-тихому. В окружении бота нет ни одной
библиотеки TON (`tonsdk`, `pytoniq`) и нет даже ed25519 (`nacl`), а ставить их
в БОЕВОЙ venv ради «на будущее» — менять прод под неготовую функцию. Поэтому
`send()` здесь не заглушка, которая когда-нибудь заработает, а явный отказ:
пока `payouts_enabled()` выключен и подписывающей библиотеки нет, TON выдаётся
человеком, и код обязан говорить об этом прямо, а не возвращать «успех» без
транзакции.

Секретов модуль не читает и не хранит. Единственная настройка — адрес счёта
владельца в `TON_PAYOUT_ADDRESS`; он же используется сверкой выплат, чтобы
собственный перевод не выглядел чужим.
"""
from __future__ import annotations

import os
from typing import Any, Dict

# ── адрес сервиса toncenter ──────────────────────────────────────────────────
# Одна точка на весь проект. Историческая переменная TON_API_URL указывает на
# КОНКРЕТНЫЙ метод (…/getTransactions) — её значение продолжаем понимать, иначе
# владелец, переопределивший адрес ради своего узла, получил бы сверку по
# своему узлу и баланс по публичному, то есть две разные правды об одном счёте.
_DEFAULT_BASE = "https://toncenter.com/api/v2"


def api_url(method: str) -> str:
    """Полный адрес метода toncenter с учётом переопределения владельцем."""
    base = os.getenv("TON_API_BASE", "").strip().rstrip("/")
    if not base:
        legacy = os.getenv("TON_API_URL", "").strip().rstrip("/")
        # …/getTransactions → …/api/v2 (берём каталог, а не сам метод)
        base = legacy.rsplit("/", 1)[0] if legacy else _DEFAULT_BASE
    return f"{base}/{method.lstrip('/')}"


def api_params(extra: Dict[str, Any] = None) -> Dict[str, Any]:
    """Параметры запроса с ключом, если владелец его задал.

    Без ключа toncenter жёстко ограничивает частоту — это не ошибка настройки,
    а режим по умолчанию, поэтому отсутствие ключа не считается сбоем.
    """
    params = dict(extra or {})
    key = os.getenv("TONCENTER_API_KEY", "").strip()
    if key:
        params["api_key"] = key
    return params


# ── настройка ────────────────────────────────────────────────────────────────
def payout_address() -> str:
    """Счёт владельца, с которого уходит TON. Пусто = не настроен."""
    return os.getenv("TON_PAYOUT_ADDRESS", "").strip()


def payouts_enabled() -> bool:
    """Гейт авто-выплат TON. Выключен по умолчанию и остаётся выключенным,
    пока в окружении нет подписывающей библиотеки — включённый флаг сам по себе
    ничего не отправит, см. send()."""
    return os.getenv("TON_PAYOUTS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def library_available() -> bool:
    """Есть ли чем подписать транзакцию. Проверяем импортом, а не догадкой."""
    for mod in ("tonsdk", "pytoniq", "pytoniq_core"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


def status() -> Dict[str, Any]:
    """Срез состояния в форме, общей для всех кошельков реестра.

    `unlocked` всегда False: разблокировать нечего — ключа у нас нет. Это не
    временное состояние, а честное описание watch-only контура.
    """
    addr = payout_address()
    return {
        "configured": bool(addr),
        "unlocked": False,
        "address": addr,
        "network": "ton-mainnet",
        "library": library_available(),
        "payouts_enabled": payouts_enabled(),
        "watch_only": True,
    }


# ── сеть ─────────────────────────────────────────────────────────────────────
def _get_json(url: str, params=None, timeout: int = 15):
    """Ответ toncenter как словарь.

    `raise_for_status()` здесь НЕ вызываем намеренно: на 4xx toncenter кладёт
    причину в тело (`{"ok": false, "error": "Failed to parse ton_addr…"}`), а
    исключение по коду превратило бы её в безымянный HTTPError — владелец
    увидел бы «ошибка сети» вместо «адрес не разобран».
    """
    import requests
    r = requests.get(url, params=params or {}, timeout=timeout)
    try:
        return r.json()
    except ValueError:
        r.raise_for_status()          # не JSON и код плохой — это правда сбой
        raise


def account_state(address: str = None) -> Dict[str, Any]:
    """{'balance': float|None, 'status': 'OK'|'ERROR'|'NOT_CONFIGURED', 'reason'}.

    None в балансе означает «не знаем», и это НЕ ноль: пустой счёт и недоступный
    обозреватель выглядят одинаково только для того, кто их не различает, а
    решение «хватит ли на выдачу» принимается именно по этому числу.
    """
    addr = (address or payout_address()).strip()
    if not addr:
        return {"balance": None, "status": "NOT_CONFIGURED",
                "reason": "TON_PAYOUT_ADDRESS не задан"}
    try:
        data = _get_json(api_url("getAddressBalance"),
                         api_params({"address": addr})) or {}
    except Exception as e:
        return {"balance": None, "status": "ERROR", "reason": f"{type(e).__name__}"}
    if not data.get("ok"):
        return {"balance": None, "status": "ERROR",
                "reason": str(data.get("error") or "toncenter отказал")[:160]}
    try:
        nano = int(data.get("result"))
    except (TypeError, ValueError):
        return {"balance": None, "status": "ERROR", "reason": "нечисловой баланс"}
    return {"balance": nano / 1e9, "status": "OK", "reason": None}


def get_balance(address: str = None) -> float:
    """Баланс в TON; «не знаем» отдаём как 0.0 — для различения нужен
    account_state(). Ноль по умолчанию фейл-клоуз: недоступная сеть не должна
    выглядеть как достаточная ликвидность."""
    st = account_state(address)
    b = st.get("balance")
    return b if isinstance(b, (int, float)) else 0.0


def balance(address: str = None) -> Dict[str, Any]:
    """Форма, которую ждёт реестр кошельков."""
    st = account_state(address)
    return {"balance": st.get("balance"), "status": st.get("status"),
            "reason": st.get("reason")}


# ── отправка ─────────────────────────────────────────────────────────────────
def send(*_args, **_kwargs):
    """Отправки нет: контур watch-only.

    Исключение, а не None: None у остальных модулей означает «попытались и не
    вышло», и вызывающий по нему уводит заявку человеку. Здесь же попытки не
    было вовсе, и тихо вернуть «не вышло» значило бы спрятать причину — на
    поверхности выдачи это выглядело бы как сбой сети.
    """
    raise NotImplementedError(
        "TON: подписи нет (watch-only контур). Выдача — вручную через /worker "
        "или /force_payout ORDER_ID TXID. Автоматическая отправка появится "
        "вместе с подписывающей библиотекой и включённым TON_PAYOUTS_ENABLED.")
