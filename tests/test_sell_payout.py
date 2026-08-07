#!/usr/bin/env python3
"""Выплата рублей за проданную крипту: куда, чем и с какими проверками.

Здесь проверяется не «работает ли Vertu» — живого баланса у нас нет, — а то,
без чего перевод денег становится опасным: что номер карты с опечаткой не
проходит, что вторая кнопка не отправляет второй перевод, что отказ рельса не
помечает заявку выплаченной, и что заявка старого образца (реквизит лежит в
`sbp_phone`, способа нет вовсе) читается как СБП, а не как пустота.
"""
import os
import sqlite3
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))

_DB = os.path.join(tempfile.mkdtemp(prefix="sellpayout-"), "t.db")
os.environ["DB_PATH"] = _DB

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


# ── подставной рельс ─────────────────────────────────────────────────────────

class FakeVertu:
    """Считает вызовы и отдаёт заготовленный ответ. Ничего не сети."""

    PAYOUT_BANKS = {"t-bank", "alfa", "sber", "vtb", "gazprom", "psb"}
    calls = []
    next_payout = {"payout_id": "PL-1", "status": "pending", "raw": {}}
    next_status = {"status": "paid", "raw_status": "Approved"}

    @classmethod
    def normalize_bank(cls, code):
        c = str(code or "").strip().lower().replace("_", "-")
        aliases = {"tbank": "t-bank", "тинькофф": "t-bank", "сбер": "sber"}
        c = aliases.get(c, c)
        return c if c in cls.PAYOUT_BANKS else ""

    def create_payout(self, **kw):
        FakeVertu.calls.append(("create", kw))
        return dict(FakeVertu.next_payout)

    def get_payout_status(self, payout_id):
        FakeVertu.calls.append(("status", payout_id))
        return dict(FakeVertu.next_status)


_mod = types.ModuleType("providers.vertu")
_mod.VertuProvider = FakeVertu
sys.modules["providers.vertu"] = _mod

from core import sell_payout as sp  # noqa: E402


def _env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _rail_on():
    _env(VERTU_PAYOUT="1", VERTU_API_KEY="k", VERTU_PAYOUT_SBP=None)


def _rail_off():
    _env(VERTU_PAYOUT=None, VERTU_API_KEY=None, VERTU_LOGIN=None,
         VERTU_PASSWORD=None, VERTU_PAYOUT_SBP=None)


# ── 1. Рельс выключен — карты нет ────────────────────────────────────────────
_rail_off()
check(sp.methods() == ("sbp",),
      "с выключенным рельсом клиенту предложена карта — обещание перевода, "
      "который сделать нечем")
check(sp.route("card") == "manual" and sp.route("sbp") == "manual",
      "выключенный рельс всё равно объявлен маршрутом выплаты")
check(sp.refuse("card", "4111111111111111"),
      "заявка на карту принята при выключенном рельсе")
check(not sp.needs_bank("sbp") and not sp.needs_full_name("sbp"),
      "ручному СБП зачем-то потребовались банк и ФИО — лишние поля на "
      "единственном работающем пути")

# Флага мало: без учётных данных вызов упадёт уже с криптой клиента у нас.
_env(VERTU_PAYOUT="1", VERTU_API_KEY=None, VERTU_LOGIN=None, VERTU_PASSWORD=None)
check(not sp.vertu_payout_enabled(),
      "рельс включён одним флагом, без учётных данных — выплата сорвётся "
      "в момент перевода, когда монеты уже у нас")

# ── 2. Рельс включён ─────────────────────────────────────────────────────────
_rail_on()
check(sp.methods() == ("card", "sbp"),
      "карта не появилась первой при живом рельсе")
check(sp.route("card") == "vertu", "карта не ушла в автоматический рельс")
check(sp.route("sbp") == "manual",
      "СБП молча переехал на рельс — у рабочего пути прибавилось два "
      "обязательных поля без решения владельца")
check(sp.needs_bank("card") and sp.needs_full_name("card"),
      "для карты не требуются банк и ФИО, хотя рельс без них отвечает 422")
_env(VERTU_PAYOUT_SBP="1")
check(sp.route("sbp") == "vertu", "явное включение СБП на рельсе не сработало")
_env(VERTU_PAYOUT_SBP=None)

check(sp.route("почтовый перевод") == "manual",
      "неизвестное направление ушло в рельс — перевод по правилам, "
      "которых мы не знаем")

# ── 3. Номер карты: контрольная сумма, а не длина ────────────────────────────
GOOD = ["4111111111111111", "5536913853247803", "2200000000000004"]
for n in GOOD:
    check(sp.normalize_details("card", n) == n, f"годная карта {n} отклонена")
