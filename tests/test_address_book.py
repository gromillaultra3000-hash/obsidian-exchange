"""Адресная книга клиента: подсказка, которой можно доверить деньги.

Сеть не трогаем — всё считается по локальной базе.
"""
import os
import sqlite3
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="addrbook_test_")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
# Путь к relay — ОТ СЕБЯ, а не боевой абсолютный: иначе набор проверяет прод.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))

from core import address_book as ab  # noqa: E402

ok = fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print(f"  ✗ {name}")


# Адреса настоящей формы: книга фильтрует по сегодняшней проверке, и выдуманная
# строка до подсказок не дойдёт — как и должно быть.
BTC1 = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
BTC2 = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
LTC1 = "ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kgmn4n9"
TRON1 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
BROKEN = "bc1qDefinitelyNotAnAddress"

conn = sqlite3.connect(os.environ["DB_PATH"])
conn.execute("""CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT,
    currency TEXT, network TEXT, rub_amount REAL, crypto_address TEXT,
    status TEXT, created_at TEXT)""")
conn.execute("""CREATE TABLE wallet_links (
    user_id INTEGER, chain TEXT, address TEXT, verified_at TEXT,
    PRIMARY KEY(user_id,chain))""")
conn.execute("""CREATE TABLE client_address_notes (
    user_id INTEGER, currency TEXT, network TEXT, address TEXT, label TEXT,
    hidden INTEGER, updated_at TEXT,
    PRIMARY KEY(user_id,currency,network,address))""")


def order(uid, cur, addr, when, net=None, status="sent"):
    conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
                 " crypto_address, status, created_at) VALUES (?,?,?,?,?,?,?)",
                 (uid, cur, net, 5000, addr, status, when))
    conn.commit()


ME, OTHER = 111, 222
order(ME, "BTC", BTC1, "2026-08-01 10:00:00", "MAINNET")
order(ME, "BTC", BTC1, "2026-08-03 10:00:00", "MAINNET")   # тот же адрес дважды
order(ME, "BTC", BTC2, "2026-07-20 10:00:00", "MAINNET")
order(ME, "LTC", LTC1, "2026-08-02 10:00:00", "MAINNET")
order(ME, "BTC", BROKEN, "2026-08-04 10:00:00", "MAINNET")
order(OTHER, "BTC", TRON1.replace("T", "1"), "2026-08-04 11:00:00", "MAINNET")
order(OTHER, "BTC", BTC2, "2026-08-04 11:00:00", "MAINNET")

# Заявки, по которым монеты НЕ уходили: адрес из них подсказкой быть не должен.
CANCELLED = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"
order(ME, "BTC", CANCELLED, "2026-08-04 12:00:00", "MAINNET", status="cancelled")
PENDING_ADDR = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
order(ME, "BTC", PENDING_ADDR, "2026-08-04 13:00:00", "MAINNET", status="pending")

# --- чужого в книге нет ------------------------------------------------------
# Главное правило: книгу строит СЕРВЕР по данным клиента. Утечка сюда — это
# чужой адрес, подставленный в заявку как «ваш сохранённый».
mine = ab.entries_for(ME)
addrs = [e["address"] for e in mine]
check("свои адреса в книге", BTC1 in addrs and BTC2 in addrs and LTC1 in addrs)
check("чужих заявок в книге нет", all(e["address"] != TRON1 for e in mine))
check("книга другого клиента своя", ab.entries_for(OTHER) and
      all(a["address"] != LTC1 for a in ab.entries_for(OTHER)))
check("несуществующий клиент — пустой список, а не всё подряд",
      ab.entries_for(999999) == [])
check("нечисловой user_id не роняет и ничего не отдаёт",
      ab.entries_for("' OR 1=1 --") == [])

# --- негодный адрес не предлагается -----------------------------------------
# Проверки формы со временем строжают. Адрес, принятый год назад, сегодня может
# их не проходить — подсказать такой одним тапом значит отправить деньги в никуда.
check("адрес, не проходящий сегодняшнюю проверку, скрыт",
      all(e["address"] != BROKEN for e in mine))

# --- порядок и дубли ---------------------------------------------------------
check("один адрес — одна строка", [e["address"] for e in mine].count(BTC1) == 1)
check("свежий адрес выше старого",
      addrs.index(BTC1) < addrs.index(BTC2))
check("повторное использование посчитано",
      next(e for e in mine if e["address"] == BTC1)["uses"] == 2)

# --- сужение под заявку ------------------------------------------------------
# Предложить BTC-адрес там, где просят LTC, — приглашение к необратимой ошибке.
btc_only = ab.entries_for(ME, "BTC")
check("фильтр по валюте отсекает чужую монету",
      btc_only and all(e["currency"] == "BTC" for e in btc_only))
