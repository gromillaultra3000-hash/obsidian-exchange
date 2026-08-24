#!/usr/bin/env python3
"""Что провайдер умеет сообщить — и что мы говорим человеку, когда не умеет.

Запуск: python3 tests/test_provider_caps.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import provider_caps as pc  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def main():
    # ── подтверждённый живым трафиком канал ───────────────────────────
    check(pc.has_verification_channel("montera") is True,
          "у Montera канал запроса доп. проверки объявлен отсутствующим, хотя "
          "вебхук подтверждён живыми запросами")

    # ── те, у кого канала нет ─────────────────────────────────────────
    for p in ("vertu", "brabus", "stormtrade", "greenpay", "lava", "xpay",
              "rspay", "fallback"):
        check(pc.has_verification_channel(p) is False,
              f"у {p} объявлен канал доп. проверки, которого нет — персонал "
              f"будет ждать сигнала, который никогда не придёт")

    # ── fail-closed: незнакомый провайдер НЕ умеет ────────────────────
    for p in ("новый_провайдер", "", None, "PayOK", 42):
        check(pc.has_verification_channel(p) is False,
              f"незнакомый провайдер {p!r} сочтён умеющим — умолчание должно "
              f"звать человека, а не обещать сигнал")

    # ── вариант через двоеточие — тот же провайдер ────────────────────
    check(pc.has_verification_channel("brabus:tbank_deeplink") is False,
          "вариант brabus:tbank_deeplink не распознан как brabus")
    check(pc.has_verification_channel("  MONTERA  ") is True,
          "регистр и пробелы ломают распознавание провайдера")

    # ── текст для персонала говорит, ЧТО ДЕЛАТЬ ───────────────────────
    note = pc.verification_note("vertu")
    check("НЕТ" in note or "нет" in note,
          f"подсказка по vertu не сообщает об отсутствии канала: {note}")
    check("вручную" in note or "кабинете" in note,
          f"подсказка по vertu не говорит, где искать: {note}")
    check("вебхук" in pc.verification_note("montera"),
          "подсказка по montera не объясняет, что клиент уже уведомлён")

    # ── каждый живой провайдер должен быть в таблице явно ─────────────
    # Умолчание безопасно, но молчаливое умолчание для СВОЕГО провайдера —
    # это «забыли внести», а не «решили».
    pdir = os.path.join(ROOT, "relay", "providers")
    skip = {"base.py", "__init__.py", "swapuz.py", "trocador.py", "platega.py"}
    for fn in sorted(os.listdir(pdir)):
        if not fn.endswith(".py") or fn in skip:
            continue
        name = fn[:-3]
        check(name in pc._VERIFICATION_CHANNEL,
              f"providers/{fn}: провайдера нет в таблице возможностей — про него "
              f"молча считается «канала нет», и это может быть неправдой")

    # ── обработчик смерти сессии пользуется этим знанием ──────────────
    main_src = open(os.path.join(ROOT, "relay-fastapi", "main.py"), encoding="utf-8").read()
    body = main_src[main_src.find("def handle_dead_session("):]
    body = body[:body.find("\nasync def ")]
    dispatcher = main_src[main_src.find("def _dispatch_lifecycle_work("):]
    dispatcher = dispatcher[:dispatcher.find("\nasync def ")]
    lifecycle_src = open(os.path.join(ROOT, "relay", "repositories",
                                      "order_lifecycle_store.py"), encoding="utf-8").read()
    check(bool(body), "relay-fastapi/main.py: нет handle_dead_session — смерть "
                      "сделки у провайдера снова никому не сообщается")
    for need, why in (("provider_caps", "не объясняет персоналу, ждать ли сигнала"),
                      ("sent_notifications", "не одноразовый — опрос завалит клиента "
                                             "одинаковыми сообщениями раз в 30 секунд"),
                      ("order_receipts", "не различает клиента с чеком и без — а это "
                                         "два разных сообщения"),
                      ("notify_telegram", "молчит клиенту"),
                      ("notify_admins_tg", "молчит персоналу")):
        proof = body + dispatcher + (lifecycle_src if need in
                                     ("sent_notifications", "order_receipts") else "")
        check(need in proof, f"handle_dead_session {why} (нет {need})")
    check(not re.search(r"UPDATE orders SET status=", body),
          "handle_dead_session меняет статус ЗАЯВКИ: «сделка не состоялась» у "
          "провайдера не доказывает, что клиент не платил — так человеку с "
          "ушедшими деньгами скажут «оплаты не было»")

    if FAILS:
        print(f"❌ Провалов: {len(FAILS)}\n")
        for m in FAILS:
            print("  •", m)
        return 1
    print("✅ Возможности провайдеров: канал доп. проверки объявлен честно, "
          "умолчание fail-closed, смерть сделки доходит до клиента и персонала.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
