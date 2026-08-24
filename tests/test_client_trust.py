#!/usr/bin/env python3
"""Порог доверия клиента: кому какой платёжный канал открыт.

Провайдеры P2P просят направлять к их трейдерам только проверенных клиентов —
у Montera это ≥1 закрытая сделка, у Vertu с 06.08.2026 ≥4 (жалобы на поддельные
PDF-чеки). Здесь проверяется главное: правило одно на ВСЕ входы к провайдеру.
Спрятанная кнопка ничего не значит, если тот же канал достаётся авто-выбором,
эскалацией или прямой ссылкой из старого сообщения.
"""
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

_DB = os.path.join(tempfile.mkdtemp(prefix="trust-"), "t.db")
os.environ["DB_PATH"] = _DB
# Учётные данные каналов, которые участвуют в выборе: без них роутер их
# скипает раньше порога, и проверять было бы нечего.
os.environ.setdefault("VERTU_LOGIN", "login")
os.environ.setdefault("VERTU_PASSWORD", "pass")

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


conn = sqlite3.connect(_DB)
conn.execute("""CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT, user_id INTEGER, status TEXT)""")
conn.execute("""CREATE TABLE provider_health (
    provider TEXT PRIMARY KEY, is_healthy INTEGER, last_checked TEXT,
    avg_response_time REAL, failed_count INTEGER, status TEXT, blocker TEXT
)""")
# 111 — новичок, 222 — две сделки, 333 — четыре, 444 — четыре, но половина
# заявок в статусах, которые оплатой не считаются.
rows = [(111, "pending")]
rows += [(222, "paid")] * 2
rows += [(333, "paid")] * 2 + [(333, "sent"), (333, "completed")]
rows += [(444, "paid")] * 2 + [(444, "expired"), (444, "cancelled"), (444, "failed")]
conn.executemany("INSERT INTO orders (user_id, status) VALUES (?,?)", rows)
conn.commit()
conn.close()

from core import client_trust as ct  # noqa: E402
from services import smart_router as sr  # noqa: E402

# ── 1. Счёт сделок ───────────────────────────────────────────────────────────
check(ct.paid_deals(111, use_cache=False) == 0, "новичку насчитали сделки")
check(ct.paid_deals(222, use_cache=False) == 2, "две сделки посчитаны неверно")
check(ct.paid_deals(333, use_cache=False) == 4,
      "paid/sent/completed считаются не все — клиент, доведший заявку до "
      "выдачи крипты, выглядел бы новичком")
check(ct.paid_deals(444, use_cache=False) == 2,
      "истёкшие и отменённые заявки зачтены как оплаченные — порог обходился "
      "бы созданием заявок, которые никто не оплачивал")

# Неизвестный клиент — ноль. Ошибиться сюда значит показать проверенному
# клиенту другой канал; в обратную — привести к трейдеру незнакомца.
for bad in (None, "", "не число", 0, -17):
    check(ct.paid_deals(bad, use_cache=False) == 0,
          f"клиент {bad!r} получил ненулевой счёт сделок")

# ── 2. Порог канала ──────────────────────────────────────────────────────────
check(ct.min_deals("VertuProvider") == 4,
      "порог Vertu не 4 — провайдер просил именно столько")
check(ct.min_deals("MonteraProvider") == 1, "порог Montera не 1")
check(ct.min_deals("BrabusProvider") == 0,
      "каналу без требования приписан порог — часть клиентов потеряла бы "
      "рабочий маршрут ни за что")
check(ct.min_deals("СовершенноНеизвестный") == 0, "неизвестный канал получил порог")

saved = os.environ.get("MIN_DEALS_VERTU")
os.environ["MIN_DEALS_VERTU"] = "2"
check(ct.min_deals("VertuProvider") == 2,
      "порог не переопределяется переменной окружения — требование приходит "
      "письмом от провайдера и меняется без нашего релиза")
