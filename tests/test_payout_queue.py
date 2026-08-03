#!/usr/bin/env python3
"""Очередь разбора: возраст, порядок, SLA и то, что видит клиент.

Запуск: python3 tests/test_payout_queue.py
"""
import os
import re
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
    return cond


def _mkdb():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.sqlite")
    c = sqlite3.connect(p)
    c.executescript("""
    CREATE TABLE orders(order_id INT PRIMARY KEY, user_id INT, username TEXT,
        rub_amount REAL, currency TEXT, crypto_address TEXT, network TEXT,
        status TEXT, created_at TEXT, updated_at TEXT, receipt_sent_at TEXT,
        paid_btc_tx TEXT);
    CREATE TABLE order_receipts(order_id INT, created_at TEXT);
    CREATE TABLE sent_notifications(order_id INTEGER, event TEXT,
        PRIMARY KEY (order_id, event));
    """)
    return p, c


def _order(c, oid, status, minutes_ago, rub=1000, txid=None, updated=True):
    ts = f"datetime('now','-{minutes_ago} minutes')"
    c.execute(f"INSERT INTO orders VALUES (?,5,'u',?,'BTC','addr',NULL,?,{ts},"
              f"{ts if updated else 'NULL'},NULL,?)", (oid, rub, status, txid))


