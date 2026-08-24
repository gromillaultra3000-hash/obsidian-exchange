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
from datetime import datetime, timezone
from repositories.address_book_store import from_environment as _store_from_environment

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Статусы, при которых монеты по заявке РЕАЛЬНО ушли на адрес. Только такие
# заявки делают адрес «уже проверенным на деле»: pending/expired/cancelled/failed
# ничего о судьбе адреса не говорят, а отменённая заявка нередко отменена
# именно из-за неверного адреса.
# `completed` — легаси-статус тех же успешных заявок: он живёт в подсчётах
# бота и payment_service. Признать только `sent` значило бы, что у давнего
# клиента книга пуста. Нашёл codex.
DELIVERED_STATUSES = ("sent", "completed")

# Сколько адресов отдаём поверхности. Список — подсказка, а не архив: длинный
# перечень одинаковых с виду строк опаснее пустого, в нём промахиваются.
MAX_ENTRIES = int(os.getenv("ADDRESS_BOOK_MAX", "8") or 8)

_store = _store_from_environment(sqlite_path=DB_PATH)


def _storage():
    # Tests and maintenance utilities deliberately redirect DB_PATH at runtime.
    # Keep that supported without rebuilding a configured PostgreSQL adapter.
    if hasattr(_store, "path") and _store.path != DB_PATH:
        return _store_from_environment(sqlite_path=DB_PATH)
    return _store


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


def _link_network(chain) -> str:
    """Каноническая сеть монеты подключённого кошелька. Не знаем — пусто:
    пустая сеть в книге означает «не сужаем», и это безопаснее выдуманной."""
    try:
        from core import assets as _assets
        return str(_assets.normalize_network(chain, None) or "").upper()
    except Exception as e:
        logger.warning("address_book: сеть связи не определена: %s", e)
        return ""


def _link_pairs(chain):
    """Пары «монета + сеть», для которых годен адрес из этой цепи.

    У BTC/LTC/TON имя цепи совпадает с кодом монеты, и раньше сеть выводилась
    прямо из него. С приходом TRON и Ethereum это перестало работать: «TRON» —
    не монета, `normalize_network` про неё ничего не знает, и доказанный
    подписью адрес молча исчезал бы из книги — ровно там, где клиент его ждёт.
    Разворачиваем через реестр цепей; пустой ответ — цепь нам незнакома, и
    выдумывать за неё монету нельзя.
    """
    try:
        from core import assets as _assets
        pairs = _assets.pairs_on_chain(chain)
    except Exception as e:
        logger.warning("address_book: цепь связи не разобрана: %s", e)
        return []
    if pairs:
        return pairs
    # Запасной путь для связей, записанных до реестра цепей: имя цепи там
    # совпадало с кодом монеты.
    net = _link_network(chain)
    return [(str(chain or "").upper(), net)] if net else []


def _row_network(currency, network) -> str:
    """Сеть заявки в каноническом виде. Пустую сеть достраиваем ТОЛЬКО у монет
    с единственной сетью: там она однозначна. У USDT сетей две, и подстановка
    «наверное, TRC-20» была бы догадкой о том, куда уходят деньги."""
    net = str(network or "").strip().upper()
    if net:
        return net
    try:
        from core import assets as _assets
        nets = _assets.CURRENCY_NETWORKS.get(
            _assets.normalize_currency(currency)) or []
        return str(nets[0]) if len(nets) == 1 else ""
    except Exception as e:
        logger.warning("address_book: сеть заявки не определена: %s", e)
        return ""


