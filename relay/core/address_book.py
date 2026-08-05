"""Адреса клиента: куда он уже получал и что подтвердил подписью.

Зачем. Опечатка в адресе необратима, а клиент набирает его заново при КАЖДОЙ
заявке — включая тех, кто пятый раз меняет на тот же кошелёк. Один тап вместо
набора убирает целый класс потерь, которого не ловит никакая проверка на нашей
стороне: контрольная сумма подтверждает, что адрес существует, а не что он ваш.

Откуда берутся адреса — и почему только отсюда:

1. Подтверждённые подписью связи (`core.wallet_link`) — владение доказано.
2. Адреса из СОБСТВЕННЫХ прошлых заявок клиента.

Принимать адрес из запроса и складывать в чей-то список нельзя: это ровно тот
путь, которым обменник превращается в бесплатный пробник чужих кошельков (см.
шапку `core/wallet_link`). Здесь то же правило с другой стороны — список строит
СЕРВЕР по своим данным, клиент может лишь подписать запись именем или скрыть её.

Баланс модуль не показывает и показывать не должен. Владение адресом из прошлой
заявки НЕ доказано: клиент мог указать чужой адрес (биржи, знакомого), и остаток
по нему — не его дело. Балансы остаются привилегией подтверждённых подписью
связей, где владение доказано.

Негодный адрес в список не попадает. Проверка форм и сетей меняется (добавили
контрольные суммы, развели сети USDT), и адрес, принятый год назад, сегодня
может её не проходить. Предложить такой к переиспользованию одним тапом — значит
своими руками отправить деньги в никуда, поэтому фильтр фейл-клоузный: не
уверены — не предлагаем.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Статусы, при которых монеты по заявке РЕАЛЬНО ушли на адрес. Только такие
# заявки делают адрес «уже проверенным на деле»: pending/expired/cancelled/failed
# ничего о судьбе адреса не говорят, а отменённая заявка нередко отменена
# именно из-за неверного адреса.
DELIVERED_STATUSES = ("sent",)
_DELIVERED_SQL = "(" + ",".join(f"'{s}'" for s in DELIVERED_STATUSES) + ")"

# Сколько адресов отдаём поверхности. Список — подсказка, а не архив: длинный
# перечень одинаковых с виду строк опаснее пустого, в нём промахиваются.
MAX_ENTRIES = int(os.getenv("ADDRESS_BOOK_MAX", "8") or 8)

_DDL = ("CREATE TABLE IF NOT EXISTS client_address_notes ("
        " user_id INTEGER NOT NULL,"
        " currency TEXT NOT NULL,"
        " network TEXT NOT NULL DEFAULT '',"
        " address TEXT NOT NULL,"
        " label TEXT NOT NULL DEFAULT '',"
        " hidden INTEGER NOT NULL DEFAULT 0,"
        " updated_at TEXT NOT NULL,"
        " PRIMARY KEY (user_id, currency, network, address))")


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute(_DDL)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid(currency, address, network=None) -> bool:
    """Годен ли адрес СЕГОДНЯШНЕЙ проверке. Сбой проверки — «негоден»."""
    try:
        from core import assets as _assets
        return bool(_assets.validate_destination(currency, address, network))
    except Exception as e:
        logger.warning("address_book: проверка адреса недоступна: %s", e)
        return False


def short(address, head: int = 8, tail: int = 6) -> str:
    """Адрес для показа. Середину прячем, но КОНЕЦ оставляем: подменённый
    адрес отличается именно хвостом, и обрезка «…» после начала — старый
    способ не заметить подмену."""
    s = str(address or "")
    if len(s) <= head + tail + 1:
        return s
    return f"{s[:head]}…{s[-tail:]}"


def entries_for(user_id, currency=None, network=None, limit: int = MAX_ENTRIES,
                include_hidden: bool = False) -> list[dict]:
    """Адреса клиента, свежие сверху. Пустой список — нормальный ответ.

    `currency`/`network` сужают выборку под конкретную заявку: предлагать
    BTC-адрес там, где просят LTC, — приглашение к необратимой ошибке.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return []
    if uid <= 0:
        return []
    cur_filter = str(currency or "").strip().upper()
    net_filter = str(network or "").strip().upper()

    rows, notes, links = [], {}, []
    try:
        with _conn() as conn:
            # Только заявки, по которым монеты ДОШЛИ. Иначе адрес, из-за
            # которого заявку и отменили («не тот кошелёк»), останется
            # предложением в один тап навсегда: клиент отменил заявку именно
            # чтобы туда не отправлять, а мы бы это подсказали. Нашёл codex.
            sql = ("SELECT currency, COALESCE(network,'') AS network, crypto_address,"
                   "       MAX(created_at) AS last_at, COUNT(*) AS uses"
                   "  FROM orders"
                   " WHERE user_id = ? AND crypto_address IS NOT NULL"
                   "   AND TRIM(crypto_address) != ''"
                   "   AND LOWER(COALESCE(status,'')) IN " + _DELIVERED_SQL)
            args = [uid]
            if cur_filter:
                sql += " AND UPPER(currency) = ?"
                args.append(cur_filter)
            sql += (" GROUP BY UPPER(currency), UPPER(COALESCE(network,'')), crypto_address"
                    " ORDER BY last_at DESC LIMIT 200")
            rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
            for r in conn.execute(
                    "SELECT currency, network, address, label, hidden FROM "
                    "client_address_notes WHERE user_id = ?", (uid,)).fetchall():
                key = (str(r["currency"]).upper(), str(r["network"] or "").upper(),
                       str(r["address"]))
                notes[key] = {"label": r["label"] or "", "hidden": bool(r["hidden"])}
    except Exception as e:
        logger.warning("address_book: не прочитали заявки клиента: %s", e)
        return []

    # Подтверждённые подписью связи идут первыми и всегда: это единственные
    # адреса, владение которыми доказано.
    try:
        from core import wallet_link as _wl
        links = _wl.links_for(uid) or []
    except Exception as e:
        logger.warning("address_book: связи кошелька недоступны: %s", e)

    out, seen = [], set()

    def add(cur, net, addr, source, verified, last_at=None, uses=0):
        cur = str(cur or "").upper()
        net = str(net or "").upper()
        addr = str(addr or "").strip()
        if not cur or not addr:
            return
        if cur_filter and cur != cur_filter:
            return
        # Сеть сверяем, только если она известна у обеих сторон: у старых
        # заявок колонки network нет вовсе, и отбрасывать их — значит терять
        # ровно те адреса, которыми клиент пользуется дольше всех.
        if net_filter and net and net != net_filter:
            return
        key = (cur, net, addr)
        if key in seen:
            return
        note = notes.get(key) or notes.get((cur, "", addr)) or {}
        hidden = bool(note.get("hidden"))
        if hidden and not include_hidden:
            seen.add(key)
            return
        if not _valid(cur, addr, net or net_filter or None):
            seen.add(key)
            return
        seen.add(key)
        out.append({"currency": cur, "network": net, "address": addr,
                    "short": short(addr), "label": note.get("label", ""),
                    "source": source, "verified": bool(verified),
                    "hidden": hidden,
                    "last_at": last_at or "", "uses": int(uses or 0)})

    for link in links:
        add(link.get("chain"), link.get("chain"), link.get("address"),
            "connected", True, link.get("verified_at"), 0)
    for r in rows:
        add(r["currency"], r["network"], r["crypto_address"],
            "used", False, r["last_at"], r["uses"])

    return out[:max(1, int(limit or MAX_ENTRIES))]