check(sp.normalize_details("card", "4111 1111-1111 1111") == "4111111111111111",
      "пробелы и дефисы в номере карты не срезаны — клиент вводит так, как "
      "написано на карте")
# Одна изменённая цифра — самая частая опечатка, и она обязана падать.
check(not sp.normalize_details("card", "4111111111111112"),
      "номер с изменённой последней цифрой прошёл — перевод ушёл бы чужому")
check(not sp.normalize_details("card", "4112111111111111"),
      "номер с опечаткой в середине прошёл")
check(not sp.normalize_details("card", "411111111111"),
      "12-значный номер принят за карту")
check(not sp.normalize_details("card", "41111111111111111111"),
      "20-значный номер принят за карту")
check(not sp.normalize_details("card", "4111a11111111111"),
      "буква в номере карты не отсеяна")
check(not sp.normalize_details("card", ""), "пустой номер карты принят")

# ── 4. Телефон ───────────────────────────────────────────────────────────────
check(sp.normalize_details("sbp", "+7 900 123-45-67") == "79001234567",
      "телефон с плюсом и разделителями не приведён к рабочему виду")
check(sp.normalize_details("sbp", "89001234567") == "79001234567",
      "восьмёрка в начале не заменена — клиенты диктуют номер именно так")
check(not sp.normalize_details("sbp", "9001234567"), "номер без кода страны принят")
check(not sp.normalize_details("sbp", "790012345678"), "лишняя цифра в номере принята")
check(not sp.normalize_details("sbp", "19001234567"), "не российский номер принят")
# Номер карты в поле телефона — та же ошибка, только наоборот.
check(not sp.normalize_details("sbp", "4111111111111111"),
      "номер карты принят как телефон СБП")

# ── 5. ФИО ───────────────────────────────────────────────────────────────────
check(sp.normalize_full_name(" Иван   Иванов ") == "Иван Иванов",
      "лишние пробелы в ФИО не свёрнуты")
check(sp.normalize_full_name("Иван Иванович Иванов") == "Иван Иванович Иванов",
      "отчество не принято")
check(not sp.normalize_full_name("Иван"),
      "одно слово принято за ФИО — почти всегда это ник или слово «карта»")
check(not sp.normalize_full_name("Иван Иванов Иванович Петрович Сергеевич"),
      "пять слов приняты за ФИО")
check(not sp.normalize_full_name("Иван 2"), "цифра в ФИО не отсеяна")
check(not sp.normalize_full_name(""), "пустое ФИО принято")

# ── 6. Маска реквизита ───────────────────────────────────────────────────────
check(sp.mask_details("card", "4111111111111111") == "•••• 1111",
      "номер карты показан целиком — он живёт в истории и переписке персонала")
m = sp.mask_details("sbp", "79001234567")
check(m.startswith("79") and m.endswith("4567") and "•" in m,
      f"телефон замаскирован неузнаваемо: {m}")

# Тому, кто платит руками, маска бесполезна: по «79•••••4567» перевод не
# сделать, и заявка встанет молча.
check(sp.staff_details("sbp", "7 900 123-45-67") == "79001234567",
      "оператору на ручном пути показан не тот номер, по которому он платит")
check(sp.staff_details("card", "4111111111111111") == "•••• 1111",
      "полный номер карты уходит в чат персонала там, где по нему платит "
      "рельс, а не человек")

# ── 7. refuse: порядок и полнота ─────────────────────────────────────────────
check(sp.refuse("card", "4111111111111111", "sber", "Иван Иванов") == "",
      "полностью заполненная заявка на карту отвергнута")
check("контрольную сумму" in sp.refuse("card", "4111111111111112", "sber", "Иван Иванов"),
      "об ошибке в номере карты сказано не про контрольную сумму")
check("банк" in sp.refuse("card", "4111111111111111", "", "Иван Иванов").lower(),
      "заявка на карту без банка принята")
check("банк" in sp.refuse("card", "4111111111111111", "монобанк", "Иван Иванов").lower(),
      "банк, которого у рельса нет, принят — отказ вскрылся бы при переводе")
check("ФИО" in sp.refuse("card", "4111111111111111", "sber", ""),
      "заявка на карту без ФИО принята, хотя рельс отвечает на неё 422")
check(sp.refuse("sbp", "79001234567") == "", "годная заявка по СБП отвергнута")

# Банк с синонимом принимается: клиент пишет «тинькофф», рельс ждёт t-bank.
check(sp.refuse("card", "4111111111111111", "tbank", "Иван Иванов") == "",
      "синоним кода банка не распознан")
