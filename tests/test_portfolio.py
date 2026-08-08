#!/usr/bin/env python3
"""Портфель клиента: все подтверждённые сети сразу и честный итог.

Карточка кошелька показывала ОДНУ сеть — TON, если она есть, иначе первую
попавшуюся. Клиент, доказавший три адреса, видел один. Ответа на вопрос
«сколько у меня всего» не было нигде, а ETH-адрес, владение которым мы сами же
просили подтвердить подписью, отвечал «сеть не поддержана».

Здесь проверяется главное: итог никогда не выдаёт незнание за ноль, состав
счёта подписан АКТИВОМ (а не цепью), и все поверхности берут одно число.
"""
import ast
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

# Своя пустая база: боевая закрыта, да и трогать её отсюда нечего.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="portfolio-"), "t.db")

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


from core import assets as _assets            # noqa: E402
from core import chain_watch                   # noqa: E402
from core import portfolio                     # noqa: E402
from core import wallet_link                   # noqa: E402

# Цены не спрашиваем у сети: тест о правилах подсчёта, а не о курсе дня.
_PRICES = {"ETH": 200_000.0, "BTC": 5_000_000.0, "USDT": 90.0, "TRX": 0.0}
portfolio._rate = lambda asset: (_PRICES.get(str(asset).upper()) or None)

# ── 1. Незнание не становится нулём ──────────────────────────────────────────
part = portfolio.summarize([
    {"chain": "ETH", "address": "0xa", "status": "OK", "balance": 1.0, "asset": "ETH",
     "assets": [{"asset": "ETH", "balance": 1.0, "status": "OK"},
                {"asset": "USDT", "balance": None, "status": "ERROR", "reason": "Timeout"}]},
])
check(part["total_rub"] == 200_000.0,
      f"в итог попало что-то кроме известного: {part['total_rub']}")
check(part["complete"] is False, "итог с недоступным активом объявлен полным")
check(any("USDT" in u for u in part["unknown"]),
      f"причина неполноты не названа: {part['unknown']}")
check(portfolio.total_line(part).startswith("≥"),
      f"неполный итог показан как окончательный: {portfolio.total_line(part)!r}")

full = portfolio.summarize([
    {"chain": "BTC", "address": "b", "status": "OK", "balance": 0.01, "asset": "BTC",
     "assets": []},
])
check(full["complete"] is True and full["total_rub"] == 50_000.0,
      f"полный итог посчитан неверно: {full}")
check(not portfolio.total_line(full).startswith("≥"),
      "полный итог зачем-то помечен неполным")

# ── 2. Актив без цены не втягивается в сумму молча ───────────────────────────
noprice = portfolio.summarize([
    {"chain": "TRON", "address": "T", "status": "OK", "balance": 10.0, "asset": "USDT",
     "assets": [{"asset": "USDT", "balance": 10.0, "status": "OK"},
                {"asset": "TRX", "balance": 500.0, "status": "OK"}]},
])
check(noprice["total_rub"] == 900.0,
      f"актив без источника цены попал в итог: {noprice['total_rub']}")
check(noprice["complete"] is False and any("TRX" in u for u in noprice["unknown"]),
      "молчаливый ноль вместо честного «цены нет»")
# Остаток при этом ПОКАЗАН — спрятать чужие деньги так же неверно, как посчитать
# их нулём.
trx = [a for a in noprice["chains"][0]["assets"] if a["asset"] == "TRX"][0]
check(trx["balance"] == 500.0 and trx["rub"] is None,
      f"остаток без цены потерялся или получил выдуманную оценку: {trx}")

# ── 3. Состав счёта берётся у читателя, а не додумывается ────────────────────
one = portfolio.summarize([
    {"chain": "BTC", "address": "b", "status": "OK", "balance": 0.5, "asset": "BTC"},
])
check([a["asset"] for a in one["chains"][0]["assets"]] == ["BTC"],
      "читатель без списка активов потерял заглавный остаток")
check(portfolio.summarize([])["chains"] == [] and portfolio.total_line({}) == "",
      "пустой список кошельков должен молчать, а не показывать 0 ₽")

# ── 4. Ethereum: отказ обозревателя ≠ пустой счёт ────────────────────────────
_calls = []
_CONTRACT = chain_watch._usdt_erc20_contract()


