"""Сверка выдачи с блокчейном: закрывать заявку можно только по
неподделываемому доказательству.

Сеть не трогаем — переводы подаются на вход как данные.
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="discovery_test_")
os.environ["DISCOVERY_SOURCES_PATH"] = os.path.join(_TMP, "sources.json")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
# Путь к relay — ОТ СЕБЯ, а не боевой абсолютный. С «/root/relay» набор
# проверял прод, а не ветку: правки в worktree он не видел вовсе и
# оставался зелёным на заведомо сломанном коде.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))

from core import payout_discovery as pd  # noqa: E402

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ {name}")


OUR = "bc1qourhotwallet"
THEIRS = "bc1qsomeonelse"
ORDER = {"order_id": 1, "expected_amount": 0.001, "paid_ts": 1000,
         "currency": "BTC", "network": "BTC"}
TRUSTED = {OUR}


# confirmations по умолчанию с запасом: у BTC порог два, и перевод «в блоке»
# сам по себе окончательным не считается (core.chain_confirm).
def tx(txid="a" * 64, amount=0.001, ts=2000, sender=OUR, confirmed=True,
       confirmations=6):
    return {"txid": txid, "amount": amount, "ts": ts,
            "senders": {sender}, "confirmed": confirmed,
            "confirmations": confirmations}


# --- закрываем только по переводу из нашего кошелька ------------------------
r = pd.judge(ORDER, [tx()], set(), TRUSTED)
check("наш кошелёк + сумма сошлась → закрыть", r["action"] == "close" and r["txid"] == "a" * 64)

r = pd.judge(ORDER, [tx(sender=THEIRS)], set(), TRUSTED)
check("чужой отправитель → только на рассмотрение", r["action"] == "review")
check("чужой отправитель НЕ даёт txid для закрытия", "txid" not in r)

# ключевой сценарий злоупотребления: клиент сам себе переводит ожидаемую сумму
r = pd.judge(ORDER, [tx(sender="bc1qclientsecondwallet")], set(), TRUSTED)
check("клиент подстроил совпадение сам → не закрываем", r["action"] != "close")

# --- неоднозначность решает человек -----------------------------------------
r = pd.judge(ORDER, [tx(txid="a" * 64), tx(txid="b" * 64)], set(), TRUSTED)
check("два подходящих перевода → на рассмотрение", r["action"] == "review")
check("оба показаны человеку", len(r["candidates"]) == 2)

# --- фильтры ---------------------------------------------------------------
r = pd.judge(ORDER, [tx(amount=0.0005)], set(), TRUSTED)
check("сумма вдвое меньше → не находим", r["action"] == "none")

r = pd.judge(ORDER, [tx(amount=0.001005)], set(), TRUSTED)
check("отклонение 0.5% в пределах допуска → закрываем", r["action"] == "close")

r = pd.judge(ORDER, [tx(amount=0.00102)], set(), TRUSTED)
check("отклонение 2% вне допуска → не находим", r["action"] == "none")

r = pd.judge(ORDER, [tx(ts=500)], set(), TRUSTED)
check("перевод ДО оплаты заявки → не наша выплата", r["action"] == "none")

r = pd.judge(ORDER, [tx(confirmed=False)], set(), TRUSTED)
check("неподтверждённый перевод → не закрываем", r["action"] == "none")

r = pd.judge(ORDER, [tx()], {"a" * 64}, TRUSTED)
check("перевод уже закреплён за другой заявкой → пропускаем", r["action"] == "none")

# --- окончательность в сети -------------------------------------------------
# Закрыть заявку по переводу, который сеть ещё может отменить, — записать
# клиенту выплату, которой не будет. Пороги — в core.chain_confirm.
r = pd.judge(ORDER, [tx(confirmations=1)], set(), TRUSTED)
check("BTC с одним подтверждением → рано закрывать", r["action"] == "none")
check("и сказано, что перевод НАЙДЕН, а не отсутствует",
      "не окончателен" in r["reason"])

r = pd.judge(ORDER, [tx(confirmations=2)], set(), TRUSTED)
check("BTC с двумя подтверждениями → закрываем", r["action"] == "close")

r = pd.judge(ORDER, [tx(confirmations=None)], set(), TRUSTED)
check("источник промолчал о подтверждениях → не закрываем", r["action"] == "none")

# У сетей, где консенсус финализирует леджер сразу, порог единица — там флага
# «в блоке» достаточно, и требовать счётчик значило бы не закрывать никогда.
XRP_ORDER = dict(ORDER, currency="XRP", network="XRP")
r = pd.judge(XRP_ORDER, [tx(confirmations=None)], set(), TRUSTED)
check("XRP: подтверждение одно и оно же окончательное → закрываем",
      r["action"] == "close")

# USDT: сеть решает порог, а не монета.
r = pd.judge(dict(ORDER, currency="USDT", network="TRC20"),
             [tx(confirmations=5)], set(), TRUSTED)
check("USDT-TRC20 с пятью подтверждениями → рано (нужно 19)", r["action"] == "none")
r = pd.judge(dict(ORDER, currency="USDT", network="TRC20"),
             [tx(confirmations=25)], set(), TRUSTED)
check("USDT-TRC20 с 25 подтверждениями → закрываем", r["action"] == "close")

r = pd.judge(dict(ORDER, currency="DOGE", network=None),
             [tx(confirmations=100)], set(), TRUSTED)
check("незнакомая сеть → судить нечем, не закрываем", r["action"] == "none")

r = pd.judge({**ORDER, "expected_amount": 0}, [tx()], set(), TRUSTED)
check("неизвестен ожидаемый объём → ничего не решаем", r["action"] == "none")

r = pd.judge(ORDER, [tx()], set(), set())
check("нет доверенных отправителей → закрыть нечем", r["action"] == "review")

# заявка без paid_ts (древняя): фильтр по времени не должен всё отсекать
r = pd.judge({**ORDER, "paid_ts": 0}, [tx(ts=1)], set(), TRUSTED)
check("нет отметки времени оплаты → перевод всё равно рассматривается",
      r["action"] == "close")

# --- ожидаемый объём -------------------------------------------------------
check("есть зафиксированная котировка — берём её",
      pd.expected_amount({"agreed_crypto_amount": 0.005, "rub_amount": 1000,
                          "currency": "BTC"}, lambda c, r: 100000) == 0.005)
check("котировки нет — считаем по курсу",
      pd.expected_amount({"agreed_crypto_amount": None, "rub_amount": 1000,
                          "currency": "BTC"}, lambda c, r: 100000) == 0.01)
check("котировки нет и курса нет → 0 (и заявка не закроется)",
      pd.expected_amount({"agreed_crypto_amount": None, "rub_amount": 1000,
                          "currency": "BTC"}, None) == 0.0)
check("сбой курса не роняет проход",
      pd.expected_amount({"agreed_crypto_amount": 0, "rub_amount": 1000,
                          "currency": "BTC"},
                         lambda c, r: (_ for _ in ()).throw(RuntimeError())) == 0.0)

# --- доверенные источники ---------------------------------------------------
pd.add_source("BTC", "bc1qMyPersonalWallet", "личный кошелёк владельца")
check("источник добавлен", "bc1qmypersonalwallet" in {a for a in pd._registered_sources().get("BTC", {})})
check("регистр не мешает совпадению",
      pd.judge(ORDER, [tx(sender="BC1QMYPERSONALWALLET")], set(),
               {"bc1qmypersonalwallet"})["action"] == "close")
pd.remove_source("BTC", "bc1qmypersonalwallet")
check("источник удалён", not pd._registered_sources().get("BTC"))

# --- fail-closed: не зная занятых txid, не закрываем ------------------------
_saved = pd._used_txids
pd._used_txids = lambda: (_ for _ in ()).throw(RuntimeError("БД недоступна"))
res = pd.discover()
check("сбой чтения занятых txid → ни одного закрытия", not res["close"])
check("сбой отражён в отчёте", bool(res["errors"]))
pd._used_txids = _saved

# --- проход целиком на поддельной цепочке -----------------------------------
import sqlite3  # noqa: E402

conn = sqlite3.connect(os.environ["DB_PATH"])
conn.execute("""CREATE TABLE orders (order_id INT, user_id INT, rub_amount REAL,
    currency TEXT, network TEXT, crypto_address TEXT, status TEXT,
    paid_btc_tx TEXT, agreed_crypto_amount REAL, created_at TEXT, updated_at TEXT)""")
conn.execute("INSERT INTO orders VALUES (10, 5, 6500, 'BTC', NULL, 'bc1qclient', "
             "'paid', NULL, 0.001, datetime('now','-3 hours'), datetime('now','-3 hours'))")
conn.execute("INSERT INTO orders VALUES (11, 5, 3000, 'BTC', NULL, 'bc1qclient2', "
             "'paid', NULL, 0.002, datetime('now','-5 minutes'), datetime('now','-5 minutes'))")
conn.execute("INSERT INTO orders VALUES (12, 5, 1000, 'BTC', NULL, 'bc1qclient3', "
             "'sent', 'deadbeef', 0.0005, datetime('now','-3 hours'), datetime('now','-3 hours'))")
conn.commit()
conn.close()

pd._own_wallet_addresses = lambda cur: {OUR}


def fake_fetch(currency, address):
    if address == "bc1qclient":
        return [tx(txid="c" * 64, amount=0.001, ts=9999999999)]
    return []


res = pd.discover(rate_fn=lambda c, r: 6500000, fetch=fake_fetch)
check("свежая заявка (5 минут) не трогается — авто-выплата ещё могла сработать",
      res["checked"] == 1)
check("заявка с доказательством закрыта", len(res["close"]) == 1 and res["close"][0]["order_id"] == 10)
check("уже отправленная заявка не проверяется",
      all(v["order_id"] != 12 for v in res["close"] + res["review"]))
check("отчёт непустой", "#10" in pd.format_report(res))
check("нет поводов → пустой отчёт", pd.format_report({"checked": 3}) == "")

r = pd.judge(ORDER, [tx(txid="A" * 64)], {"a" * 64}, TRUSTED)
check("занятый txid узнаётся в другом регистре", r["action"] == "none")

# --- подтверждение по одной заявке (кнопка в боте) --------------------------
v = pd.candidates_for(10, rate_fn=lambda c, r: 6500000, fetch=fake_fetch)
check("кандидат по заявке найден", v.get("candidates") and v["candidates"][0]["txid"] == "c" * 64)
check("вердикт несёт всё нужное для закрытия",
      v.get("user_id") == 5 and v.get("currency") == "BTC" and v.get("rub_amount") == 6500)

v = pd.candidates_for(12, fetch=fake_fetch)
check("уже отправленную заявку закрыть нельзя", "error" in v)
v = pd.candidates_for(999, fetch=fake_fetch)
check("несуществующая заявка → ошибка, не молчание", "error" in v)


# Сеть в контракт fetch добавилась позже, а подменяют его снаружи. Позвать
# двухаргументную функцию с тремя = TypeError, который выше глотается в
# «цепочка недоступна»: сверка молча перестаёт находить что-либо. Поэтому
# двухаргументный источник обязан продолжать работать.
def legacy_fetch(currency, address):
    return fake_fetch(currency, address)


v = pd.candidates_for(10, rate_fn=lambda c, r: 6500000, fetch=legacy_fetch)
check("двухаргументный источник переводов (старый контракт) продолжает работать",
      not v.get("error") and v.get("candidates"))


seen_network = []


def three_arg_fetch(currency, address, network=None):
    seen_network.append(network)
    return fake_fetch(currency, address)


v = pd.candidates_for(10, rate_fn=lambda c, r: 6500000, fetch=three_arg_fetch)
check("трёхаргументный источник получает сеть заявки",
      not v.get("error") and v.get("candidates") and seen_network)


def boom_fetch(currency, address):
    raise RuntimeError("обозреватель недоступен")


v = pd.candidates_for(10, rate_fn=lambda c, r: 6500000, fetch=boom_fetch)
check("сбой обозревателя → ошибка, а не пустой список кандидатов", "error" in v)

# --- перевод рядом с суммой перестал быть невидимым -------------------------
# Живой случай 04.08.2026: владелец выплатил #99955118 руками, перевод лежал на
# адресе клиента ПЕРВЫМ в списке — сверка ответила «подходящих переводов не
# найдено», потому что котировка в заявке не зафиксирована и объём пересчитался
# по курсу восьмью днями позже (0.000642 против 0.00062977, 1.9% при допуске 1%).
near_tx = tx(amount=0.00102, sender=THEIRS)      # +2% мимо допуска
v = pd.judge(ORDER, [near_tx], set(), TRUSTED)
check("перевод мимо допуска НЕ становится кандидатом", not v["candidates"])
check("перевод мимо допуска не закрывает заявку", v["action"] == "none")
check("но он попадает в near", len(v.get("near") or []) == 1)
check("named расхождение считается в процентах",
      abs((v["near"][0]["off_pct"]) - 2.0) < 0.01)
check("причина называет найденную сумму, а не «не найдено»",
      "0.00102" in v["reason"] and "не найдено" not in v["reason"])

v_fixed = pd.judge({**ORDER, "expected_fixed": True}, [near_tx], set(), TRUSTED)
v_float = pd.judge({**ORDER, "expected_fixed": False}, [near_tx], set(), TRUSTED)
check("при зафиксированной котировке про курс не выдумывается",
      "курс" not in v_fixed["reason"])
check("при незафиксированной — причина расхождения названа прямо",
      "не зафиксирована" in v_float["reason"])

far = tx(amount=0.01, sender=THEIRS)             # в десять раз больше
check("далёкий перевод в near не попадает",
      not (pd.judge(ORDER, [far], set(), TRUSTED).get("near") or []))
early = tx(amount=0.00102, ts=10, sender=THEIRS)  # до оплаты заявки
check("перевод ДО оплаты заявки в near не попадает",
      not (pd.judge(ORDER, [early], set(), TRUSTED).get("near") or []))
unripe = tx(amount=0.00102, sender=THEIRS, confirmations=1)
check("незрелый перевод в near не попадает — советовать мемпул нельзя",
      not (pd.judge(ORDER, [unripe], set(), TRUSTED).get("near") or []))
check("наш перевод в допуске по-прежнему закрывает заявку сам",
      pd.judge(ORDER, [tx()], set(), TRUSTED)["action"] == "close")

rep = pd.format_report({"checked": 1, "close": [], "review": [], "errors": [],
                        "near": [{**v_float, "currency": "BTC", "rub_amount": 4447.0}]})
check("отчёт показывает находку рядом", "🔍" in rep and "#1" in rep)
check("в отчёте полный хеш и готовая команда",
      near_tx["txid"] in rep and "/force_payout 1 " in rep)
check("пустой проход по-прежнему молчит",
      pd.format_report({"checked": 3, "close": [], "review": [], "near": [],
                        "errors": []}) == "")

# --- окно молчания гасит повтор новости, а не новую новость -----------------
base_res = {"review": [], "near": [{"order_id": 1,
                                    "near": [{"txid": "b" * 64}]}]}
same_res = {"review": [], "near": [{"order_id": 1,
                                    "near": [{"txid": "B" * 64}]}]}
more_res = {"review": [], "near": [{"order_id": 1,
                                    "near": [{"txid": "b" * 64},
                                             {"txid": "c" * 64}]}]}
check("та же находка — тот же отпечаток, повтор не пробивает окно",
      pd.alert_fingerprint(base_res) == pd.alert_fingerprint(same_res))
check("новый перевод по ТОЙ ЖЕ заявке меняет отпечаток",
      pd.alert_fingerprint(base_res) != pd.alert_fingerprint(more_res))
check("порядок находок на отпечаток не влияет",
      pd.alert_fingerprint({"review": [], "near": [
          {"order_id": 2, "near": [{"txid": "d" * 64}]},
          {"order_id": 1, "near": [{"txid": "b" * 64}]}]})
      == pd.alert_fingerprint({"review": [], "near": [
          {"order_id": 1, "near": [{"txid": "b" * 64}]},
          {"order_id": 2, "near": [{"txid": "d" * 64}]}]}))
check("спорные и близкие находки не путаются между собой",
      pd.alert_fingerprint({"review": [{"order_id": 1,
                                        "candidates": [{"txid": "b" * 64}]}],
                            "near": []})
      != pd.alert_fingerprint(base_res))

check("зафиксированную котировку отличаем от пересчитанной",
      pd.quote_is_fixed({"agreed_crypto_amount": 0.5}) is True
      and pd.quote_is_fixed({"agreed_crypto_amount": None}) is False
      and pd.quote_is_fixed({"agreed_crypto_amount": 0}) is False)

import shutil  # noqa: E402

shutil.rmtree(_TMP, ignore_errors=True)

print(f"payout_discovery: зелёных {ok}, упавших {fail}")
sys.exit(1 if fail else 0)
