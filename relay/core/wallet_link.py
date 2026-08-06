"""Подключённый кошелёк клиента: хранение доказанного владения и балансы.

Зачем отдельный модуль. Этап 3 бэклога — некастодиальный кошелёк в Mini App:
ключ у клиента, у нас интерфейс. Первый шаг — только просмотр баланса. Всё
опасное здесь в одном вопросе: ЧЕЙ адрес мы смотрим.

Правило, ради которого модуль и написан: адрес для баланса берётся ТОЛЬКО из
этой таблицы, куда он попадает после проверенной подписи (`ton_proof`,
core/tonconnect). Принять адрес из запроса и показать по нему баланс — значит
превратить обменник в бесплатный пробник чужих кошельков: любой желающий
проверял бы остатки по списку адресов через наш сервер, от нашего IP и с нашими
ключами к обозревателю. Плюс клиент увидел бы «ваш баланс» под чужим адресом.

Второе правило: «не знаем» — не ноль. Недоступный обозреватель и пустой счёт
выглядят одинаково только для того, кто их не различает; клиенту показываем
честное «баланс недоступен», а не 0.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Пока подключается только TON (единственная сеть с проверкой владения —
# TON Connect). Добавление сети = запись сюда + доказательство владения,
# иначе адрес попадёт в таблицу без подтверждения.
BALANCE_SOURCES = {
    "TON": ("wallet.ton_wallet", "account_state"),
    # BTC/LTC подключаются не сами (кошелёк к нам не ходит) — владение
    # доказывается подписью сообщения, `core/sig_proof`. Для баланса это
    # ничего не меняет: адрес всё равно берётся из таблицы связей.
    "BTC": ("core.chain_watch", "btc_account_state"),
    "LTC": ("core.chain_watch", "ltc_account_state"),
    # TRON — цепь, а не монета: на одном счёте живут и TRX, и USDT. Читаем и
    # показываем USDT (единственный актив, которым мы здесь торгуем), и сам
    # ответ называет актив полем `asset` — иначе клиент решит, что «баланс
    # TRON» это его USDT, и увидит не те деньги.
    "TRON": ("core.chain_watch", "tron_account_state"),
}

HISTORY_SOURCES = {
    "TON": ("wallet.ton_wallet", "history"),
    "BTC": ("core.chain_watch", "btc_history"),
    "LTC": ("core.chain_watch", "ltc_history"),
    "TRON": ("core.chain_watch", "tron_history"),
}

_DDL = ("CREATE TABLE IF NOT EXISTS wallet_links ("
        " user_id INTEGER NOT NULL,"
        " chain TEXT NOT NULL,"
        " address TEXT NOT NULL,"
        " verified_at TEXT NOT NULL,"
        " PRIMARY KEY (user_id, chain))")


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.execute(_DDL)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def remember(user_id, chain: str, address: str) -> bool:
    """Запомнить ДОКАЗАННОЕ владение адресом. Зовут только там, где вердикт
    подписи положительный, — сам модуль подпись не проверяет и проверить не
    может, поэтому вызывать его из места без вердикта нельзя."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    chain = (chain or "").upper().strip()
    address = (address or "").strip()
    if not uid or not chain or not address:
        return False
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO wallet_links (user_id, chain, address, verified_at) "
                "VALUES (?,?,?,?) ON CONFLICT(user_id, chain) DO UPDATE SET "
                "address=excluded.address, verified_at=excluded.verified_at",
                (uid, chain, address, _now()))
            conn.commit()
        return True
    except Exception as e:
        logger.warning("wallet_link: не сохранили связь uid=%s %s: %s", user_id, chain, e)
        return False


def forget(user_id, chain: str = None) -> int:
    """Отключить кошелёк. Возвращает число снятых связей."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return 0
    try:
        with _conn() as conn:
            if chain:
                cur = conn.execute("DELETE FROM wallet_links WHERE user_id=? AND chain=?",
                                   (uid, (chain or "").upper().strip()))
            else:
                cur = conn.execute("DELETE FROM wallet_links WHERE user_id=?", (uid,))
            conn.commit()
            return cur.rowcount or 0
    except Exception as e:
        logger.warning("wallet_link: не сняли связь uid=%s: %s", user_id, e)
        return 0


def links_for(user_id) -> list:
    """Подключённые кошельки клиента: [{'chain','address','verified_at'}]."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return []
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT chain, address, verified_at FROM wallet_links "
                "WHERE user_id=? ORDER BY chain", (uid,)).fetchall()
        return [{"chain": r[0], "address": r[1], "verified_at": r[2]} for r in rows]
    except Exception as e:
        logger.warning("wallet_link: не прочитали связи uid=%s: %s", user_id, e)
        return []


