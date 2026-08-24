"""Троттлинг алертов должен переживать рестарт процесса, но не глушить НОВУЮ беду.

Оба свойства проверяем на изолированной БД: боевую не трогаем.
"""
import os
import sqlite3
import sys
import tempfile
import pytest

_TMP = tempfile.mkdtemp(prefix="alert_throttle_test_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
with sqlite3.connect(os.environ["DB_PATH"]) as _schema_conn:
    _schema_conn.executescript(
        "CREATE TABLE alert_throttle(key TEXT PRIMARY KEY,last_sent TEXT NOT NULL);"
        "CREATE TABLE alert_watermark(key TEXT PRIMARY KEY,value INTEGER NOT NULL);"
    )
# Путь к relay — ОТ СЕБЯ, а не боевой абсолютный. С «/root/relay» набор
# проверял прод, а не ветку: правки в worktree он не видел вовсе и
# оставался зелёным на заведомо сломанном коде.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))

from core.alert_throttle import should_send, cleanup  # noqa: E402
from core.conversion_watch import _fingerprint  # noqa: E402

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ {name}")


# --- окно молчания ---------------------------------------------------------
check("первый раз шлём", should_send("k1", 3600) is True)
check("повтор сразу — молчим", should_send("k1", 3600) is False)
check("повтор ещё раз — молчим", should_send("k1", 3600) is False)
check("другой ключ не заблокирован", should_send("k2", 3600) is True)

# нулевой интервал = не троттлим вовсе
check("интервал 0 — всегда шлём", should_send("k3", 0) is True and should_send("k3", 0) is True)

# --- переживает «рестарт» ---------------------------------------------------
# состояние лежит в БД, а не в памяти: перечитываем модуль с нуля
for _m in [m for m in list(sys.modules) if m.startswith("core.alert_throttle")]:
    del sys.modules[_m]
from core.alert_throttle import should_send as should_send2  # noqa: E402

check("после рестарта окно ещё действует", should_send2("k1", 3600) is False)

# --- окно истекло ----------------------------------------------------------
conn = sqlite3.connect(os.environ["DB_PATH"])
conn.execute("UPDATE alert_throttle SET last_sent=datetime('now','-7 hours') WHERE key='k1'")
conn.commit()
conn.close()
check("окно истекло — шлём снова", should_send2("k1", 3600) is True)

# --- пустой ключ не должен молча глушить ------------------------------------
check("пустой ключ — шлём", should_send("", 3600) is True)

# --- fail-open при недоступной БД -------------------------------------------
import core.alert_throttle as at  # noqa: E402
_saved = at.DB_PATH
at.DB_PATH = "/nonexistent-dir-xyz/no.db"
check("БД недоступна — всё равно шлём (fail-open)", at.should_send("k9", 3600) is True)
at.DB_PATH = _saved

# --- отпечатки: состав важен, возраст нет -----------------------------------
a = [{"order_id": 5, "age_min": 10}, {"order_id": 7, "age_min": 99}]
b = [{"order_id": 7, "age_min": 900}, {"order_id": 5, "age_min": 1}]
c = [{"order_id": 5, "age_min": 10}, {"order_id": 7, "age_min": 99}, {"order_id": 9, "age_min": 1}]
check("возраст и порядок не меняют отпечаток",
      _fingerprint("stuck_payout", a) == _fingerprint("stuck_payout", b))
check("новая заявка меняет отпечаток",
      _fingerprint("stuck_payout", a) != _fingerprint("stuck_payout", c))
check("тип входит в отпечаток",
      _fingerprint("stuck_payout", a) != _fingerprint("receipt_undelivered", a))

# ключевой сценарий: молчим про старое, но кричим про новое
key_a = "conv:" + _fingerprint("stuck_payout", a)
key_c = "conv:" + _fingerprint("stuck_payout", c)
check("первый алерт про {5,7} уходит", should_send(key_a, 21600) is True)
check("повтор про {5,7} молчит", should_send(key_a, 21600) is False)
check("появилась заявка 9 — алерт уходит немедленно", should_send(key_c, 21600) is True)

# --- уборка ----------------------------------------------------------------
conn = sqlite3.connect(os.environ["DB_PATH"])
conn.execute("UPDATE alert_throttle SET last_sent=datetime('now','-100 days') WHERE key='k2'")
conn.commit()
conn.close()
check("cleanup убирает старое", cleanup(30) == 1)
check("cleanup не трогает свежее", cleanup(30) == 0)

import shutil  # noqa: E402
shutil.rmtree(_TMP, ignore_errors=True)

print(f"alert_throttle: зелёных {ok}, упавших {fail}")
if fail:
    pytest.fail(f"alert throttle self-check failed: {fail}")
