#!/usr/bin/env python3
"""Кошелёк TON: наблюдение честное, отправка отказана громко.

Зачем этот набор. Контур watch-only опасен ровно двумя способами. Первый —
выдать «не знаем» за «пусто»: недоступный обозреватель и пустой счёт дают одно
и то же число, а по нему принимается решение «хватит ли на выдачу». Второй —
промолчать про отсутствие подписи: вызывающий примет тишину за неудачную
попытку отправки и спишет её на сеть, вместо того чтобы позвать человека.

Сеть здесь НЕ дёргаем: HTTP-слой подменяется, проверяется разбор ответа.
Запуск: /root/bot/venv/bin/python3 tests/test_ton_wallet.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from wallet import ton_wallet as tw            # noqa: E402
from wallet import registry                    # noqa: E402

FAILS = []


def check(cond, msg):
    print(("✅ " if cond else "❌ ") + msg)
    if not cond:
        FAILS.append(msg)


def with_env(**kv):
    """Временная подмена окружения (возврат к прежнему состоянию гарантирован)."""
    class _Ctx:
        def __enter__(self):
            self.old = {k: os.environ.get(k) for k in kv}
            for k, v in kv.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        def __exit__(self, *a):
            for k, v in self.old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _Ctx()


def main():
    real_get = tw._get_json

    # ── адрес сервиса: одна точка на проект ───────────────────────────
    with with_env(TON_API_BASE=None, TON_API_URL=None):
        check(tw.api_url("getAddressBalance").endswith("/api/v2/getAddressBalance"),
              "по умолчанию идём в публичный toncenter")
    # Историческая переменная указывает на КОНКРЕТНЫЙ метод: владелец,
    # переопределивший её ради своего узла, должен получить свой узел и для
    # баланса — иначе сверка и остаток смотрят в разные места.
    with with_env(TON_API_BASE=None, TON_API_URL="https://my.node/api/v2/getTransactions"):
        check(tw.api_url("getAddressBalance") == "https://my.node/api/v2/getAddressBalance",
              "переопределённый узел действует и для баланса")
    with with_env(TON_API_BASE="https://own.node/api/v2/", TON_API_URL=None):
        check(tw.api_url("getTransactions") == "https://own.node/api/v2/getTransactions",
              "TON_API_BASE перекрывает умолчание, лишний слеш не ломает адрес")
    with with_env(TONCENTER_API_KEY=None):
        check("api_key" not in tw.api_params({"address": "x"}),
              "без ключа запрос уходит без api_key (это штатный режим, не сбой)")
    with with_env(TONCENTER_API_KEY="secret"):
        check(tw.api_params().get("api_key") == "secret", "ключ подставляется, когда задан")

    # Сверка выплат обязана ходить туда же, куда и баланс: две правды об одном
    # счёте — это выплата, которую одна половина системы видит, а вторая нет.
    from core import payout_discovery as pd
    seen = {}
    pd._get_json = lambda url, params=None, **k: seen.update(url=url, params=params) or {}
    try:
        with with_env(TON_API_BASE="https://own.node/api/v2", TONCENTER_API_KEY="k1"):
            pd._incoming_ton("EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N")
        check(seen.get("url") == "https://own.node/api/v2/getTransactions",
              f"сверка идёт на тот же узел, что и баланс (ушла на {seen.get('url')})")
        check((seen.get("params") or {}).get("api_key") == "k1",
              "сверка использует тот же ключ toncenter")
    finally:
        pd._get_json = real_get

    # ── «не знаем» — не ноль ──────────────────────────────────────────
    with with_env(TON_PAYOUT_ADDRESS=None):
        st = tw.account_state()
        check(st["balance"] is None and st["status"] == "NOT_CONFIGURED",
              "без TON_PAYOUT_ADDRESS честно говорим «не настроено», а не «0»")

    with with_env(TON_PAYOUT_ADDRESS="EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N"):
        tw._get_json = lambda *a, **k: {"ok": True, "result": "1500000000"}
        try:
            st = tw.account_state()
            check(abs(st["balance"] - 1.5) < 1e-9 and st["status"] == "OK",
                  f"нанотоны переведены в TON ({st['balance']})")
        finally:
            tw._get_json = real_get

        # toncenter отвечает 4xx с причиной в теле — причину обязан увидеть
        # владелец, иначе «адрес не разобран» выглядит как «сеть недоступна».
        tw._get_json = lambda *a, **k: {"ok": False, "error": "Failed to parse ton_addr"}
        try:
            st = tw.account_state()
            check(st["balance"] is None and st["status"] == "ERROR"
                  and "ton_addr" in (st["reason"] or ""),
                  f"причина отказа доходит до человека ({st['reason']!r})")
        finally:
            tw._get_json = real_get

        tw._get_json = lambda *a, **k: (_ for _ in ()).throw(OSError("нет сети"))
        try:
            st = tw.account_state()
            check(st["balance"] is None and st["status"] == "ERROR",
                  "сбой сети — «не знаем», а не «пусто»")
            check(tw.get_balance() == 0.0,
                  "get_balance при неизвестном остатке отдаёт 0.0 (фейл-клоуз)")
        finally:
            tw._get_json = real_get

        tw._get_json = lambda *a, **k: {"ok": True, "result": "не число"}
        try:
            check(tw.account_state()["status"] == "ERROR",
                  "нечисловой ответ не превращается в баланс")
        finally:
            tw._get_json = real_get

    # ── отправка отказана громко ──────────────────────────────────────
    # None означало бы «попытались и не вышло» — вызывающий списал бы это на
    # сеть. Здесь попытки не было вовсе, и причина обязана быть названа.
    try:
        tw.send("EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N", 1.0)
        check(False, "send() промолчал вместо отказа")
    except NotImplementedError as e:
        check("вручную" in str(e).lower() or "/worker" in str(e),
              "отказ отправки называет ручной путь выдачи")
    except Exception as e:
        check(False, f"send() бросил {type(e).__name__}, а не понятный отказ")

    # Флаг сам по себе ничего не открывает: подписывающей библиотеки нет.
    with with_env(TON_PAYOUTS_ENABLED="1"):
        check(tw.payouts_enabled() is True, "гейт читается из окружения")
        try:
            tw.send("EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N", 1.0)
            check(False, "включённый гейт заставил контур «отправить» без подписи")
        except NotImplementedError:
            check(True, "включённый гейт не открывает отправку без библиотеки")
    with with_env(TON_PAYOUTS_ENABLED=None):
        check(tw.payouts_enabled() is False, "по умолчанию выплаты TON выключены")

    check(tw.status()["watch_only"] is True and tw.status()["unlocked"] is False,
          "контур честно описан как watch-only")

    # ── реестр показывает сеть владельцу ──────────────────────────────
    check("TON" in registry.chains(), "TON есть в реестре кошельков")
    with with_env(TON_PAYOUT_ADDRESS="EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N"):
        tw._get_json = lambda *a, **k: {"ok": True, "result": "2000000000"}
        try:
            row = next(r for r in registry.overview() if r["chain"] == "TON")
        finally:
            tw._get_json = real_get
        check(row.get("configured") is True, "заданный адрес делает сеть настроенной")
        check(any(a["symbol"] == "TON" and abs((a["balance"] or 0) - 2.0) < 1e-9
                  for a in row.get("assets", [])),
              f"остаток виден в общем срезе ({row.get('assets')})")
    with with_env(TON_PAYOUT_ADDRESS=None):
        row = next(r for r in registry.overview() if r["chain"] == "TON")
        check(row.get("configured") is False,
              "без адреса сеть показана ненастроенной, а не с нулевым остатком")

    if FAILS:
        print(f"\n❌ Провалов: {len(FAILS)}")
        for m in FAILS:
            print("  •", m)
        return 1
    print("\n✅ TON-кошелёк: узел один на сверку и баланс, «не знаем» отличимо от "
          "нуля, отправка отказана с причиной, сеть видна владельцу.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