def address_for(user_id, chain: str):
    """Подтверждённый адрес клиента в сети или None. Единственный источник
    адреса для любого показа баланса."""
    chain = (chain or "").upper().strip()
    for link in links_for(user_id):
        if link["chain"] == chain:
            return link["address"]
    return None


def _account_state(chain: str, address: str, source=None) -> dict:
    """Состояние счёта у обозревателя. source — для тестов, в проде None."""
    fn = source
    if fn is None:
        mod_name, fn_name = BALANCE_SOURCES.get(chain, (None, None))
        if not mod_name:
            return {"balance": None, "status": "UNSUPPORTED",
                    "reason": f"сеть {chain} не поддержана"}
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
        except Exception as e:
            return {"balance": None, "status": "ERROR", "reason": type(e).__name__}
    try:
        st = fn(address) or {}
    except Exception as e:
        return {"balance": None, "status": "ERROR", "reason": type(e).__name__}
    bal = st.get("balance")
    if not isinstance(bal, (int, float)):
        # «не знаем» остаётся «не знаем»: подставить 0 здесь — соврать клиенту
        # про пустой кошелёк при недоступном обозревателе.
        return {"balance": None, "pending": None, "status": st.get("status") or "ERROR",
                "reason": st.get("reason") or "баланс недоступен"}
    # Ожидающее в мемпуле проносим отдельным числом: сложить его с остатком
    # значило бы назвать своим то, что ещё может не состояться, а промолчать —
    # ответить «ноль» тому, кто только что получил перевод.
    pend = st.get("pending")
    # Актив называет сам источник: в цепи TRON на одном счёте лежат TRX и USDT,
    # и «баланс TRON» без имени актива клиент прочитает как свои USDT. По
    # умолчанию актив совпадает с цепью — так было у BTC/LTC/TON.
    return {"balance": float(bal), "status": "OK", "reason": None,
            "asset": str(st.get("asset") or chain).upper(),
            "pending": float(pend) if isinstance(pend, (int, float)) else None}


def history_for(user_id, chain: str = "TON", limit: int = 20, source=None) -> dict:
    """История операций ПОДКЛЮЧЁННОГО кошелька клиента.

    Как и у баланса, адрес берётся из хранилища связей, а не из запроса — и по
    той же причине, только цена ошибки выше: история кошелька выдаёт связи,
    суммы и контрагентов. Показать её по адресу из параметра значило бы отдать
    чужую финансовую жизнь любому, кто знает адрес.

    Ответ различает «операций нет» и «спросить не смогли»: клиенту, который
    ищет свой перевод, это разные новости.
    """
    chain = (chain or "TON").upper().strip()
    address = address_for(user_id, chain)
    if not address:
        return {"items": [], "status": "NOT_CONNECTED", "reason": "кошелёк не подключён",
                "chain": chain, "address": ""}
    fn = source
    if fn is None:
        mod_name, fn_name = HISTORY_SOURCES.get(chain, (None, None))
        if not mod_name:
            return {"items": [], "status": "UNSUPPORTED",
                    "reason": f"история сети {chain} не поддержана",
                    "chain": chain, "address": address}
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
        except Exception as e:
            return {"items": [], "status": "ERROR", "reason": type(e).__name__,
                    "chain": chain, "address": address}
    try:
        res = fn(address, limit) or {}
    except Exception as e:
        return {"items": [], "status": "ERROR", "reason": type(e).__name__,
                "chain": chain, "address": address}
    items = res.get("items")
    if not isinstance(items, list):
        items = []
    return {"items": items, "status": res.get("status") or "ERROR",
            "reason": res.get("reason"), "chain": chain, "address": address}


def balances_for(user_id, source=None) -> list:
    """Балансы ПОДКЛЮЧЁННЫХ кошельков клиента.

    Адрес приходит из хранилища связей, а не из запроса — см. заголовок модуля.
    Функция намеренно не принимает адрес аргументом: тогда её нечем позвать
    «за чужой кошелёк».
    """
    out = []
    for link in links_for(user_id):
        st = _account_state(link["chain"], link["address"], source=source)
        out.append({
            "chain": link["chain"],
            "address": link["address"],
            "verified_at": link["verified_at"],
            "balance": st["balance"],
            "asset": st.get("asset") or link["chain"],
            "pending": st.get("pending"),
            "status": st["status"],
            "reason": st["reason"],
        })
    return out