def _note_by_address(notes: dict, cur: str, addr: str):
    """Пометка по АДРЕСУ, в какой бы сети её ни записали.

    Клиент прячет адрес, а не строку реестра. Запись могла лечь и с пустой
    сетью (старая заявка), и с канонической — искать только по точному ключу
    значит иногда не исполнить его решение вовсе.
    """
    for (c, _n, a), note in notes.items():
        if c == cur and a == addr:
            return note
    return None


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
        # Только заявки, по которым монеты ДОШЛИ. Иначе адрес, из-за
        # которого заявку и отменили («не тот кошелёк»), останется
        # предложением в один тап навсегда: клиент отменил заявку именно
        # чтобы туда не отправлять, а мы бы это подсказали. Нашёл codex.
        rows, note_rows = _storage().entries(uid, DELIVERED_STATUSES, cur_filter or None)
        for r in note_rows:
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
    # Один и тот же адрес приходит сюда в двух видах: у подтверждённой связи и
    # свежих заявок сеть каноническая (MAINNET), у старых заявок колонки network
    # не было вовсе и она пустая. Ключи разные — записи считались разными, и
    # книга показывала адрес дважды. Хуже дубля было другое: пометка «скрыть»
    # ложится на КАНОНИЧЕСКУЮ запись, а безсетевой близнец её не видел и
    # оставался предложением в один тап. То есть решение клиента «этот адрес
    # больше не подсказывать» тихо не исполнялось. Нашёл codex.
    #
    # Лечим с двух сторон. Первая: у монеты с ЕДИНСТВЕННОЙ сетью пустая сеть
    # старой заявки не двусмысленна — это она и есть, приводим к канону. У
    # USDT так делать нельзя: там сетей две, и «по умолчанию TRC-20» было бы
    # догадкой о чужих деньгах.
    precise = {(str(l.get("chain") or "").upper(), str(l.get("address") or "").strip())
               for l in links if _link_network(l.get("chain"))}
    for r in rows:
        r["network"] = _row_network(r.get("currency"), r.get("network"))
        if r["network"]:
            precise.add((str(r["currency"]).upper(), str(r["crypto_address"]).strip()))
    # Вторая: если у адреса ЕСТЬ представление с названной сетью, безсетевое —
    # тот же адрес, только менее точный. Считаем по всему набору, а не по
    # порядку обхода: иначе исход зависел бы от того, какая заявка свежее.
    decided = {}

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
        if not net and (cur, addr) in precise:
            return
        if not net and (cur, addr) in decided:
            return
        # Пометку ищем и по безсетевому виду: клиент прячет АДРЕС, а не запись
        # о нём, и в каком виде она в тот момент лежала — его не касается.
        note = (notes.get(key) or notes.get((cur, "", addr))
                or _note_by_address(notes, cur, addr) or {})
        hidden = bool(note.get("hidden"))
        decided[(cur, addr)] = net
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
        # Связь хранится по ЦЕПИ, а книга живёт парами «монета + сеть», и одно в
        # другое разворачивается не один в один: доказав `0x…`, клиент доказал
        # его и для ETH, и для USDT-ERC20 — это буквально один счёт. Показать
        # такой адрес только под одной монетой значило бы прятать его там, где
        # он полностью годен.
        for cur, net in _link_pairs(link.get("chain")):
            add(cur, net, link.get("address"), "connected", True,
                link.get("verified_at"), 0)
    for r in rows:
        add(r["currency"], r["network"], r["crypto_address"],
            "used", False, r["last_at"], r["uses"])

    return out[:max(1, int(limit or MAX_ENTRIES))]


def entries_by_currency(user_id, per_currency: int = MAX_ENTRIES) -> list[dict]:
    """Книга для витрин, где отбор по монете делает САМА страница.

    Сайт получает список целиком и прячет чужие монеты на клиенте. С общим
    ограничением в восемь записей это тихо теряло адреса: восемь свежих заявок
    по другим монетам вытесняли единственный LTC-адрес, и клиент, у которого он
    есть, видел пустое место. Нашёл codex. Поэтому ограничение здесь — на
    КАЖДУЮ пару «монета + сеть», а не на весь список.
    """
    seen, out = {}, []
    for e in entries_for(user_id, limit=1000):
        key = (e["currency"], e["network"])
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= max(1, int(per_currency or MAX_ENTRIES)):
            out.append(e)
    return out


