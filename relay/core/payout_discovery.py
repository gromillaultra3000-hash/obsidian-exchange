"""Поиск доказательств выплаты в блокчейне по адресу назначения заявки.

Зачем. Выплата «мимо бота» — из личного кошелька владельца, а не из горячего —
оставляет заявку в статусе 'paid' навсегда: клиент не получает уведомление и
TXID, реф-бонус и VIP-объём не начисляются, сторож конверсии вечно считает
заявку зависшей. 27.07.2026 так висели три заявки на 13 947 ₽, две из которых
были УЖЕ оплачены; факт оплаты пришлось искать руками через обозреватели.

Отличие от core/chain_reconcile: тот смотрит на ИСХОДЯЩИЕ из нашего кошелька
(и только TRON). Здесь наоборот — ВХОДЯЩИЕ на адрес клиента, поэтому находятся
и переводы из кошельков, о которых система не знает.

## Главное правило: закрываем только по неподделываемому доказательству

Совпадение суммы на адресе клиента — доказательство СЛАБОЕ: адрес принадлежит
клиенту, и туда может прийти что угодно откуда угодно. Хуже того, клиент может
подстроить совпадение сам (перевести себе ожидаемую сумму со второго кошелька)
и получить закрытую заявку без выплаты. Поэтому отправитель обязан быть НАШИМ:
адрес горячего кошелька или адрес, заранее внесённый владельцем через
/paysrc. Такой перевод подделать нельзя — ключи только у нас.

Всё остальное (сумма сошлась, но отправитель неизвестен) закрытием НЕ считается
и уходит человеку как подсказка. Ошибка здесь стоит дороже, чем ручной клик:
закрытая по ошибке заявка означает клиента, который заплатил и не получил ничего,
а система считает, что всё в порядке.

ЧТЕНИЕ + вердикт. Модуль ничего не пишет в orders — решение исполняет вызывающий.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/root/exchange.db")

# Насколько фактическая сумма может отличаться от ожидаемой. Комиссию сети
# платит отправитель, поэтому расхождение обычно нулевое; допуск нужен на
# округление и на ручной ввод «примерно столько».
AMOUNT_TOLERANCE_PCT = float(os.getenv("DISCOVERY_AMOUNT_TOLERANCE_PCT", "1.0") or 1.0)
# Заявку моложе этого возраста не трогаем: авто-выплата ещё могла не отработать.
MIN_AGE_MIN = int(os.getenv("DISCOVERY_MIN_AGE_MIN", "45") or 45)
# Глубже в прошлое не смотрим — старые совпадения уже неактуальны.
MAX_AGE_DAYS = int(os.getenv("DISCOVERY_MAX_AGE_DAYS", "14") or 14)

SOURCES_PATH = os.getenv("DISCOVERY_SOURCES_PATH",
                         "/root/wallet_data/payout_sources.json")


# ─────────────────────────────────────────────────────────────────
# Доверенные отправители
# ─────────────────────────────────────────────────────────────────
def _norm(addr) -> str:
    """Адреса сравниваем без регистра: bech32 допускает верхний регистр целиком,
    а EVM-адрес несёт контрольную сумму именно в регистре. Для СРАВНЕНИЯ это
    неважно — важно не потерять совпадение из-за разного написания."""
    return str(addr or "").strip().lower()


def _registered_sources() -> dict:
    try:
        p = Path(SOURCES_PATH)
        if not p.exists():
            return {}
        data = json.loads(p.read_text("utf-8"))
        return data.get("sources") or {}
    except Exception as e:
        logger.warning("payout_discovery: список источников нечитаем: %s", e)
        return {}


def add_source(currency: str, address: str, note: str = "") -> dict:
    """Внести кошелёк, из которого владелец платит клиентам, в доверенные."""
    cur = str(currency or "").upper()
    addr = str(address or "").strip()
    if not cur or not addr:
        return {"ok": False, "error": "нужны валюта и адрес"}
    p = Path(SOURCES_PATH)
    try:
        data = json.loads(p.read_text("utf-8")) if p.exists() else {}
    except Exception:
        data = {}
    src = data.setdefault("sources", {})
    src.setdefault(cur, {})[_norm(addr)] = {"note": note, "raw": addr}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "currency": cur, "address": addr,
            "total": sum(len(v) for v in src.values())}


def remove_source(currency: str, address: str) -> dict:
    cur = str(currency or "").upper()
    p = Path(SOURCES_PATH)
    try:
        data = json.loads(p.read_text("utf-8")) if p.exists() else {}
    except Exception:
        return {"ok": False, "error": "список нечитаем"}
    removed = (data.get("sources") or {}).get(cur, {}).pop(_norm(address), None)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": bool(removed), "currency": cur, "address": address}


# Имена легаси-кошельков bitcoinlib (watch-only после Фазы 3) — по ним берётся
# ПОЛНЫЙ список адресов, включая адреса сдачи.
_LEGACY_WALLETS = {"BTC": "PayoutWallet", "LTC": "PayoutLTC"}


# Кеш своих адресов. Список кошелька меняется только когда мы сами тратим, а
# читается он через bitcoinlib, чей SQLite привязан к потоку-создателю: дёргать
# его из нового потока executor'а каждые полчаса — лишняя нагрузка и лишний
# риск. Просроченный кеш максимум отправит СВОЮ выплату человеку на
# подтверждение (новый адрес сдачи ещё не попал в список) — направление
# безопасное, ошибочного закрытия он вызвать не может.
_OWN_CACHE: dict[str, tuple[float, set]] = {}
OWN_CACHE_TTL = int(os.getenv("DISCOVERY_OWN_CACHE_TTL", "3600") or 3600)


def _own_wallet_addresses(currency: str) -> set:
    """Все адреса наших собственных кошельков — доверенные по определению.

    ⚠️ Одного «основного» адреса НЕДОСТАТОЧНО. Кошелёк BTC/LTC — иерархический:
    трата уходит с того адреса, где лежали монеты, а сдача садится на новый.
    Живая проверка 27.07.2026: выплата #99955120 ушла с bc1qnaqa9gz…, которого
    нет ни в primaryAddress, ни в списке addresses из меты вольта (11 записей
    против 23 фактических). Если брать только основной адрес, СВОЯ ЖЕ выплата
    выглядит чужой и заявка никогда не закроется — сбой тихий, без ошибки.
    Поэтому спрашиваем сам кошелёк (watch-only, пароль не нужен).
    """
    import time
    cur = str(currency or "").upper()
    hit = _OWN_CACHE.get(cur)
    if hit and (time.time() - hit[0]) < OWN_CACHE_TTL:
        return hit[1]
    out = set()
    try:
        import sys
        if "/root/relay" not in sys.path:
            sys.path.insert(0, "/root/relay")
        if cur in _LEGACY_WALLETS:
            from wallet import btc_wallet as bw
            a = bw.address(cur)
            if a:
                out.add(_norm(a))
            meta = bw._meta(cur) or {}
            out |= {_norm(x) for x in (meta.get("addresses") or []) if x}
            try:
                from bitcoinlib.wallets import Wallet
                out |= {_norm(x) for x in Wallet(_LEGACY_WALLETS[cur]).addresslist() if x}
            except Exception as e:
                # bitcoinlib есть только в bot/venv; без него остаётся мета —
                # список неполный, поэтому часть своих выплат уйдёт человеку
                # на подтверждение. Это медленнее, но не опаснее.
                logger.warning("payout_discovery: полный список адресов %s недоступен: %s",
                               cur, type(e).__name__)
        elif cur == "USDT":
            from wallet.tron_wallet import tron_address
            a = tron_address()
            if a:
                out.add(_norm(a))
    except Exception as e:
        logger.warning("payout_discovery: адрес своего кошелька %s: %s", cur, e)
    out = {a for a in out if a}
    # Пустой результат НЕ кешируем: это признак сбоя, а не «своих адресов нет».
    # Закешировать пустоту значит на час лишить сверку возможности закрывать.
    if out:
        _OWN_CACHE[cur] = (time.time(), out)
    return out


def trusted_senders(currency: str) -> set:
    """Наши кошельки + внесённые владельцем. Пусто = закрывать нечем."""
    cur = str(currency or "").upper()
    reg = {_norm(a) for a in (_registered_sources().get(cur) or {})}
    return _own_wallet_addresses(cur) | reg


# ─────────────────────────────────────────────────────────────────
# Чтение цепочек
# ─────────────────────────────────────────────────────────────────
def _get_json(url: str, params=None, timeout: int = 15):
    import requests
    r = requests.get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _incoming_btc_like(address: str, coin: str) -> list[dict]:
    """Входящие переводы BTC/LTC. Отправителями считаем адреса всех входов."""
    base = ("https://mempool.space/api" if coin == "BTC"
            else "https://litecoinspace.org/api")
    txs = _get_json(f"{base}/address/{address}/txs") or []
    out = []
    for t in txs:
        value = sum(v.get("value", 0) for v in (t.get("vout") or [])
                    if v.get("scriptpubkey_address") == address)
        if value <= 0:
            continue          # адрес мог быть только сдачей/входом — не приход
        senders = {_norm((v.get("prevout") or {}).get("scriptpubkey_address"))
                   for v in (t.get("vin") or [])}
        st = t.get("status") or {}
        out.append({
            "txid": t.get("txid"),
            "senders": {s for s in senders if s},
            "amount": value / 1e8,
            "ts": st.get("block_time") or 0,
            "confirmed": bool(st.get("confirmed")),
        })
    return out


def _incoming_trc20(address: str) -> list[dict]:
    """Входящие USDT (TRC-20)."""
    data = _get_json("https://api.trongrid.io/v1/accounts/"
                     f"{address}/transactions/trc20",
                     {"limit": 50, "only_to": "true"}) or {}
    out = []
    for t in data.get("data") or []:
        info = t.get("token_info") or {}
        if (info.get("symbol") or "").upper() != "USDT":
            continue          # на адрес могли прийти другие токены
        dec = int(info.get("decimals") or 6)
        out.append({
            "txid": t.get("transaction_id"),
            "senders": {_norm(t.get("from"))},
            "amount": int(t.get("value") or 0) / (10 ** dec),
            "ts": int(t.get("block_timestamp") or 0) // 1000,
            # trongrid отдаёт только попавшие в блок переводы
            "confirmed": True,
        })
    return out


def incoming_transfers(currency: str, address: str) -> list[dict]:
    cur = str(currency or "").upper()
    if cur in ("BTC", "LTC"):
        return _incoming_btc_like(address, cur)
    if cur == "USDT":
        return _incoming_trc20(address)
    return []


# ─────────────────────────────────────────────────────────────────
# Вердикт по одной заявке
# ─────────────────────────────────────────────────────────────────
def judge(order: dict, transfers: list[dict], used_txids: set,
          trusted: set, tolerance_pct: float | None = None) -> dict:
    """Чистая логика: какой перевод закрывает заявку и можно ли закрыть.

    Вынесена отдельно от сети, чтобы проверяться тестами без обозревателей.
    """
    tol = AMOUNT_TOLERANCE_PCT if tolerance_pct is None else float(tolerance_pct)
    expected = float(order.get("expected_amount") or 0)
    paid_ts = int(order.get("paid_ts") or 0)
    res = {"order_id": order.get("order_id"), "action": "none",
           "candidates": [], "reason": ""}
    if expected <= 0:
        res["reason"] = "неизвестен ожидаемый объём выплаты"
        return res

    lo = expected * (1 - tol / 100.0)
    hi = expected * (1 + tol / 100.0)
    for t in transfers:
        txid = t.get("txid")
        if not txid or txid in used_txids:
            continue          # перевод уже закреплён за другой заявкой
        if not t.get("confirmed"):
            continue
        # Перевод обязан быть ПОСЛЕ оплаты заявки: приход на адрес клиента
        # до неё — его собственные деньги, а не наша выплата.
        if paid_ts and int(t.get("ts") or 0) < paid_ts:
            continue
        amount = float(t.get("amount") or 0)
        if not (lo <= amount <= hi):
            continue
        # Нормализуем здесь ТОЖЕ, хотя источники это уже делают: иначе новый
        # добытчик цепочки, забывший про регистр, молча перестал бы узнавать
        # наш кошелёк — заявки просто не закрывались бы без всякой ошибки.
        senders = {_norm(s) for s in (t.get("senders") or set()) if s}
        res["candidates"].append({
            "txid": txid, "amount": amount, "ts": t.get("ts"),
            "trusted": bool(senders & {_norm(x) for x in trusted}),
            "senders": sorted(senders),
        })

    if not res["candidates"]:
        res["reason"] = "подходящих переводов на адрес клиента не найдено"
        return res
    if len(res["candidates"]) > 1:
        res["action"] = "review"
        res["reason"] = (f"подходящих переводов несколько ({len(res['candidates'])}) — "
                         f"выбрать должен человек")
        return res

    only = res["candidates"][0]
    if not only["trusted"]:
        res["action"] = "review"
        res["reason"] = ("сумма сошлась, но отправитель нам не принадлежит — "
                         "подтвердить может только человек "
                         "(добавьте свой кошелёк: /paysrc)")
        return res
    res["action"] = "close"
    res["txid"] = only["txid"]
    res["amount"] = only["amount"]
    res["reason"] = "перевод с нашего кошелька на адрес клиента — выплата состоялась"
    return res


# ─────────────────────────────────────────────────────────────────
# Проход по зависшим заявкам
# ─────────────────────────────────────────────────────────────────
def _db():
    import sqlite3
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def stuck_orders() -> list[dict]:
    """Заявки, оплаченные клиентом, но без доказательства выдачи."""
    import sqlite3
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT order_id, user_id, rub_amount, currency, network, "
                "       crypto_address, agreed_crypto_amount, "
                "       CAST(strftime('%s', COALESCE(updated_at, created_at)) AS INT) paid_ts "
                "FROM orders "
                "WHERE status='paid' AND (paid_btc_tx IS NULL OR paid_btc_tx='') "
                "  AND COALESCE(updated_at, created_at) <= datetime('now', ?) "
                "  AND COALESCE(updated_at, created_at) >= datetime('now', ?) "
                "ORDER BY COALESCE(updated_at, created_at)",
                (f"-{MIN_AGE_MIN} minutes", f"-{MAX_AGE_DAYS} days")).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as e:
        logger.error("payout_discovery: чтение orders: %s", e)
        return []


def _used_txids() -> set:
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT paid_btc_tx FROM orders "
                "WHERE paid_btc_tx IS NOT NULL AND paid_btc_tx != ''").fetchall()
        return {_norm(r[0]) for r in rows}
    except Exception as e:
        logger.error("payout_discovery: чтение занятых txid: %s", e)
        # Fail-CLOSED: не зная, какие переводы уже закреплены, закрывать нельзя —
        # один перевод мог бы закрыть две заявки.
        raise


def expected_amount(order: dict, rate_fn=None) -> float:
    """Сколько должно было уйти клиенту: обещанное при создании заявки, а при
    его отсутствии — пересчёт по курсу (для старых заявок)."""
    agreed = order.get("agreed_crypto_amount")
    if agreed and float(agreed) > 0:
        return float(agreed)
    if rate_fn is None:
        return 0.0
    try:
        rate = float(rate_fn(order.get("currency"), order.get("rub_amount")) or 0)
        return round(float(order.get("rub_amount") or 0) / rate, 8) if rate else 0.0
    except Exception:
        return 0.0


def discover(rate_fn=None, fetch=None) -> dict:
    """Ищет доказательства выплаты по всем зависшим заявкам.

    rate_fn(currency, rub) — курс для старых заявок без зафиксированной
    котировки; fetch(currency, address) — источник переводов (подменяется в тестах).
    Ничего не меняет: возвращает список вердиктов.
    """
    fetch = fetch or incoming_transfers
    out = {"checked": 0, "close": [], "review": [], "none": 0, "errors": []}
    try:
        used = _used_txids()
    except Exception as e:
        out["errors"].append(f"не удалось прочитать занятые txid: {type(e).__name__}")
        return out
    trusted_cache: dict[str, set] = {}

    for o in stuck_orders():
        out["checked"] += 1
        cur = (o.get("currency") or "").upper()
        addr = o.get("crypto_address")
        if not addr:
            continue
        if cur not in trusted_cache:
            trusted_cache[cur] = trusted_senders(cur)
        try:
            transfers = fetch(cur, addr)
        except Exception as e:
            out["errors"].append(f"#{o['order_id']}: цепочка недоступна ({type(e).__name__})")
            continue
        v = judge({**o, "expected_amount": expected_amount(o, rate_fn)},
                  transfers, used, trusted_cache[cur])
        v["currency"] = cur
        v["rub_amount"] = o.get("rub_amount")
        v["user_id"] = o.get("user_id")
        v["network"] = o.get("network")
        v["address"] = addr
        if v["action"] == "close":
            used.add(_norm(v["txid"]))   # в рамках прохода перевод уже занят
            out["close"].append(v)
        elif v["action"] == "review":
            out["review"].append(v)
        else:
            out["none"] += 1
    return out


def format_report(res: dict, max_items: int = 6) -> str:
    """Сводка для Telegram или '' — если рассказывать не о чем."""
    if not res.get("close") and not res.get("review") and not res.get("errors"):
        return ""
    lines = ["⛓ <b>Сверка выдачи с блокчейном</b>\n",
             f"<blockquote>Проверено зависших заявок: <b>{res.get('checked', 0)}</b>\n"
             f"Закрыто по доказательству: <b>{len(res.get('close', []))}</b>\n"
             f"Требуют решения: <b>{len(res.get('review', []))}</b></blockquote>"]
    for v in res.get("close", [])[:max_items]:
        lines.append(f"\n✅ #{v['order_id']} — {v.get('amount')} {v['currency']}, "
                     f"tx <code>{(v.get('txid') or '')[:16]}…</code>")
    for v in res.get("review", [])[:max_items]:
        lines.append(f"\n🟡 #{v['order_id']} ({v.get('rub_amount'):g} ₽ → {v['currency']}): "
                     f"{v['reason']}")
        for c in v.get("candidates", [])[:2]:
            lines.append(f"   <code>{c['txid'][:20]}…</code> {c['amount']} "
                         f"от {', '.join(c['senders'])[:48]}")
    for e in res.get("errors", [])[:3]:
        lines.append(f"\n⚠️ {e}")
    return "\n".join(lines)
