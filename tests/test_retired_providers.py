#!/usr/bin/env python3
"""Снятый с эксплуатации канал уходит С ОБОИХ концов сразу.

Владелец 03.08.2026: «убери platega и green pay из мониторинга, я их не буду
использовать». Опасность тут не в лишней строке отчёта, а в асимметрии: если
убрать канал только с витрины, роутер продолжит отправлять туда клиентов, а
мы этого больше не увидим. Поэтому один список правит и выбором, и показом —
набор проверяет ровно это равенство.

Боевую БД не трогаем: smart_router.DB_PATH подменяется на временную.

Запуск: /root/bot/venv/bin/python3 tests/test_retired_providers.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

import services.smart_router as sr  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="retired_test_")
DB = Path(_TMP) / "test.db"
sr.DB_PATH = DB

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ {name}")


# Все провайдеры в БД идеально здоровы — включая снятые. Так проверяем именно
# снятие, а не «его и так отфильтровало нездоровье».
def seed():
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS provider_health")
    con.execute("CREATE TABLE provider_health (provider TEXT PRIMARY KEY, "
                "is_healthy INTEGER, failed_count INTEGER, avg_response_time REAL, "
                "last_checked TEXT, status TEXT, blocker TEXT)")
    for name in sr.SHORT_NAMES:
        con.execute("INSERT INTO provider_health VALUES (?,1,0,0.4,?,'READY','')",
                    (name, "2026-08-03T00:00:00"))
    con.commit()
    con.close()


seed()
# Учётные данные, чтобы required_env не выкинул провайдеров раньше снятия.
for env in ("VERTU_LOGIN", "XPAY_API_KEY", "LAVA_SHOP_ID", "STORMTRADE_API_KEY"):
    os.environ[env] = "test"
os.environ.pop("DISABLED_PROVIDERS", None)
os.environ.pop("RETIRED_PROVIDERS", None)
os.environ.pop("PROVIDER_PROFIT_ORDER", None)
os.environ.pop("ESCALATION_CHAIN", None)

RETIRED_CLASSES = ("GreenPayProvider", "PlategaProvider")

# --- сам признак ------------------------------------------------------------
check("снятые по умолчанию — platega и greenpay",
      sr.get_retired_providers() == {"platega", "greenpay"})
check("признак понимает имя класса", sr.is_provider_retired("GreenPayProvider"))
check("признак понимает короткое имя", sr.is_provider_retired("platega"))
check("признак понимает суффикс варианта", sr.is_provider_retired("greenpay:card"))
check("живой канал не считается снятым",
      not sr.is_provider_retired("BrabusProvider") and not sr.is_provider_retired("vertu"))

# --- витрина ----------------------------------------------------------------
scores = sr.get_health_scores()
check("витрина здоровья не показывает снятых",
      all(c not in scores for c in RETIRED_CLASSES))
check("витрина здоровья показывает живых",
      "BrabusProvider" in scores and "VertuProvider" in scores)

trust = sr.get_trust_metrics()
check("снятые не считаются живыми маршрутами",
      trust["active_routes"] == len([n for n, cfg in sr.PROVIDER_CONFIG.items()
                                     if not cfg.get("last_resort")
                                     and not sr.is_provider_retired(n)]))

# --- денежный путь ----------------------------------------------------------
# Ключевая проверка: снятый канал НЕ выбирается, хотя в БД он здоров, а из
# витрины его уже вырезали (то есть «нет данных» здесь = «не спрашивать»).
chosen = {sr.choose_provider(10000) for _ in range(400)}
check("выбор ни разу не приводит к снятому каналу",
      not (chosen & set(RETIRED_CLASSES)))
check("выбор при этом работает (живые каналы выбираются)",
      bool(chosen - {None}))

# Решающий случай, детерминированно. Все живые каналы выключены kill-switch'ем,
# в БД снятый провайдер здоров — если бы снятие жило только на витрине, он
# остался бы ЕДИНСТВЕННЫМ кандидатом и забрал бы заявку (choose_provider
# трактует отсутствие данных о здоровье как «здоров»). Правильный ответ —
# штатный резерв, а не «отправим туда, куда больше не смотрим».
os.environ["DISABLED_PROVIDERS"] = ",".join(
    s for c, s in sr.SHORT_NAMES.items() if c not in RETIRED_CLASSES)
check("снятый канал не становится последним кандидатом",
      sr.choose_provider(10000) not in RETIRED_CLASSES)
del os.environ["DISABLED_PROVIDERS"]

chain = sr.get_escalation_chain()
check("эскалация не содержит снятых",
      not ({"greenpay", "platega"} & set(chain)) and chain)

order = sr.get_profit_order()
check("порядок выгоды не содержит снятых",
      not ({"greenpay", "platega"} & set(order)) and order)

# Env-цепочка не должна воскрешать снятый канал: ESCALATION_CHAIN правится
# оператором на лету, а решение о снятии живёт в коде.
os.environ["ESCALATION_CHAIN"] = "greenpay,platega,fallback"
check("env-цепочка не воскрешает снятого",
      set(sr.get_escalation_chain()) == {"fallback"})
os.environ["ESCALATION_CHAIN"] = "greenpay,platega"
check("цепочка целиком из снятых → штатный резерв, а не пустота",
      sr.get_escalation_chain() == ["stormtrade", "fallback"])
del os.environ["ESCALATION_CHAIN"]

os.environ["PROVIDER_PROFIT_ORDER"] = "greenpay,platega,brabus"
check("env-порядок выгоды не воскрешает снятого",
      sr.get_profit_order() == ["brabus"])
del os.environ["PROVIDER_PROFIT_ORDER"]

# --- возврат в строй --------------------------------------------------------
os.environ["RETIRED_PROVIDERS"] = ""
check("пустой RETIRED_PROVIDERS возвращает канал на витрину",
      "GreenPayProvider" in sr.get_health_scores())
# В выбор возвращаем через эскалацию: она детерминирована, а weighted-выбор
# дал бы снятому каналу мизерный вес (его нет в порядке выгоды) — тест бы
# мигал по случайности, а не по сути.
os.environ["ESCALATION_CHAIN"] = "greenpay,fallback"
check("и в денежный путь", "greenpay" in sr.get_escalation_chain())
del os.environ["ESCALATION_CHAIN"]
os.environ["RETIRED_PROVIDERS"] = "brabus"
check("список настраивается: снят другой канал",
      sr.is_provider_retired("BrabusProvider")
      and not sr.is_provider_retired("greenpay"))
del os.environ["RETIRED_PROVIDERS"]

# --- дверь вебхука ----------------------------------------------------------
# У снятого канала не должно остаться живого входа «пометить оплаченным».
MAIN = open(os.path.join(ROOT, "relay-fastapi", "main.py"), encoding="utf-8").read()
gp = MAIN[MAIN.index('@app.post("/greenpay/webhook")'):]
gp = gp[:gp.index("\n@app.")]
check("вебхук снятого канала проверяет снятие", "is_provider_retired" in gp)
check("вебхук снятого канала не верит пустому ключу",
      "if not GREENPAY_API_SECRET" in gp)
check("отказ идёт ДО разбора тела",
      gp.index("is_provider_retired") < gp.index("await request.body()"))

print(f"\n{ok} проверок пройдено, {fail} провал(ов)")
sys.exit(1 if fail else 0)