check("LTC-адрес виден в своей валюте",
      any(e["address"] == LTC1 for e in ab.entries_for(ME, "LTC")))
check("валюта без адресов — пустой список", ab.entries_for(ME, "XRP") == [])

# --- заметки клиента ---------------------------------------------------------
check("имя сохранилось", ab.set_label(ME, "BTC", BTC1, "мой Ledger", "MAINNET"))
check("имя видно в книге",
      next(e for e in ab.entries_for(ME, "BTC") if e["address"] == BTC1)["label"] == "мой Ledger")
check("скрытый адрес исчезает из подсказок",
      ab.hide(ME, "BTC", BTC2, "MAINNET")
      and all(e["address"] != BTC2 for e in ab.entries_for(ME, "BTC")))
check("скрытие у одного клиента не влияет на другого",
      any(e["address"] == BTC2 for e in ab.entries_for(OTHER, "BTC")))
check("возврат из скрытых работает",
      ab.unhide(ME, "BTC", BTC2, "MAINNET")
      and any(e["address"] == BTC2 for e in ab.entries_for(ME, "BTC")))
check("имя переживает скрытие и возврат",
      next(e for e in ab.entries_for(ME, "BTC") if e["address"] == BTC1)["label"] == "мой Ledger")

# --- владение: данным из кнопки не доверяем ---------------------------------
# Колбэк подделывается. Без этой проверки чужой адрес подставился бы в заявку
# под видом «вы уже им пользовались».
check("свой адрес признан своим", ab.owns(ME, "BTC", BTC1))
check("чужой адрес своим не признан", not ab.owns(ME, "BTC", TRON1))
check("свой адрес чужой валютой не признан", not ab.owns(ME, "LTC", BTC1))
check("пустой адрес не проходит", not ab.owns(ME, "BTC", ""))
check("скрытый адрес перестаёт быть «своим» для подстановки",
      ab.hide(ME, "BTC", BTC2, "MAINNET") and not ab.owns(ME, "BTC", BTC2))
# ...но для правки заметки он свой: иначе вернуть его из скрытых было бы нечем.
check("скрытый адрес всё ещё свой, когда правим заметку",
      ab.owns(ME, "BTC", BTC2, include_hidden=True))
check("чужой адрес не становится своим и со скрытыми",
      not ab.owns(ME, "BTC", TRON1, include_hidden=True))
ab.unhide(ME, "BTC", BTC2, "MAINNET")


# --- только то, что действительно дошло --------------------------------------
# Отменённая заявка часто отменена ИМЕННО из-за неверного адреса. Предложить
# такой адрес в один тап — сделать за клиента ту ошибку, от которой он ушёл.
check("адрес отменённой заявки не предлагается",
      all(e["address"] != CANCELLED for e in ab.entries_for(ME, "BTC")))
check("адрес неоплаченной заявки не предлагается",
      all(e["address"] != PENDING_ADDR for e in ab.entries_for(ME, "BTC")))
check("адрес отменённой заявки не считается своим для подстановки",
      not ab.owns(ME, "BTC", CANCELLED))

# --- сеть отсекается наравне с монетой ---------------------------------------
# У USDT адреса TRC20 и ERC20 разные, и подстановка не той сети теряет перевод.
order(ME, "USDT", TRON1, "2026-08-03 09:00:00", "TRC20")
order(ME, "USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7",
      "2026-08-03 09:30:00", "ERC20")
trc = [e["address"] for e in ab.entries_for(ME, "USDT", "TRC20")]
erc = [e["address"] for e in ab.entries_for(ME, "USDT", "ERC20")]
check("TRC20 показывает свой адрес", TRON1 in trc)
check("TRC20 не показывает адрес ERC20", all(not a.startswith("0x") for a in trc))
check("ERC20 показывает свой адрес", any(a.startswith("0x") for a in erc))
check("ERC20 не показывает адрес TRC20", TRON1 not in erc)

# --- показ адреса ------------------------------------------------------------
# Хвост оставляем видимым: подменённый адрес отличается именно им.
s = ab.short(BTC1)
check("короткая форма сохраняет начало и КОНЕЦ",
      s.startswith(BTC1[:8]) and s.endswith(BTC1[-6:]))
check("короткий адрес не режется", ab.short("bc1qshort") == "bc1qshort")

# --- сбой проверки адресов = пустая книга, а не «всё годится» ---------------
_saved = ab._valid
ab._valid = lambda *a, **k: False
check("нечем проверить адрес — не предлагаем ничего", ab.entries_for(ME) == [])
ab._valid = _saved


