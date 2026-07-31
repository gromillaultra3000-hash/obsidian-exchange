#!/usr/bin/env python3
"""TON: адрес, memo и чтение цепи. Без сети — ответы подаются как данные.

Новая монета опасна тем, что её путь длинный: реестр → валидация адреса →
котировка → выплата → сверка → обозреватель. Пропуск любого звена выглядит как
работающая кнопка, за которой ничего нет.

Запуск: python3 tests/test_ton.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import address as A, assets as AS, payout_discovery as pd, txid as T  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


# Настоящий счёт TON Foundation в трёх формах — одна и та же цель.
BOUNCE = "EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N"
NONBOUNCE = "UQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqEBI"
RAW = "0:83dfd552e63729b472fcbcc8c45ebcc6691702558b68ec7527e1ba403a0f31a8"


def main():
    # ── адрес: контрольная сумма, а не только форма ───────────────────
    for a, label in ((BOUNCE, "bounceable"), (NONBOUNCE, "non-bounceable"),
                     (RAW, "сырая форма"),
                     ("-1:" + RAW.split(":")[1], "masterchain")):
        check(A.is_valid_ton(a), f"валидный адрес TON ({label}) отвергнут")
    # Опечатка сохраняет длину и алфавит — ловится только контрольной суммой.
    check(not A.is_valid_ton(BOUNCE[:-1] + "M"),
          "опечатка в последнем символе принята — монеты ушли бы в пустоту")
    check(not A.is_valid_ton(BOUNCE[:-4] + "AAAA"), "испорченный хвост принят")
    for bad, label in (("", "пусто"), (None, "None"), (12345, "не строка"),
                       ("bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "адрес BTC"),
                       ("5:" + RAW.split(":")[1], "несуществующий workchain"),
                       (BOUNCE[:40], "обрезанный")):
        check(not A.is_valid_ton(bad), f"мусор принят как адрес TON: {label}")

    _, h1 = A.parse_ton_address(BOUNCE)
    _, h2 = A.parse_ton_address(RAW)
    check(h1 == h2, "дружественная и сырая формы одного счёта дали разные хеши")

    # ── memo: не число, но роль та же, что у тега XRP ────────────────
    check(A.is_valid_ton_memo("order-42"), "обычный memo отвергнут")
    check(A.is_valid_ton_memo(""), "пустой memo должен быть допустим (личный кошелёк)")
    check(not A.is_valid_ton_memo("x" * 128),
          "memo длиннее одной ячейки принят — биржа его не разберёт")
    check(not A.is_valid_ton_memo("a\nb"), "перевод строки в memo принят")
    check(not A.is_valid_ton_memo(42), "нестроковый memo принят")

    # ── реестр знает монету целиком ──────────────────────────────────
    check("TON" in AS.CURRENCY_NETWORKS, "TON нет в реестре валют")
    check(AS.tag_name("TON"), "у TON не объявлен memo — поверхности не спросят его")
    check(AS.network_label("TON"), "у сети TON нет человекочитаемой метки")
    check(AS.validate_address("TON", BOUNCE), "реестр не принимает валидный адрес TON")
    check(not AS.validate_address("TON", BOUNCE, "ERC20"),
          "адрес TON принят в чужой сети")
    check(not AS.validate_address("BTC", BOUNCE), "адрес TON принят как BTC")

    # ── хеш приводится к общему для проекта виду ─────────────────────
    import base64
    raw = bytes(range(32))
    hx = pd._ton_hash_hex(base64.b64encode(raw).decode())
    check(hx == raw.hex(), f"base64-хеш toncenter не приведён к hex64: {hx}")
    check(T.is_txid(hx), "приведённый хеш не признан идентификатором транзакции")
    check(T.explorer_url("TON", hx), "по выплате TON клиенту нечего показать")
    check(pd._ton_hash_hex("не хеш") == "", "мусор принят за хеш транзакции")

    # ── чтение цепи: memo отсекает чужой перевод ─────────────────────
    b64 = base64.b64encode(raw).decode()
    other = base64.b64encode(bytes(32)).decode()
    seen = {}
    real_get = pd._get_json
    pd._get_json = lambda u, params=None, **k: (seen.update(params or {}) or {"result": [
        {"utime": 1780000000, "transaction_id": {"hash": b64},
         "in_msg": {"value": "25000000000", "source": "EQOur", "message": "order-42"}},
        {"utime": 1780000100, "transaction_id": {"hash": other},
         "in_msg": {"value": "25000000000", "source": "EQOur", "message": "чужой"}},
        {"utime": 1780000200, "transaction_id": {"hash": other},
         "in_msg": {"value": "0", "source": "EQOur", "message": "order-42"}},
    ]})
    try:
        got = pd.incoming_transfers("TON", "EQClient#order-42")
    finally:
        pd._get_json = real_get
    check(len(got) == 1,
          f"с memo взято {len(got)} переводов — адрес биржи один на всех "
          f"клиентов, и без сверки memo закрылась бы чужая заявка")
    check(got and abs(got[0]["amount"] - 25.0) < 1e-9,
          f"нанотоны не переведены в TON ({got[0]['amount'] if got else '—'})")
    check(got and got[0].get("confirmed"),
          "перевод без отметки confirmed — judge отбросит его молча")
    check(seen.get("address") == "EQClient",
          f"в цепь ушёл адрес вместе с memo: {seen.get('address')}")

    # сбой сети — пустой список, а не исключение наружу
    pd._get_json = lambda *a, **k: (_ for _ in ()).throw(OSError("нет сети"))
    try:
        check(pd.incoming_transfers("TON", "EQClient") == [],
              "сбой toncenter не даёт пустой список")
    finally:
        pd._get_json = real_get

    # ── адрес и memo проходят ОБЩИЙ вход, а не разборщик чужой монеты ──────
    # Пока валюта с тегом была одна, `canonical_address` и панель выдачи вели
    # любую такую валюту в XRP-разбор. С появлением TON это стало значить:
    # заявку не создать, а работнику вместо реквизитов показать «адрес не
    # разобран». Проверяем поведением, а не наличием функции.
    check(AS.canonical_address("TON", BOUNCE, None) == BOUNCE,
          "TON без memo не проходит канонизацию — заявку не создать")
    check(AS.canonical_address("TON", BOUNCE, "order 42") == f"{BOUNCE}#order 42",
          "текстовый memo TON теряется при канонизации")
    check(AS.canonical_address("TON", BOUNCE, 12345) is None,
          "числовой memo принят как текстовый — у TON memo это строка")
    check(AS.canonical_address("TON", f"{BOUNCE}#one", "two") is None,
          "конфликт двух memo решён молча — деньги уйдут не туда, "
          "куда просил клиент")
    check(AS.canonical_address("TON", "не адрес", None) is None,
          "мусор вместо адреса TON принят")
    check(AS.validate_tag("TON", "order 42") is True,
          "текстовый memo TON отвергнут числовым валидатором XRP")
    check(AS.validate_tag("XRP", "order 42") is False,
          "XRP принял текстовый тег — destination tag это число")
    check(AS.validate_tag("TON", "x" * 200) is False,
          "memo длиннее ячейки TON принят — перевод не соберётся")

    # обратный разбор: то, что сохранили, обязано разобраться в те же части
    for memo in (None, "order 42", "0"):
        stored = AS.canonical_address("TON", BOUNCE, memo)
        got_addr, got_memo = A.parse_destination(stored, "TON")
        check(got_addr == BOUNCE and got_memo == memo,
              f"склейка TON не разбирается обратно при memo={memo!r}: "
              f"{got_addr!r}/{got_memo!r} — работник увидит не те реквизиты")

    # диспетчер не путает монеты между собой
    check(A.parse_destination(BOUNCE, "XRP") == (None, None),
          "адрес TON разобран как XRP — проверка по валюте не работает")
    check(A.canonical_destination(BOUNCE, None, "BTC") is None,
          "валюта без тегов пущена через тегированный вход")

    # ── Ввод тега разбирается в типе СВОЕЙ валюты ──────────────────────────
    # Одна общая функция на все поверхности: у XRP значение целое, у TON —
    # текст. Числовой разбор для всех означал бы, что правильный memo молча
    # станет «тега нет» и адрес соберётся без него.
    check(A.parse_tag_input("order-42", "TON") == ("order-42", None),
          "текстовый memo TON не принят — заявка уйдёт без memo")
    check(A.parse_tag_input("12345", "XRP") == (12345, None),
          "числовой тег XRP не разобран")
    check(A.parse_tag_input("order-42", "XRP") == (None, "bad_number"),
          "текст принят как тег XRP — в заявку ляжет «тега нет» вместо отказа")
    check(A.parse_tag_input("4294967296", "XRP") == (None, "bad_number"),
          "тег XRP за границей 32 бит принят")
    check(A.parse_tag_input("", "TON") == (None, None)
          and A.parse_tag_input("  ", "XRP") == (None, None),
          "пустой ввод отдан как ошибка — клиент увидит отказ на пустом поле")
    check(A.parse_tag_input("x", "BTC") == (None, "not_tagged"),
          "тег у валюты без тегов принят молча")
    check(A.parse_tag_input("a" * 128, "TON")[1] == "bad_text"
          and A.parse_tag_input("две\nстроки", "TON")[1] == "bad_text",
          "слишком длинный или многострочный memo принят")

    # Вид и разделитель — свойства валюты, а не поверхности.
    check((AS.tag_kind("XRP"), AS.tag_kind("TON")) == ("number", "text"),
          "реестр не знает вида значения тега")
    check((AS.tag_separator("XRP"), AS.tag_separator("TON")) == (":", "#"),
          "реестр не знает разделителя «адрес+тег»")
    check(AS.tag_kind("BTC") is None and AS.tag_separator("BTC") is None,
          "валюта без тега получила вид/разделитель")
    # Сырой TON-адрес сам содержит двоеточие: прибитый разделитель разрезал бы
    # его пополам, поэтому «тег внутри адреса» ищется по СВОЕМУ символу.
    raw = "0:" + "a" * 64
    check(not AS.address_carries_tag("TON", raw),
          "сырой TON-адрес принят за «адрес с memo» — memo спросят не у того")
    check(AS.address_carries_tag("TON", BOUNCE + "#note"),
          "склейка «адрес#memo» не распознана")
    for code, cur in (("bad_number", "XRP"), ("bad_text", "TON")):
        check(bool(AS.tag_error_text(cur, code)) and
              AS.tag_error_text(cur, code) != AS.tag_error_text(cur, "not_tagged"),
              f"текст отказа {code} для {cur} пустой или неотличимый")

    if FAILS:
        print(f"❌ Провалов: {len(FAILS)}\n")
        for m in FAILS:
            print("  •", m)
        return 1
    print("✅ TON: адрес проверяется контрольной суммой, memo не пускает чужой "
          "перевод, хеш приведён к общему виду, обозреватель есть, адрес и memo "
          "проходят общий вход и разбираются обратно.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