def set_label(user_id, currency, address, label, network="") -> bool:
    """Подписать адрес именем («мой Ledger», «Binance»). Пустое имя — снять."""
    return _note(user_id, currency, address, network, label=str(label or "")[:40])


def hide(user_id, currency, address, network="") -> bool:
    """Убрать адрес из подсказок. Заявки не трогаем — это витрина, не история."""
    return _note(user_id, currency, address, network, hidden=1)


def unhide(user_id, currency, address, network="") -> bool:
    return _note(user_id, currency, address, network, hidden=0)


def _note(user_id, currency, address, network, label=None, hidden=None) -> bool:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    cur = str(currency or "").strip().upper()
    net = str(network or "").strip().upper()
    addr = str(address or "").strip()
    if uid <= 0 or not cur or not addr:
        return False
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT label, hidden FROM client_address_notes WHERE user_id=? "
                "AND currency=? AND network=? AND address=?",
                (uid, cur, net, addr)).fetchone()
            new_label = row["label"] if (row and label is None) else (label or "")
            new_hidden = row["hidden"] if (row and hidden is None) else int(hidden or 0)
            conn.execute(
                "INSERT INTO client_address_notes"
                " (user_id, currency, network, address, label, hidden, updated_at)"
                " VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(user_id, currency, network, address) DO UPDATE SET"
                " label=excluded.label, hidden=excluded.hidden,"
                " updated_at=excluded.updated_at",
                (uid, cur, net, addr, new_label, new_hidden, _now()))
            conn.commit()
        return True
    except Exception as e:
        logger.warning("address_book: заметку не сохранили: %s", e)
        return False


def owns(user_id, currency, address, network=None, include_hidden: bool = False) -> bool:
    """Есть ли этот адрес в книге клиента.

    Нужен там, где адрес приходит НАЗАД от клиента (нажал подсказку). Данным из
    кнопки не доверяем: колбэк подделывается, и без этой проверки чужой адрес
    подставился бы в заявку как «ваш сохранённый».

    `include_hidden` — для правки заметок: скрытый адрес не годится для
    ПОДСТАНОВКИ, но остаётся своим, иначе вернуть его из скрытых было бы нечем.
    """
    addr = str(address or "").strip()
    if not addr:
        return False
    for e in entries_for(user_id, currency, network, limit=200,
                         include_hidden=include_hidden):
        if e["address"] == addr:
            return True
    return False