def _fake(url, timeout=12):
    _calls.append(url)
    if "action=balance" in url:
        return {"status": "1", "result": "1500000000000000000"}      # 1.5 ETH
    if "action=tokenbalance" in url:
        return {"status": "1", "result": "25000000"}                  # 25 USDT
    if "action=tokentx" in url:
        return {"status": "1", "result": [
            {"hash": "0x9", "from": "0xdead", "to": "0xME", "value": "25000000",
             "timeStamp": "1700000300", "isError": "0",
             "contractAddress": _CONTRACT},
            # подставной «USDT» с чужого контракта — в список попасть не должен
            {"hash": "0x8", "from": "0xdead", "to": "0xME", "value": "999000000",
             "timeStamp": "1700000400", "isError": "0",
             "contractAddress": "0xfake"},
        ]}
    if "action=txlist" in url:
        return {"status": "1", "result": [
            {"hash": "0x1", "from": "0xdead", "to": "0xME", "value": "1000000000000000000",
             "timeStamp": "1700000000", "isError": "0"},
            # сорвавшаяся — денег не двигала
            {"hash": "0x2", "from": "0xdead", "to": "0xME", "value": "5000000000000000000",
             "timeStamp": "1700000100", "isError": "1"},
            # вызов контракта без перевода
            {"hash": "0x3", "from": "0xME", "to": "0xcontract", "value": "0",
             "timeStamp": "1700000200", "isError": "0"},
        ]}
    return {}


chain_watch._get_json = _fake
chain_watch._cache.clear()

st = chain_watch.evm_account_state("0xME")
check(st["status"] == "OK" and st["balance"] == 1.5,
      f"остаток ETH разобран неверно: {st}")
check(st["pending"] is None,
      "про мемпул Ethereum мы ничего не знаем — ноль здесь был бы утверждением")
by = {a["asset"]: a for a in st["assets"]}
check(by.get("ETH", {}).get("balance") == 1.5 and by.get("USDT", {}).get("balance") == 25.0,
      f"состав ETH-счёта собран неверно: {st['assets']}")

# Отказ обозревателя приходит как `status:"0"` с пустым результатом — и это НЕ
# пустой кошелёк. Клиент с деньгами не должен увидеть ноль из-за чужого сбоя.
chain_watch._cache.clear()
chain_watch._get_json = lambda url, timeout=12: {"status": "0", "message": "NOTOK",
                                                 "result": None}
bad = chain_watch.evm_account_state("0xME")
check(bad["balance"] is None and bad["status"] == "ERROR",
      f"отказ обозревателя превратился в баланс: {bad}")

# Сбой ТОКЕНА не отменяет уже прочитанный ETH, но и не становится нулём.
chain_watch._cache.clear()
chain_watch._get_json = lambda url, timeout=12: (
    {"status": "1", "result": "1000000000000000000"} if "action=balance" in url
    else {"status": "0", "message": "NOTOK", "result": None})
half = chain_watch.evm_account_state("0xME")
usdt = {a["asset"]: a for a in half["assets"]}.get("USDT", {})
check(half["balance"] == 1.0 and usdt.get("balance") is None
      and usdt.get("status") == "ERROR",
      f"сбой токена испортил весь счёт или выдал ноль: {half}")

# ── 5. История Ethereum: срыв, вызов контракта и токен ───────────────────────
chain_watch._cache.clear()
chain_watch._get_json = _fake
h = chain_watch.evm_history("0xME")
check(h["status"] == "OK", f"история не прочиталась: {h}")
kinds = [(i["asset"], i["direction"], i["amount"]) for i in h["items"]]
# Один перевод ETH + один перевод USDT; сорвавшаяся и нулевая отброшены.
check(kinds == [("USDT", "in", 25.0), ("ETH", "in", 1.0)],
      f"история собрана неверно (порядок по времени, срыв и нулевой вызов "
      f"должны отпасть): {kinds}")

# Пустой адрес: обозреватель отвечает status "0" с текстом «ничего не найдено».
# Это ответ, а не сбой — сказать «история недоступна» новому клиенту неверно.
chain_watch._cache.clear()
chain_watch._get_json = lambda url, timeout=12: {
    "status": "0", "message": "No transactions found", "result": []}
empty = chain_watch.evm_history("0xNEW")
check(empty["status"] == "OK" and empty["items"] == [],
      f"пустая история принята за сбой: {empty}")
chain_watch._cache.clear()
chain_watch._get_json = lambda url, timeout=12: {
    "status": "0", "message": "No transactions found", "result": "[]"}
empty2 = chain_watch.evm_history("0xNEW")
check(empty2["status"] == "OK" and empty2["items"] == [],
      f"строковая форма «ничего не найдено» принята за сбой: {empty2}")

# Молчит один источник из двух — отдаём что есть, но НЕ выдаём это за полный
# список: пропажа половины операций читается как потерянный перевод.
chain_watch._cache.clear()
chain_watch._get_json = lambda url, timeout=12: (
    {"status": "1", "result": [{"hash": "0x1", "from": "0xd", "to": "0xME",
                                "value": "1000000000000000000",
                                "timeStamp": "1700000000", "isError": "0"}]}
    if "action=txlist" in url else {"status": "0", "message": "NOTOK", "result": None})
half_h = chain_watch.evm_history("0xME")
check(half_h["status"] == "OK" and len(half_h["items"]) == 1
      and half_h.get("partial") is True and "USDT" in (half_h.get("reason") or ""),
      f"неполная история выдана за полную: {half_h}")