os.environ["MIN_DEALS_VERTU"] = "нисколько"
check(ct.min_deals("VertuProvider") == 4,
      "мусор в переменной окружения снял порог вместо того, чтобы отступить "
      "к значению реестра")
if saved is None:
    os.environ.pop("MIN_DEALS_VERTU", None)
else:
    os.environ["MIN_DEALS_VERTU"] = saved

# ── 3. Решение по клиенту ────────────────────────────────────────────────────
ct.forget()
check(not ct.allows("VertuProvider", 111), "новичок допущен к Vertu")
check(not ct.allows("VertuProvider", 222),
      "клиент с двумя сделками допущен к Vertu — порог четыре")
check(ct.allows("VertuProvider", 333), "клиент с четырьмя сделками не допущен к Vertu")
check(ct.allows("MonteraProvider", 222), "повторный клиент не допущен к Montera")
check(not ct.allows("MonteraProvider", 111), "новичок допущен к Montera")
check(ct.allows("BrabusProvider", 111),
      "канал без порога закрылся для новичка — обменник перестал бы работать "
      "для новых клиентов вовсе")
check(not ct.allows("VertuProvider", None),
      "клиент без Telegram-идентификатора допущен к каналу для повторных")

why = ct.refuse_reason("VertuProvider", 222)
check("4" in why and "2" in why,
      f"причина отказа не называет ни порога, ни счёта клиента: {why!r}")
check(ct.refuse_reason("VertuProvider", 333) == "",
      "у допущенного клиента нашлась причина отказа")
check(ct.refuse_reason("BrabusProvider", 111) == "",
      "канал без порога назвал причину отказа")

# ── 4. Тот же порог в выборе провайдера ──────────────────────────────────────
# Кнопку спрятать мало: авто-выбор — отдельная дверь к тому же трейдеру.
ct.forget()
picked_new = {sr.choose_provider(10000, telegram_id=111) for _ in range(400)}
check("VertuProvider" not in picked_new,
      "авто-выбор отдаёт Vertu новичку — провайдер увидит ровно то, на что "
      "жаловался, просто мимо кнопки")
check("MonteraProvider" not in picked_new, "авто-выбор отдаёт Montera новичку")
check(picked_new - {None},
      "новичку не достался НИ ОДИН канал — порог отрезал обменник целиком")

picked_trusted = {sr.choose_provider(10000, telegram_id=333) for _ in range(400)}
check("VertuProvider" in picked_trusted,
      "проверенный клиент не получает Vertu — порог отсекает тех, для кого "
      "он и вводился наоборот")

# Клиент не назван — считаем новым. Иначе любой вызов без него становится
# дырой в требовании провайдера.
picked_unknown = {sr.choose_provider(10000) for _ in range(400)}
check("VertuProvider" not in picked_unknown and "MonteraProvider" not in picked_unknown,
      "выбор без указания клиента раздаёт каналы для повторных — тихая дыра "
      "в требовании провайдера")

check(sr.client_trust_refusal("VertuProvider", 111),
      "общий вход в реестр порогов не отказывает новичку")
check(sr.client_trust_refusal("VertuProvider", 333) == "",
      "общий вход отказывает проверенному клиенту")

# ── 5. Кеш не переживает закрытие сделки ─────────────────────────────────────
check(ct.paid_deals(222) == 2, "кеш испортил счёт")
conn = sqlite3.connect(_DB)
conn.executemany("INSERT INTO orders (user_id, status) VALUES (?,?)",
                 [(222, "paid")] * 2)
conn.commit()
conn.close()
check(ct.paid_deals(222) == 2, "кеша нет вовсе — счёт спрашивается у базы на каждый чих")
ct.forget(222)
check(ct.paid_deals(222) == 4,
      "после сброса кеша счёт не обновился — клиент, закрывший четвёртую "
      "сделку, ждал бы доступа неизвестно сколько")

if FAILS:
    print(f"❌ Порог доверия: {len(FAILS)} провал(ов)")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("✅ Порог доверия: счёт сделок, пороги каналов и отсечение в авто-выборе "
      "работают одинаково на всех входах")