# --- приходы: что МЫ отправили на адреса клиента -----------------------------
# Витрина кошелька без этого — список строк, по которым ничего не происходило.
conn.execute("ALTER TABLE orders ADD COLUMN agreed_crypto_amount REAL")
conn.execute("ALTER TABLE orders ADD COLUMN paid_btc_tx TEXT")
conn.execute("ALTER TABLE orders ADD COLUMN updated_at TEXT")
conn.commit()
TX = "c" * 64
conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
             " crypto_address, status, created_at, agreed_crypto_amount,"
             " paid_btc_tx, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (ME, "BTC", "MAINNET", 5000, BTC1, "sent", "2026-08-05 10:00:00",
              0.00096, TX, "2026-08-05 10:05:00"))
# Выплата «обещана», но хеша нет — это не приход, а обещание.
cur_ins = conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
             " crypto_address, status, created_at, agreed_crypto_amount,"
             " paid_btc_tx, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (ME, "BTC", "MAINNET", 5000, BTC1, "sent", "2026-08-05 11:00:00",
              0.001, "", "2026-08-05 11:05:00"))
NO_TX_ORDER = cur_ins.lastrowid
# Ручная выдача: в колонке пометка, а не хеш. Спрятать строку нельзя (выдача
# была), выдать за транзакцию — тоже (клиент пойдёт искать её в обозревателе).
cur_ins = conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
             " crypto_address, status, created_at, agreed_crypto_amount,"
             " paid_btc_tx, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (ME, "BTC", "MAINNET", 5000, BTC1, "sent", "2026-08-05 09:00:00",
              0.0005, "manual payout by admin", "2026-08-05 09:05:00"))
MANUAL_ORDER = cur_ins.lastrowid
# Чужая выплата: в кошельке клиента ей не место.
conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
             " crypto_address, status, created_at, agreed_crypto_amount,"
             " paid_btc_tx, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (OTHER, "BTC", "MAINNET", 5000, BTC2, "sent", "2026-08-05 12:00:00",
              0.002, "d" * 64, "2026-08-05 12:05:00"))
conn.commit()

d = ab.deliveries_for(ME)
check("приход с хешем виден", any(x["txid"] == TX for x in d))
# Ручная отправка в боте помечает заявку sent, не заполняя хеш. Спрятать такую
# выдачу — значит умолчать о собственном платеже; показываем как ручную.
_no_tx = next((x for x in d if x["order_id"] == NO_TX_ORDER), None)
check("выдача без хеша видна клиенту", _no_tx is not None)
check("выдача без хеша помечена ручной и без ссылки",
      _no_tx and _no_tx["evidence"] == "manual" and not _no_tx["tx_url"]
      and _no_tx["txid"] == "")
check("чужой приход в кошелёк не попал", all(x["txid"] != "d" * 64 for x in d))
check("у прихода есть ссылка на обозреватель",
      next(x for x in d if x["txid"] == TX)["tx_url"].startswith("http"))
check("сумма прихода — из зафиксированной котировки",
      next(x for x in d if x["txid"] == TX)["amount"] == 0.00096)
manual = next((x for x in d if x["order_id"] == MANUAL_ORDER), None)
check("ручная выдача видна клиенту", manual is not None)
check("ручная выдача не выдаётся за транзакцию",
      manual and manual["txid"] == "" and manual["tx_url"] == ""
      and manual["evidence"] == "manual")
check("настоящий хеш помечен как цепочка",
      next(x for x in d if x["txid"] == TX)["evidence"] == "chain")
check("чужой user_id не отдаёт приходы", ab.deliveries_for(999999) == [])
check("нечисловой user_id не роняет приходы", ab.deliveries_for("x") == [])


# --- заметка ложится под ТУ ЖЕ сеть, что и запись ----------------------------
# У старых заявок колонки network не было. Если заметку положить под сеть,
# выбранную на экране, ключ разойдётся с записью: команда ответит «сохранено»,
# а в списке ничего не изменится. Нашёл codex.
LEGACY = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"
conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
             " crypto_address, status, created_at) VALUES (?,?,?,?,?,?,?)",
             (ME, "BTC", None, 5000, LEGACY, "sent", "2026-08-02 08:00:00"))
conn.commit()
check("заявка без сети попадает в книгу",
      any(e["address"] == LEGACY for e in ab.entries_for(ME, "BTC")))
check("имя для записи без сети сохраняется",
      ab.set_label(ME, "BTC", LEGACY, "старый кошелёк", "MAINNET"))
check("имя ВИДНО в книге, а не потерялось под другой сетью",
      next(e for e in ab.entries_for(ME, "BTC") if e["address"] == LEGACY)["label"]
      == "старый кошелёк")
check("скрытие записи без сети действительно скрывает",
      ab.hide(ME, "BTC", LEGACY, "MAINNET")
      and all(e["address"] != LEGACY for e in ab.entries_for(ME, "BTC")))