# Молчат оба — это отказ, а не «операций нет».
chain_watch._cache.clear()
chain_watch._get_json = lambda url, timeout=12: {"status": "0", "message": "NOTOK",
                                                 "result": None}
dead = chain_watch.evm_history("0xME")
check(dead["status"] == "ERROR" and dead["items"] == [],
      f"полный отказ обозревателя показан как пустая история: {dead}")

check("d.partial" in read("relay", "webapp.html"),
      "Mini App не предупреждает о неполной истории")

# ── 5б. Проводка до портфеля, а не только сам расчёт ─────────────────────────
# Здесь тест раньше и промахнулся: считалка проверялась напрямую, а слой между
# читателем цепи и портфелем — нет. Он пересобирает ответ поимённо, и всё
# неперечисленное терялось молча: портфель видел один заглавный ETH, не видел
# USDT на том же счёте и объявлял итог ПОЛНЫМ. Нашёл codex.
wallet_link.remember(4242, "ETH", "0xME")


def _src_state(address):
    return {"balance": 1.0, "pending": None, "status": "OK", "asset": "ETH",
            "assets": [{"asset": "ETH", "balance": 1.0, "status": "OK"},
                       {"asset": "USDT", "balance": 25.0, "status": "OK"}]}


linked = wallet_link.balances_for(4242, source=_src_state)
check(linked and [a["asset"] for a in linked[0].get("assets", [])] == ["ETH", "USDT"],
      f"состав счёта не дошёл от читателя до портфеля: {linked}")
through = portfolio.summarize(linked)
check(through["total_rub"] == 200_000.0 + 25.0 * 90.0,
      f"портфель на реальном пути посчитан без токена: {through['total_rub']}")
check(through["complete"] is True, "полный портфель объявлен неполным")


def _src_hist(address, limit):
    return {"items": [], "status": "OK", "reason": "часть операций недоступна (USDT)",
            "partial": True}


hist = wallet_link.history_for(4242, "ETH", source=_src_hist)
check(hist.get("partial") is True,
      f"признак неполной истории потерялся по дороге к клиенту: {hist}")

# ── 6. Реестры не разъезжаются ───────────────────────────────────────────────
check("ETH" in wallet_link.BALANCE_SOURCES and "ETH" in wallet_link.HISTORY_SOURCES,
      "ETH снова выпал из реестра источников — подпись примем, показать нечего")
check(set(wallet_link.BALANCE_SOURCES) == set(wallet_link.HISTORY_SOURCES),
      "реестры остатка и истории разошлись по составу сетей")
proof_chains = set()
for cur in (_assets.SIGNED_MESSAGE_CURRENCIES | _assets.WALLET_CONNECT_CURRENCIES):
    for net in (_assets.networks_for(cur) or [None]):
        c = _assets.chain_of(cur, net)
        if c:
            proof_chains.add(c)
check(not (proof_chains - set(wallet_link.BALANCE_SOURCES)),
      f"владение принимаем без источника остатка: "
      f"{sorted(proof_chains - set(wallet_link.BALANCE_SOURCES))}")

# ── 7. Остаток подписан активом, а не цепью ──────────────────────────────────
# На счёте TRON лежат и TRX, и USDT. «0.5000 TRON» клиент прочитает как свои
# USDT и увидит не те деньги. Mini App подписывал активом с самого начала, бот —
# нет, и это чинилось вместе с портфелем.
bot_src = read("bot", "main_bot.py")
fn = next((n for n in ast.walk(ast.parse(bot_src))
           if isinstance(n, ast.FunctionDef) and n.name == "_my_wallet_text"), None)
check(fn is not None, "текст кошелька в боте пропал")
if fn:
    body = ast.get_source_segment(bot_src, fn) or ""
    check(":.4f} {w['chain']}" not in body,
          "бот снова подписывает остаток цепью — USDT будет назван TRON")
    check("asset" in body, "бот не читает актив остатка")
    check("portfolio" in body or "summarize" in body,
          "бот считает итог сам, мимо общего движка")

webapp = read("relay", "webapp.html")
check("portfolioRender" in webapp and "w-portfolio" in webapp,
      "в Mini App нет портфеля")
main_src = read("relay-fastapi", "main.py")
check("portfolio" in main_src and "summarize" in main_src,
      "сервер не отдаёт посчитанный портфель")
# Фронт не должен складывать сам: вторая формула цены разойдётся с первой.
check("total_rub" in webapp and "+ a.rub" not in webapp,
      "Mini App складывает стоимость сам, мимо сервера")

if FAILS:
    print(f"❌ Портфель: {len(FAILS)} провал(ов)")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("✅ Портфель: незнание не ноль, актив назван активом, итог один на бот, "
      "сайт и Mini App")
