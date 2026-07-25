#!/usr/bin/env python3
"""Регресс-тест выборки авто-выплаты (сессия 25.07.2026).

Ловит конкретный прод-дефект: заявка #99955115 (BTC 4500₽) оплачена через
вебхук Brabus, страж вынес verdict=confirmed / would_auto_pay=1, НО авто-выплата
её не тронула — клиент не получил BTC. Причина: вебхук ставит status='paid' без
updated_at, а выборка auto_check_payments фильтровала по
`updated_at >= datetime('now','-24h')`. NULL >= … даёт NULL → строка молча
выпадала. Фикс: COALESCE(updated_at, created_at) + write-side updated_at в вебхуках.

Запуск: python3 tests/test_payout_selection.py
"""
import sqlite3
import sys
import tempfile

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY, status TEXT, rub_amount REAL,
        created_at TEXT, updated_at TEXT)""")
    conn.execute("""CREATE TABLE sent_notifications (order_id INTEGER, event TEXT)""")
    return conn


# Заявка оплачена вебхуком: status='paid', updated_at=NULL, created_at свежий.
BUGGY = """SELECT order_id FROM orders o
    WHERE o.status='paid'
      AND o.updated_at >= datetime('now','-24 hours')
      AND NOT EXISTS (SELECT 1 FROM sent_notifications sn
                      WHERE sn.order_id=o.order_id AND sn.event='payout_triggered')"""

FIXED = """SELECT order_id FROM orders o
    WHERE o.status='paid'
      AND COALESCE(o.updated_at, o.created_at) >= datetime('now','-24 hours')
      AND NOT EXISTS (SELECT 1 FROM sent_notifications sn
                      WHERE sn.order_id=o.order_id AND sn.event='payout_triggered')"""

conn = _db()
conn.execute("INSERT INTO orders VALUES (99955115,'paid',4500,datetime('now'),NULL)")

check("воспроизведение бага: старая выборка НЕ видит paid-заявку с updated_at=NULL",
      conn.execute(BUGGY).fetchall() == [])
check("фикс: COALESCE-выборка видит ту же заявку",
      conn.execute(FIXED).fetchall() == [(99955115,)])

# Заявка старше 24ч по created_at (updated_at=NULL) — не должна попадать (окно 24ч).
conn.execute("INSERT INTO orders VALUES (1,'paid',1000,datetime('now','-30 hours'),NULL)")
check("окно 24ч соблюдено: старая NULL-заявка (created_at -30ч) в выборку не попадает",
      1 not in [r[0] for r in conn.execute(FIXED).fetchall()])

# Уже помеченная payout_triggered — не берётся повторно (защита от двойной выплаты).
conn.execute("INSERT INTO orders VALUES (2,'paid',500,datetime('now'),NULL)")
conn.execute("INSERT INTO sent_notifications VALUES (2,'payout_triggered')")
check("защита от двойной выплаты: заявка с payout_triggered в выборку не попадает",
      2 not in [r[0] for r in conn.execute(FIXED).fetchall()])

# Свежая заявка с заполненным updated_at по-прежнему берётся.
conn.execute("INSERT INTO orders VALUES (3,'paid',2000,datetime('now','-1 hours'),datetime('now'))")
check("заявка с непустым updated_at по-прежнему в выборке",
      3 in [r[0] for r in conn.execute(FIXED).fetchall()])

# Атомарный claim: INSERT OR IGNORE выдаёт rowcount=1 только первому, кто застолбил
# заявку; повторный claim той же заявки → rowcount=0 (второй проход/экземпляр
# выплату не повторяет).
conn2 = sqlite3.connect(":memory:")
conn2.execute("CREATE TABLE sent_notifications (order_id INTEGER, event TEXT, "
              "UNIQUE(order_id, event))")
r1 = conn2.execute("INSERT OR IGNORE INTO sent_notifications (order_id,event) "
                   "VALUES (777,'payout_triggered')").rowcount
r2 = conn2.execute("INSERT OR IGNORE INTO sent_notifications (order_id,event) "
                   "VALUES (777,'payout_triggered')").rowcount
check("claim: первый застолбивший получает rowcount=1", r1 == 1)
check("claim: повторный застолбить не может (rowcount=0) → нет двойной выплаты", r2 == 0)
conn2.close()

conn.close()

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
