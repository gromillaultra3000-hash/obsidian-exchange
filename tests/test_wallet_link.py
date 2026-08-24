#!/usr/bin/env python3
"""Баланс показывается только по адресу, владение которым доказано.

Этап 3 бэклога, шаг 1: просмотр баланса подключённого кошелька. Опасность здесь
одна и вся в вопросе «чей адрес». Если адрес принять из запроса, обменник
становится бесплатным пробником чужих кошельков от нашего IP, а клиенту
рисуется «ваш баланс» под чужим адресом. Поэтому источник адреса ровно один —
таблица подтверждённых связей.

Второе свойство: «не знаем» не превращается в ноль. Недоступный обозреватель и
пустой счёт — разные новости для того, кто собрался платить.

Боевую БД не трогаем: DB_PATH подменён на временный файл.

Запуск: /root/bot/venv/bin/python3 tests/test_wallet_link.py
"""
import ast
import inspect
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

_TMP = tempfile.mkdtemp(prefix="wallet_link_test_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
with sqlite3.connect(os.environ["DB_PATH"]) as _fixture_db:
    _fixture_db.execute(
        "CREATE TABLE wallet_links (user_id INTEGER, chain TEXT, address TEXT, "
        "verified_at TEXT, PRIMARY KEY(user_id,chain))"
    )

from core import wallet_link as wl  # noqa: E402

wl.DB_PATH = os.environ["DB_PATH"]

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ {name}")


ALICE, BOB = 111, 222
A_ADDR = "UQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqEBI"
B_ADDR = "UQAvlWFDxGF2lXm67y4yzC17wYKD9A0guwPkMs1gOsM__NOT"

# --- запоминание и чтение ---------------------------------------------------
check("до подключения кошельков нет", wl.links_for(ALICE) == [])
check("связь сохраняется", wl.remember(ALICE, "TON", A_ADDR))
check("связь читается", [l["address"] for l in wl.links_for(ALICE)] == [A_ADDR])
check("адрес отдаётся по сети", wl.address_for(ALICE, "TON") == A_ADDR)
check("чужой сети нет", wl.address_for(ALICE, "BTC") is None)
check("чужой клиент не видит связь", wl.links_for(BOB) == [])

wl.remember(ALICE, "TON", B_ADDR)
check("переподключение заменяет адрес, а не копит",
      [l["address"] for l in wl.links_for(ALICE)] == [B_ADDR])
wl.remember(ALICE, "TON", A_ADDR)

check("мусорный вход не сохраняется",
      not wl.remember(None, "TON", A_ADDR) and not wl.remember(ALICE, "TON", "")
      and not wl.remember(ALICE, "", A_ADDR))
check("нечисловой клиент не ломает чтение", wl.links_for("не-число") == [])

# --- балансы ----------------------------------------------------------------
asked = []


def fake_ok(address):
    asked.append(address)
    return {"balance": 12.5, "status": "OK", "reason": None}


def fake_down(address):
    asked.append(address)
    return {"balance": None, "status": "ERROR", "reason": "toncenter молчит"}


def fake_boom(address):
    raise RuntimeError("сеть отвалилась")


asked.clear()
bal = wl.balances_for(ALICE, source=fake_ok)
check("баланс отдаётся по подключённому кошельку",
      len(bal) == 1 and bal[0]["balance"] == 12.5 and bal[0]["chain"] == "TON")
check("спрашивали ровно подтверждённый адрес", asked == [A_ADDR])

bal = wl.balances_for(ALICE, source=fake_down)
check("недоступный обозреватель — это не ноль", bal[0]["balance"] is None)
check("и статус честный", bal[0]["status"] == "ERROR" and bal[0]["reason"])

bal = wl.balances_for(ALICE, source=fake_boom)
check("падение источника не роняет ответ",
      len(bal) == 1 and bal[0]["balance"] is None and bal[0]["status"] == "ERROR")

check("у клиента без кошелька балансов нет", wl.balances_for(BOB, source=fake_ok) == [])

# Главное правило, проверяем по сигнатуре: функцию НЕЧЕМ позвать за чужой
# кошелёк — адрес не является её аргументом.
params = set(inspect.signature(wl.balances_for).parameters)
check("balances_for не принимает адрес аргументом",
      not ({"address", "addr", "wallet"} & params))

# --- история ----------------------------------------------------------------
asked_hist = []


def hist_ok(address, limit=20):
    asked_hist.append((address, limit))
    return {"items": [
        {"direction": "in", "amount": 3.0, "counterparty": "UQFrom",
         "comment": "", "ts": 1785000000, "txid": "AAA", "fee": 0.001},
        {"direction": "out", "amount": 1.0, "counterparty": "UQTo",
         "comment": "", "ts": 1784000000, "txid": "BBB", "fee": 0.001},
    ], "status": "OK", "reason": None}


def hist_down(address, limit=20):
    return {"items": [], "status": "ERROR", "reason": "toncenter молчит"}


def hist_boom(address, limit=20):
    raise RuntimeError("сеть отвалилась")


asked_hist.clear()
h = wl.history_for(ALICE, source=hist_ok)
check("история отдаётся по подключённому кошельку",
      h["status"] == "OK" and len(h["items"]) == 2)
check("история спрашивалась ровно по подтверждённому адресу",
      asked_hist and asked_hist[0][0] == A_ADDR)
check("в ответе указан адрес, по которому смотрели", h["address"] == A_ADDR)

h = wl.history_for(ALICE, source=hist_down)
check("недоступная история не выдаётся за «операций нет»",
      h["items"] == [] and h["status"] == "ERROR")
h = wl.history_for(ALICE, source=hist_boom)
check("падение источника истории не роняет ответ",
      h["items"] == [] and h["status"] == "ERROR")

h = wl.history_for(BOB, source=hist_ok)
check("у клиента без кошелька истории нет",
      h["items"] == [] and h["status"] == "NOT_CONNECTED")
check("неизвестная сеть — честный отказ, а не пустая история",
      wl.history_for(ALICE, chain="BTC", source=None)["status"] in ("NOT_CONNECTED",
                                                                    "UNSUPPORTED"))

hist_params = set(inspect.signature(wl.history_for).parameters)
check("history_for не принимает адрес аргументом",
      not ({"address", "addr", "wallet"} & hist_params))

# --- отключение -------------------------------------------------------------
check("отключение снимает связь", wl.forget(ALICE, "TON") == 1)
check("после отключения кошельков нет", wl.links_for(ALICE) == [])
check("повторное отключение безвредно", wl.forget(ALICE, "TON") == 0)

wl.remember(ALICE, "TON", A_ADDR)
wl.remember(BOB, "TON", B_ADDR)
check("отключение чужого клиента не трогает наш",
      wl.forget(BOB) == 1 and wl.address_for(ALICE, "TON") == A_ADDR)

# --- эндпоинты: адрес не приходит снаружи -----------------------------------
MAIN = open(os.path.join(ROOT, "relay-fastapi", "main.py"), encoding="utf-8").read()
tree = ast.parse(MAIN)
handlers = {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

links = handlers.get("api_wallet_links")
check("эндпоинт балансов существует", links is not None)
if links:
    src = ast.get_source_segment(MAIN, links) or ""
    check("эндпоинт балансов требует подписанный initData", "verify_init_data" in src)
    check("эндпоинт балансов не читает адрес из запроса",
          "query_params" not in src and "request.json" not in src)
    check("эндпоинт балансов зовёт хранилище связей", "balances_for" in src)

verify = handlers.get("tonconnect_verify")
if verify:
    src = ast.get_source_segment(MAIN, verify) or ""
    check("связь запоминается только при положительном вердикте",
          'if verdict["verified"]' in src and "remember" in src)

# --- карточка кошелька на сайте ---------------------------------------------
# Шаблон рисуется отдельно от кода, и ошибка в нём молчит до открытия страницы.
# Тут уже поймано: `wallet_ops.items` в Jinja — это МЕТОД словаря, а не список
# операций, страница падала с TypeError.
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    Environment = None

if Environment is not None:
    tpl_dir = os.path.join(ROOT, "relay-fastapi", "templates")
    env = Environment(loader=FileSystemLoader(tpl_dir), autoescape=select_autoescape())
    env.filters["tsfmt"] = lambda ts: "01.01 00:00"
    page = open(os.path.join(tpl_dir, "dashboard_profile.html"), encoding="utf-8").read()
    card = page[page.index('<div class="dash-card">\n    <h2>🔌'):
                page.index('<div class="dash-card">\n    <h2>🔐')]
    tpl = env.from_string(card)

    class _U(dict):
        __getattr__ = dict.get

    def render(tg_id, wallets, ops):
        return tpl.render(web_user=_U(telegram_id=tg_id), wallets=wallets, wallet_ops=ops)

    W = [{"chain": "TON", "address": "UQabc", "balance": 2.5}]
    W_UNK = [{"chain": "TON", "address": "UQabc", "balance": None}]
    OPS = {"status": "OK", "chain": "TON",
           "items": [{"ts": 1785000000, "direction": "in", "amount": 2.5,
                      "counterparty": "UQx"}]}
    try:
        out_ok = render(1, W, OPS)
        out_down = render(1, W_UNK, {"status": "ERROR", "chain": "TON", "items": []})
        out_empty = render(1, W, {"status": "OK", "chain": "TON", "items": []})
        out_none = render(None, [], None)
        rendered = True
    except Exception as e:
        rendered = False
        check(f"карточка кошелька рендерится ({type(e).__name__}: {e})", False)
    if rendered:
        check("на сайте видна сумма операции", "2.5000" in out_ok and "получено" in out_ok)
        check("на сайте недоступный баланс не выдан за ноль",
              "баланс недоступен" in out_down)
        check("на сайте недоступная история не выдана за «операций нет»",
              "История сейчас недоступна" in out_down)
        check("на сайте пустая история названа пустой",
              "Операций по кошельку пока нет" in out_empty)
        check("без привязки Telegram сказано, где подключать",
              "подключается в Telegram" in out_none)

print(f"\n{ok} проверок пройдено, {fail} провал(ов)")
sys.exit(1 if fail else 0)