def main():
    p, c = _mkdb()
    os.environ["DB_PATH"] = p
    import core.payout_queue as q
    q.DB_PATH = p

    # ── SLA-пороги ────────────────────────────────────────────────────
    check(q.sla_level(1) == "ok", "свежая заявка не 'ok'")
    check(q.sla_level(q.SLA_WARN_MIN) == "warn", "порог warn не срабатывает ровно на границе")
    check(q.sla_level(q.SLA_BREACH_MIN) == "breach", "порог breach не срабатывает на границе")
    # Возраст неизвестен — это НЕ «свежая». Древние заявки без updated_at так и
    # прятались в конец списка, где их никто не видел.
    check(q.sla_level(None) == "breach", "неизвестный возраст считается нормой")
    check(q.sla_level("мусор") == "breach", "нечисловой возраст считается нормой")

    check(q.human_age(18) == "18 мин", f"возраст 18 мин читается как {q.human_age(18)}")
    check(q.human_age(220).startswith("3 ч"), f"220 мин → {q.human_age(220)}")
    check(q.human_age(3000).startswith("2 сут"), f"3000 мин → {q.human_age(3000)}")

    # ── что попадает в очередь ────────────────────────────────────────
    _order(c, 1, "paid", 5, rub=1000)                    # свежая оплата, ok
    _order(c, 2, "paid", 90, rub=5000)                   # просрочена, warn
    _order(c, 3, "paid", 600, rub=31000)                 # грубо просрочена
    _order(c, 4, "paid", 300, rub=7000, txid="abc")      # выдана — не долг
    _order(c, 5, "sent", 300, rub=7000, txid="abc")      # завершена
    _order(c, 6, "pending", 300, rub=2000)               # без чека — не наш долг
    _order(c, 7, "expired", 800, rub=4000)               # закрыта, чека нет
    c.execute("INSERT INTO orders VALUES (8,5,'u',9000,'BTC','a',NULL,'pending',"
              "datetime('now','-200 minutes'),datetime('now','-200 minutes'),NULL,NULL)")
    c.execute("INSERT INTO order_receipts VALUES (8, datetime('now','-180 minutes'))")
    c.commit()

    rows = q.queue()
    ids = [r["order_id"] for r in rows]
    check(set(ids) == {1, 2, 3, 8}, f"состав очереди неверен: {ids}")
    check(4 not in ids and 5 not in ids, "выданная заявка осталась долгом")
    check(6 not in ids and 7 not in ids, "заявка без чека и без оплаты попала в очередь")

    # ── порядок: самые старые первыми ─────────────────────────────────
    check(ids[0] == 3, f"первой в очереди должна быть самая старая, а не #{ids[0]}")
    ages = [r["age_min"] for r in rows]
    check(ages == sorted(ages, reverse=True), f"очередь не отсортирована по возрасту: {ages}")

    by_id = {r["order_id"]: r for r in rows}
    check(by_id[1]["sla"] == "ok", "свежая оплата помечена просроченной")
    check(by_id[2]["sla"] == "warn", "90-минутная оплата не помечена warn")
    check(by_id[3]["sla"] == "breach", "10-часовая оплата не помечена breach")
    check(by_id[8]["kind"] == q.KIND_RECEIPT, "заявка с чеком помечена не тем видом долга")
    check(by_id[3]["kind"] == q.KIND_PAYOUT, "оплаченная заявка помечена не тем видом долга")

    # ── фильтр по виду долга ──────────────────────────────────────────
    only_pay = {r["order_id"] for r in q.queue(kind=q.KIND_PAYOUT)}
    check(only_pay == {1, 2, 3}, f"фильтр payout вернул {only_pay}")
    only_rcpt = {r["order_id"] for r in q.queue(kind=q.KIND_RECEIPT)}
    check(only_rcpt == {8}, f"фильтр receipt вернул {only_rcpt}")

    # ── шапка ─────────────────────────────────────────────────────────
    s = q.summary(rows)
    check(s["count"] == 4, f"счёт строк: {s['count']}")
    check(abs(s["rub"] - 46000) < 0.01, f"сумма долга: {s['rub']}")
    # #3 (10 ч) — breach; #8 (3 ч) и #2 (1,5 ч) — warn; #1 — ok.
    check(s["breach"] == 1, f"просроченных грубо: {s['breach']}")
    check(s["warn"] == 2, f"просроченных: {s['warn']}")
    check(s["oldest_id"] == 3, f"самая старая: {s['oldest_id']}")

    # ── что видит клиент ──────────────────────────────────────────────
    check(q.client_state(1)["delayed"] is False, "клиенту свежей заявки обещают задержку")
    check(q.client_state(2)["delayed"] is True, "клиент просроченной заявки не узнает о задержке")
    check(q.client_state(4)["delayed"] is False, "по выданной заявке клиенту говорят о задержке")
    check(q.client_state(999)["delayed"] is False, "несуществующая заявка объявлена задержанной")
    # Пороги персонала и клиента — одни и те же: иначе клиенту «всё по плану»
    # ровно тогда, когда у оператора строка красная.
    for oid in (1, 2, 3):
        st = q.client_state(oid)
        check(st["delayed"] == (by_id[oid]["sla"] != "ok"),
              f"#{oid}: клиент и оператор видят разное состояние заявки")

    # ── заявка без updated_at: самая старая, а не самая свежая ────────
    _order(c, 9, "paid", 0, rub=100, updated=False)
    c.execute("UPDATE orders SET created_at=NULL WHERE order_id=9")
    c.commit()
    rows2 = q.queue()
    check(rows2[0]["order_id"] == 9,
          f"заявка без отметок времени встала не первой: {[r['order_id'] for r in rows2]}")
    check(rows2[0]["sla"] == "breach", "заявка без отметок времени сочтена свежей")

    # ── сбой БД: очередь пуста, а не исключение наружу ────────────────
    q.DB_PATH = "/nonexistent/dir/x.sqlite"
    check(q.queue() == [], "при сбое БД очередь не пуста")
    check(q.client_state(1)["delayed"] is False, "при сбое БД клиенту обещают задержку")
    q.DB_PATH = p

    # ── база без таблицы чеков: половина очереди живёт ────────────────
    c.execute("DROP TABLE order_receipts")
    c.commit()
    rows3 = q.queue()
    check({r["order_id"] for r in rows3} >= {1, 2, 3},
          "без таблицы чеков пропала и половина про выплаты")

    # ── итог считается по ДОЛГАМ, а не по размеру экрана ──────────────
    # summary() честно суммирует то, что ей дали, — значит ошибиться можно
    # только у вызывающего: срезал список для показа и по нему же посчитал шапку.
    # Тогда «в очереди 15 на N ₽» описывает экран, и чем больше долгов, тем
    # меньше их видно. Нашёл codex.
    many = [{"order_id": i, "rub_amount": 100, "sla": "breach", "age_human": "1 ч"}
            for i in range(40)]
    check(q.summary(many)["count"] == 40 and q.summary(many)["rub"] == 4000,
          "summary считает не всё, что ей дали")
    check(q.summary(many[:15])["count"] == 15,
          "срезанный список даёт срезанный итог — значит резать до подсчёта нельзя")

    bot_src = open(os.path.join(ROOT, "bot", "main_bot.py"), encoding="utf-8").read()
    m = re.search(r"rows\s*=\s*_pq\.queue\(limit=(\d+)\)\s*\n(?:.*\n){0,12}?"
                  r"\s*s\s*=\s*_pq\.summary\(rows\)", bot_src)
    check(m is None,
          "бот считает шапку очереди по срезанному списку — долги сверх экрана "
          "исчезают из итога")

    main_src = open(os.path.join(ROOT, "relay-fastapi", "main.py"), encoding="utf-8").read()
    m2 = re.search(r"_delayed_ids[\s\S]{0,900}?_pq\.queue\(limit=(\d+)", main_src)
    check(m2 is None or int(m2.group(1)) >= 10 ** 5,
          "признак задержки берётся из первых N строк очереди — при большом "
          "числе долгов часть клиентов перестанет видеть отметку")

    if FAILS:
        print(f"❌ Провалов: {len(FAILS)}\n")
        for m in FAILS:
            print("  •", m)
        return 1
    print("✅ Очередь разбора: возраст, порядок, SLA, фильтры, шапка и состояние "
          "для клиента — согласованы.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