check(sp.normalize_bank("СБЕР") == "sber", "нормализация банка через общий вход не работает")
check(sp.normalize_bank("") == "" and sp.normalize_bank(None) == "",
      "пустой код банка превратился во что-то непустое")

codes = [c for c, _ in sp.banks()]
check(set(codes) == FakeVertu.PAYOUT_BANKS,
      "список банков разошёлся с тем, что принимает рельс")
check(sp.bank_label("t-bank") == "Т-Банк", "код банка не превращается в название")

# ── 8. Заявки в базе ─────────────────────────────────────────────────────────

def _db():
    conn = sqlite3.connect(_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


with _db() as c:
    c.execute("""CREATE TABLE sell_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, currency TEXT,
        crypto_amount REAL, rub_amount REAL, sbp_phone TEXT, receive_address TEXT,
        status TEXT, created_at TEXT, updated_at TEXT,
        payout_method TEXT, payout_bank TEXT, payout_details TEXT,
        payout_name TEXT, payout_provider TEXT, payout_ref TEXT, payout_status TEXT)""")
    # Заявка старого образца: способа нет вовсе, реквизит в легаси-колонке.
    c.execute("INSERT INTO sell_orders (id, user_id, currency, rub_amount, sbp_phone,"
              " status) VALUES (1, 111, 'BTC', 5000, '79001234567', 'pending')")
    # Новая заявка на карту.
    c.execute("INSERT INTO sell_orders (id, user_id, currency, rub_amount, sbp_phone,"
              " status, payout_method, payout_bank, payout_details, payout_name)"
              " VALUES (2, 222, 'BTC', 7000, '', 'pending', 'card', 'sber',"
              " '4111111111111111', 'Иван Иванов')")
    # Заявка на карту с нулевой выплатой — платить нечего.
    c.execute("INSERT INTO sell_orders (id, user_id, currency, rub_amount, sbp_phone,"
              " status, payout_method, payout_bank, payout_details, payout_name)"
              " VALUES (3, 333, 'BTC', 0, '', 'pending', 'card', 'sber',"
              " '4111111111111111', 'Иван Иванов')")
    # Заявка на карту, чей реквизит испортили в базе руками.
    c.execute("INSERT INTO sell_orders (id, user_id, currency, rub_amount, sbp_phone,"
              " status, payout_method, payout_bank, payout_details, payout_name)"
              " VALUES (4, 444, 'BTC', 5000, '', 'pending', 'card', 'sber',"
              " '4111111111111112', 'Иван Иванов')")
    c.commit()

row1 = _db().execute("SELECT * FROM sell_orders WHERE id=1").fetchone()
t1 = sp.target(row1)
check(t1["method"] == "sbp" and t1["details"] == "79001234567",
      "заявка старого образца прочитана мимо своего реквизита — выплата ушла "
      "бы в пустоту либо потребовала бы человека с базой в руках")
check(t1["route"] == "manual", "старая заявка отправлена в автоматический рельс")

row2 = _db().execute("SELECT * FROM sell_orders WHERE id=2").fetchone()
t2 = sp.target(row2)
check(t2["method"] == "card" and t2["details"] == "4111111111111111"
      and t2["bank"] == "sber" and t2["route"] == "vertu",
      "заявка на карту прочитана неверно")
check(t2["shown"] == "•••• 1111", "карточка заявки показывает полный номер")

# ── 9. Отправка рублей ───────────────────────────────────────────────────────
FakeVertu.calls = []
res = sp.send_rub(1)
check(res.get("ok") and res.get("manual"),
      "ручная заявка не опознана как ручная")
check(not FakeVertu.calls, "по ручной заявке всё равно дёрнули рельс")

res = sp.send_rub(3)
check(not res.get("ok") and "нулев" in res.get("error", "").lower(),
      "выплата на ноль рублей не отклонена")

res = sp.send_rub(4)
check(not res.get("ok") and "не годится" in res.get("error", ""),
      "испорченный в базе реквизит не перепроверен перед переводом — "
      "между приёмом заявки и выплатой проходят часы")

FakeVertu.calls = []
res = sp.send_rub(2, callback_url="https://example.org/cb")
check(res.get("ok") and res.get("ref") == "PL-1", f"выплата не создана: {res}")
kinds = [k for k, _ in FakeVertu.calls]
check(kinds == ["create"], f"вызовы рельса не те: {kinds}")
kw = FakeVertu.calls[0][1]
check(kw["amount"] == 7000.0, "в рельс ушла не сумма заявки")
check(kw["bank"] == "sber" and kw["full_name"] == "Иван Иванов",
      "банк или ФИО не доехали до рельса")
check(kw["bank_details"] == "4111111111111111",
      "в рельс ушёл ненормализованный реквизит")
check(kw["callback_url"] == "https://example.org/cb", "адрес обратного вызова потерян")
check(str(kw["order_id"]).endswith("2") or "2" in str(kw["order_id"]),
      "выплата не привязана к номеру заявки")

saved = _db().execute("SELECT payout_provider, payout_ref, payout_status"
                      " FROM sell_orders WHERE id=2").fetchone()
check(tuple(saved) == ("vertu", "PL-1", "pending"),
      f"ссылка на выплату не записана в заявку: {tuple(saved)}")

# Повторное нажатие обязано вернуть ту же выплату, а не создать вторую:
# у рельса нет идемпотентности по нашему идентификатору.
FakeVertu.calls = []
res2 = sp.send_rub(2)
check(res2.get("ok") and res2.get("duplicate") and res2.get("ref") == "PL-1",
      f"повтор не распознан: {res2}")
check(not FakeVertu.calls,
      "вторая кнопка отправила ВТОРОЙ перевод — клиент получил бы деньги дважды")

# Отклонённую рельсом выплату повторять можно и нужно: деньги не ушли.
with _db() as c:
    c.execute("UPDATE sell_orders SET payout_status='declined' WHERE id=2")
    c.commit()
check(sp.already_sent(2) == {},
      "отклонённая выплата считается отправленной — заявка зависла бы навсегда")
FakeVertu.calls = []
FakeVertu.next_payout = {"payout_id": "PL-2", "status": "pending"}
res3 = sp.send_rub(2)
check(res3.get("ok") and res3.get("ref") == "PL-2", "повтор после отказа не прошёл")

# Отказ рельса не должен оставлять следов «выплата создана».
FakeVertu.next_payout = {"error": "Недостаточно средств"}
with _db() as c:
    c.execute("UPDATE sell_orders SET payout_ref='', payout_status='' WHERE id=2")
    c.commit()
res4 = sp.send_rub(2)
check(not res4.get("ok") and "средств" in res4.get("error", ""),
      f"отказ рельса не передан наверх: {res4}")
ref_after = _db().execute("SELECT payout_ref FROM sell_orders WHERE id=2").fetchone()[0]
check(not ref_after,
      "после отказа рельса в заявке осталась ссылка на выплату — заявка "
      "выглядела бы оплаченной, хотя денег клиент не получил")
# Успех без номера выплаты — не успех: перевод мог уйти, а сослаться на него
# нечем. Ни закрыть заявку, ни отпустить её обратно в очередь нельзя.
FakeVertu.next_payout = {"status": "pending", "raw": {}}
with _db() as c:
    c.execute("UPDATE sell_orders SET payout_ref='', payout_status='' WHERE id=2")
    c.commit()
res5 = sp.send_rub(2)
check(not res5.get("ok") and res5.get("needs_human"),
      f"ответ рельса без номера выплаты принят за успех — заявка закрылась бы "
      f"по переводу, которого мы не видим: {res5}")
check(_db().execute("SELECT payout_status FROM sell_orders WHERE id=2").fetchone()[0]
      == "unknown", "невнятный исход не отмечен в заявке")
FakeVertu.calls = []
res6 = sp.send_rub(2)
check(not res6.get("ok") and res6.get("needs_human"),
      "повтор после невнятного исхода разрешён")
check(not FakeVertu.calls,
      "после ответа без номера выплаты вторая кнопка отправила ВТОРОЙ перевод "
      "вслепую — по деньгам, которые могли уже уйти")

FakeVertu.next_payout = {"payout_id": "PL-1", "status": "pending", "raw": {}}

# ── 10. Исход выплаты закрывает заявку ровно один раз ────────────────────────
check(sp.is_settled("paid") and not sp.is_settled("pending")
      and not sp.is_settled("awaiting_payment"),
      "созданная, но не зачисленная выплата считается состоявшейся — заявка "
      "закроется до денег, а отклонённая позже останется paid навсегда")
for bad in ("failed", "declined", "revoked"):
    check(sp.is_rejected(bad), f"исход {bad} не признан отказом")
check(not sp.is_rejected("pending") and not sp.is_rejected("paid"),
      "живая или успешная выплата принята за отказ")

with _db() as c:
    c.execute("UPDATE sell_orders SET status='paying' WHERE id=2")
    c.commit()
check(sp.mark_settled(2), "подтверждённая выплата не закрыла заявку")
check(_db().execute("SELECT status FROM sell_orders WHERE id=2").fetchone()[0] == "paid",
      "заявка не перешла в paid")
check(not sp.mark_settled(2),
      "второе закрытие вернуло «закрыл я» — объём начислился бы дважды, "
      "а клиент получил бы два письма «выполнено»")

# Выплаченная заявка терминальна. Обход и обратный вызов спрашивают статус
# независимо, и устаревшее «отклонено» после свежего «зачислено» вернуло бы
# закрытый долг в очередь — то есть разрешило бы заплатить второй раз.
check(not sp.mark_rejected(2),
      "устаревший отказ снова открыл ВЫПЛАЧЕННУЮ заявку — по закрытому долгу "
      "можно было бы заплатить второй раз")
check(_db().execute("SELECT status FROM sell_orders WHERE id=2").fetchone()[0] == "paid",
      "выплаченная заявка перестала быть терминальной")

with _db() as c:
    c.execute("UPDATE sell_orders SET status='paying' WHERE id=2")
    c.commit()
check(sp.mark_rejected(2),
      "отклонённая выплата не вернула заявку в очередь")
check(_db().execute("SELECT status FROM sell_orders WHERE id=2").fetchone()[0]
      == "pending",
      "после отказа заявка не вернулась в ожидание — монеты клиента у нас, "
      "а долг не видит ни один список")
check(not sp.mark_rejected(2),
      "повторный отказ снова «вернул» заявку, которая и так ждёт")

# ── 11. Заявка, брошенная на полпути ─────────────────────────────────────────
# Процесс умер между «занять строку» и «записать номер выплаты»: кнопка её
# больше не займёт, обход статусов не увидит, а долг перед клиентом настоящий.
with _db() as c:
    c.execute("UPDATE sell_orders SET status='paying', payout_ref='',"
              " updated_at=datetime('now','-40 minutes') WHERE id=4")
    c.execute("UPDATE sell_orders SET status='paying', payout_ref='PL-LIVE',"
              " updated_at=datetime('now','-40 minutes') WHERE id=3")
    c.execute("UPDATE sell_orders SET status='paying', payout_ref='',"
              " updated_at=datetime('now') WHERE id=1")
    c.commit()
stuck = {r["id"] for r in sp.stale_claims(15)}
check(4 in stuck, "заявка, брошенная без номера выплаты, не найдена — она "
                  "невидима и для кнопки, и для обхода статусов")
check(3 not in stuck,
      "заявка с номером выплаты объявлена застрявшей — её доведёт обход "
      "статусов, а человека звать не за чем")
check(1 not in stuck,
      "только что занятая заявка объявлена застрявшей — тревога полетит по "
      "каждой нормальной выплате")

check(not sp.release_claim(3),
      "заявка с номером выплаты возвращена в очередь — второй перевод по "
      "деньгам, которые уже ушли")
check(sp.release_claim(4), "застрявшая заявка не вернулась в очередь")
check(_db().execute("SELECT status FROM sell_orders WHERE id=4").fetchone()[0]
      == "pending", "после возврата заявка не ждёт выплаты")
check(not sp.release_claim(4), "повторный возврат сработал на уже свободной заявке")


# ── 12. Опрос статуса ────────────────────────────────────────────────────────
with _db() as c:
    c.execute("UPDATE sell_orders SET payout_ref='PL-9', payout_status='pending'"
              " WHERE id=2")
    c.commit()
st = sp.refresh_status(2)
check(st.get("status") == "paid", f"статус выплаты не прочитан: {st}")
check(_db().execute("SELECT payout_status FROM sell_orders WHERE id=2").fetchone()[0]
      == "paid", "свежий статус не сохранён в заявку")
check(sp.refresh_status(1).get("status") == "none",
      "у заявки без выплаты статус выдуман")
check(sp.refresh_status(99999).get("status") == "unknown",
      "несуществующая заявка получила осмысленный статус выплаты")
FakeVertu.next_status = {"status": "unknown"}
with _db() as c:
    c.execute("UPDATE sell_orders SET payout_status='pending' WHERE id=2")
    c.commit()
sp.refresh_status(2)
check(_db().execute("SELECT payout_status FROM sell_orders WHERE id=2").fetchone()[0]
      == "pending",
      "невнятный ответ рельса затёр известный статус выплаты")

_rail_off()

if FAILS:
    print(f"❌ Выплата за продажу: {len(FAILS)} провал(ов)")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("✅ Выплата за продажу: контрольная сумма карты, обязательные поля, "
      "защита от второго перевода и разбор старых заявок в порядке")
