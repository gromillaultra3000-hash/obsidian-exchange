#!/usr/bin/env python3
"""Идентификатор попытки: уникален при повторе и читается обратно в заявку.

Главное здесь — не «уникальность» сама по себе, а ПАРА: сделать идентификатор
уникальным и не поправить разбор — значит принять оплату и не узнать её.

Запуск: python3 tests/test_attempt_id.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import attempt_id  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
    return cond


def main():
    # ── уникальность там, где раньше был конфликт ─────────────────────
    ids = [attempt_id.make(1234) for _ in range(500)]
    check(len(set(ids)) == 500,
          f"из 500 попыток по одной заявке уникальных только {len(set(ids))} — "
          f"Montera ответит 422 «внешний id уже существует» и ретрай сгорит")
    # Посекундного суффикса не хватало: цикл ретраев успевает провернуться
    # трижды внутри одной секунды.
    burst = [attempt_id.make(1234) for _ in range(3)]
    check(len(set(burst)) == 3, "три подряд идущие попытки дали одинаковый id")

    # ── разбор возвращает ЗАЯВКУ, а не «всё после подчёркивания» ──────
    for oid in (1, 42, 1234, 99955118):
        a = attempt_id.make(oid)
        got = attempt_id.parse(a)
        check(got == str(oid), f"построили {a} — разобрали {got!r}, ждали {oid}")

    # ── старая форма (живые сделки, созданные до суффикса) ────────────
    check(attempt_id.parse("obsidian_1234") == "1234",
          "старый идентификатор без суффикса перестал читаться — вебхуки по "
          "уже созданным сделкам не найдут свою заявку")

    # ── чужое и мусор ─────────────────────────────────────────────────
    for bad in ("", None, "1234", "other_1234", "obsidian_", "obsidian_abc",
                "obsidianX_1234", "  ", "obsidian_12ab_x"):
        check(attempt_id.parse(bad) is None,
              f"мусор {bad!r} разобран как заявка {attempt_id.parse(bad)!r} — "
              f"чужой вебхук пометит оплаченной не ту заявку")
    check(attempt_id.parse("  obsidian_77_abc  ") == "77",
          "идентификатор с пробелами по краям не разобран")

    # ── свой префикс (выплаты Vertu) не путается с обычным ────────────
    out = attempt_id.make(55, prefix="obsidian_out")
    check(attempt_id.parse(out, prefix="obsidian_out") == "55",
          f"выплатный идентификатор {out} не разобран своим префиксом")
    check(attempt_id.parse(out) is None,
          "выплатный идентификатор разобран как обычная заявка — вебхук "
          "приёма пометит оплаченной заявку по номеру выплаты")

    # Правило «ни одной своей копии построения и разбора» живёт в мине
    # check_attempt_id_is_symmetric — здесь проверяется поведение модуля,
    # там то, что им пользуются все.

    # ── КАЖДЫЙ parse_webhook исполняется, а не только читается ────────
    # Разбор вебхука не вызывал ни один тест, и опечатка в нём (NameError на
    # необъявленной переменной) прошла бы в прод целиком: провайдер прислал
    # «оплачено», обработчик упал, заявка осталась pending. Ловится это
    # единственным способом — вызовом.
    cases = [
        ("montera", "MonteraProvider",
         lambda a: {"external_id": a, "status": "success"}, "paid"),
        ("greenpay", "GreenPayProvider",
         lambda a: {"external_id": a, "status": "success"}, "paid"),
        ("lava", "LavaProvider",
         lambda a: {"orderId": a, "status": 1}, "paid"),
        ("brabus", "BrabusProvider",
         lambda a: {"invoice": {"internalId": a, "status": "paid"}}, "paid"),
        ("stormtrade", "StormTradeProvider",
         lambda a: {"invoice": {"internalId": a, "status": "paid"}}, "paid"),
        ("xpayconnect", "XPayConnectProvider",
         lambda a: {"order_id": a, "status": "success"}, "paid"),
    ]
    import importlib
    for mod, cls_name, payload, want_status in cases:
        try:
            cls = getattr(importlib.import_module(f"providers.{mod}"), cls_name)
            inst = cls.__new__(cls)          # без сети и ключей: нужен только разбор
            oid, st = inst.parse_webhook(payload(attempt_id.make(4242)))
        except Exception as e:
            FAILS.append(f"providers/{mod}.parse_webhook падает на нормальном "
                         f"вебхуке: {type(e).__name__}: {e}")
            continue
        check(oid == "4242",
              f"providers/{mod}.parse_webhook вернул заявку {oid!r} вместо 4242 — "
              f"оплата придёт, а мы её не узнаем")
        check(st == want_status,
              f"providers/{mod}.parse_webhook вернул статус {st!r} вместо "
              f"{want_status!r} — заявка не станет оплаченной")
    # и старая форма, по которой у провайдеров живут созданные ранее сделки
    for mod, cls_name, payload, _ in cases:
        try:
            cls = getattr(importlib.import_module(f"providers.{mod}"), cls_name)
            oid, _st = cls.__new__(cls).parse_webhook(payload("obsidian_4242"))
        except Exception as e:
            FAILS.append(f"providers/{mod}.parse_webhook падает на старой форме: {e}")
            continue
        check(oid == "4242",
              f"providers/{mod}: вебхук по сделке, созданной до суффикса, "
              f"больше не находит свою заявку (получили {oid!r})")

    if FAILS:
        print(f"❌ Провалов: {len(FAILS)}\n")
        for m in FAILS:
            print("  •", m)
        return 1
    print("✅ Идентификатор попытки: уникален на повторах, читается обратно "
          "в заявку, старая форма понимается, чужое отбрасывается.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