ab.unhide(ME, "BTC", LEGACY, "MAINNET")
check("возврат записи без сети работает",
      any(e["address"] == LEGACY for e in ab.entries_for(ME, "BTC")))


# --- витрина сайта: ограничение на каждую монету, а не на весь список --------
# Страница фильтрует чипы на клиенте. С общим лимитом свежие заявки по другим
# монетам вытесняли бы единственный адрес нужной — и он бы просто исчез.
for _i in range(12):
    conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
                 " crypto_address, status, created_at) VALUES (?,?,?,?,?,?,?)",
                 (ME, "BTC", "MAINNET", 5000, BTC1 if _i % 2 else BTC2, "sent",
                  f"2026-08-06 {10 + _i:02d}:00:00"))
conn.commit()
by_cur = ab.entries_by_currency(ME)
check("LTC-адрес не вытеснен свежими BTC-заявками",
      any(e["address"] == LTC1 for e in by_cur))
check("на каждую монету не больше лимита",
      all(sum(1 for e in by_cur if e["currency"] == c) <= ab.MAX_ENTRIES
          for c in {e["currency"] for e in by_cur}))


# Легаси-статус `completed` — те же успешные заявки (так их считают бот и
# payment_service). Иначе у давнего клиента книга пуста.
LEGACY_DONE = "ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kgmn4n9"
conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
             " crypto_address, status, created_at, agreed_crypto_amount,"
             " paid_btc_tx, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
             (OTHER, "LTC", "MAINNET", 5000, LEGACY_DONE, "completed",
              "2026-07-01 10:00:00", 0.4, "e" * 64, "2026-07-01 10:05:00"))
conn.commit()
check("адрес заявки со статусом completed попадает в книгу",
      any(e["address"] == LEGACY_DONE for e in ab.entries_for(OTHER, "LTC")))
check("приход по заявке completed виден",
      any(x["txid"] == "e" * 64 for x in ab.deliveries_for(OTHER)))


# ── один адрес под двумя ключами ─────────────────────────────────────────────
# У старых заявок колонки `network` не было, у подтверждённой подписью связи
# сеть каноническая. Один и тот же адрес приходил в книгу дважды, и — хуже —
# пометка «скрыть» ложилась только на одну из записей: клиент убирал адрес, а
# безсетевой близнец продолжал предлагаться в один тап. Нашёл codex.
TWIN = 333
conn.execute("""CREATE TABLE IF NOT EXISTS wallet_links (
    user_id INTEGER, chain TEXT, address TEXT, verified_at TEXT)""")
conn.execute("INSERT INTO orders (user_id, currency, network, rub_amount,"
             " crypto_address, status, created_at) VALUES (?,?,?,?,?,?,?)",
             (TWIN, "BTC", None, 5000, BTC1, "sent", "2026-07-10 10:00:00"))
conn.execute("INSERT INTO wallet_links (user_id, chain, address, verified_at)"
             " VALUES (?,?,?,?)", (TWIN, "BTC", BTC1, "2026-08-01 10:00:00"))
conn.commit()

twin = ab.entries_for(TWIN, "BTC")
check("адрес показан один раз, а не в двух видах",
      [e["address"] for e in twin].count(BTC1) == 1)
check("показан именно подтверждённый вид записи",
      any(e["address"] == BTC1 and e["verified"] for e in twin))
check("у показанной записи названа сеть",
      all(e["network"] for e in twin if e["address"] == BTC1))

check("скрытие принято", ab.hide(TWIN, "BTC", BTC1))
after = ab.entries_for(TWIN, "BTC")
check("скрытый адрес не возвращается ни в каком виде",
      not any(e["address"] == BTC1 for e in after))
check("и не предлагается как «свой» для подстановки",
      not ab.owns(TWIN, "BTC", BTC1))
check("а с явной просьбой показать скрытое — виден один раз",
      [e["address"] for e in ab.entries_for(TWIN, "BTC", include_hidden=True)
       ].count(BTC1) == 1)

# Пометка, записанная под ПУСТОЙ сетью (так её сохранили бы до канонизации),
# обязана исполняться и после того, как запись получила каноническую сеть.
conn.execute("DELETE FROM client_address_notes WHERE user_id=?", (TWIN,))
conn.execute("INSERT INTO client_address_notes (user_id, currency, network,"
             " address, label, hidden, updated_at) VALUES (?,?,?,?,?,?,?)",
             (TWIN, "BTC", "", BTC1, "", 1, "2026-08-05 10:00:00"))
conn.commit()
check("старая пометка «скрыть» без сети всё ещё исполняется",
      not any(e["address"] == BTC1 for e in ab.entries_for(TWIN, "BTC")))

print(f"address_book: зелёных {ok}, упавших {fail}")
sys.exit(1 if fail else 0)
