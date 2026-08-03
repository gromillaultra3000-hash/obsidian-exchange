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
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

_TMP = tempfile.mkdtemp(prefix="wallet_link_test_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")

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

print(f"\n{ok} проверок пройдено, {fail} провал(ов)")
sys.exit(1 if fail else 0)