def deliveries_for(user_id, limit: int = 10) -> list[dict]:
    """Что МЫ отправили на адреса клиента: приход глазами получателя.

    Витрина кошелька без этого — список строк, по которым ничего не происходило.
    Приход берём из СВОИХ заявок, а не из цепочки: у нас есть и сумма, и адрес,
    и хеш, а обозреватель по чужому адресу нам не отвечает и не должен —
    показывать остаток чужого адреса мы не вправе (см. шапку модуля).

    Только `sent` и только с хешем: «отправлено» без хеша — это обещание, а не
    приход, и в кошельке ему не место.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return []
    if uid <= 0:
        return []
    try:
        # Все выданные заявки, в том числе без хеша: путь ручной отправки
        # в боте помечает заявку `sent`, не заполняя `paid_btc_tx`
        # (main_bot.py). Отсечь их по «нет хеша» значило бы спрятать от
        # клиента выдачу, которая состоялась. Нашёл codex.
        rows = _storage().deliveries(uid, DELIVERED_STATUSES, max(1, int(limit or 10)))
    except Exception as e:
        logger.warning("address_book: приходы не прочитаны: %s", e)
        return []

    out = []
    for r in rows:
        cur = str(r["currency"] or "").upper()
        raw = str(r["paid_btc_tx"] or "").strip()
        # Колонка историческая: кроме хешей в ней встречаются ссылки и пометки
        # ручной выдачи. Выдать такую пометку за транзакцию нельзя — клиент
        # пойдёт искать её в обозревателе и не найдёт. Но и спрятать строку
        # нельзя: выдача БЫЛА, а «получено» без записи — это молчание о
        # собственном платеже. Поэтому показываем, честно помечая, чем
        # подтверждено. Нашёл codex.
        chain = False
        try:
            from core import txid as _txid
            chain = bool(_txid.is_txid(raw, cur))
        except Exception:
            chain = False
        url = ""
        if chain:
            try:
                url = _txid.explorer_url(cur, raw, r["network"] or None) or ""
            except Exception:
                url = ""
        out.append({"order_id": r["order_id"], "currency": cur,
                    "network": str(r["network"] or "").upper(),
                    "address": str(r["crypto_address"] or ""),
                    "short": short(str(r["crypto_address"] or "")),
                    "amount": r["agreed_crypto_amount"],
                    "txid": raw if chain else "",
                    "evidence": "chain" if chain else "manual",
                    "tx_url": url, "ts": r["ts"] or ""})
    return out


def set_label(user_id, currency, address, label, network="") -> bool:
    """Подписать адрес именем («мой Ledger», «Binance»). Пустое имя — снять."""
    return _note(user_id, currency, address, network, label=str(label or "")[:40])


def hide(user_id, currency, address, network="") -> bool:
    """Убрать адрес из подсказок. Заявки не трогаем — это витрина, не история."""
    return _note(user_id, currency, address, network, hidden=1)


def unhide(user_id, currency, address, network="") -> bool:
    return _note(user_id, currency, address, network, hidden=0)


def _resolve_network(user_id, currency, address, network) -> str:
    """Сеть, под которой адрес РЕАЛЬНО лежит в книге.

    У старых заявок колонки `network` не было, и такие записи живут с пустой
    сетью. Поверхность же присылает сеть выбранную — заметка легла бы под ключ,
    которого в книге нет: команда отвечает «сохранено», а в списке ничего не
    меняется. Нашёл codex.
    """
    addr = str(address or "").strip()
    for e in entries_for(user_id, currency, None, limit=200, include_hidden=True):
        if e["address"] == addr:
            return e["network"]
    return str(network or "").strip().upper()


def _note(user_id, currency, address, network, label=None, hidden=None) -> bool:
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    cur = str(currency or "").strip().upper()
    addr = str(address or "").strip()
    if uid <= 0 or not cur or not addr:
        return False
    net = _resolve_network(uid, cur, addr, network)
    try:
        _storage().upsert_note(uid, cur, net, addr, label, hidden, _now())
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
