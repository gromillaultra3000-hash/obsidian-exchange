#!/usr/bin/env python3
"""Тест единого реестра кошельков (wallet.registry).

Проверяет нормализацию overview() и ИЗОЛЯЦИЮ сбоев: падение одного адаптера
(в status или balance) не должно ронять весь обзор — админ-поверхность обязана
показать остальные сети. Сеть не дёргаем: адаптеры подменяются фейковыми.

Запуск: /root/bot/venv/bin/python3 tests/test_wallet_registry.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
from wallet import registry as R  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


def _ok_chain():
    return {"chain": "OK", "label": "Ок-сеть",
            "status": lambda: {"configured": True, "unlocked": False,
                               "address": "addr1", "network": "net"},
            "balance": lambda: {"assets": [{"symbol": "OK", "balance": 1.5, "status": "OK"}],
                                "gasAsset": {"symbol": "GAS", "balance": 0.1}, "error": None}}


def _status_raises():
    def _boom():
        raise RuntimeError("status_down")
    return {"chain": "BAD1", "label": "Сбой-статуса",
            "status": _boom, "balance": lambda: {"assets": []}}


def _balance_raises():
    def _boom():
        raise RuntimeError("rpc_down")
    return {"chain": "BAD2", "label": "Сбой-баланса",
            "status": lambda: {"configured": True, "unlocked": True, "address": "a2", "network": "n"},
            "balance": _boom}


def _not_configured():
    return {"chain": "NEW", "label": "Не создан",
            "status": lambda: {"configured": False, "unlocked": False, "address": "", "network": "n"},
            "balance": lambda: {"assets": [{"symbol": "NEW", "balance": 9.9, "status": "OK"}]}}


_orig = R.CHAINS
R.CHAINS = [_ok_chain, _status_raises, _balance_raises, _not_configured]
try:
    rows = R.overview(include_balance=True)
    by = {r["chain"]: r for r in rows}

    check("обзор вернул все 4 сети (сбой одной не роняет остальные)", len(rows) == 4)
    check("OK-сеть: актив с балансом нормализован",
          by["OK"]["assets"][0]["balance"] == 1.5 and by["OK"]["assets"][0]["symbol"] == "OK")
    check("OK-сеть: gasAsset прокинут", by["OK"]["gasAsset"]["symbol"] == "GAS")
    check("сбой в status → error помечен, configured=False",
          by["BAD1"].get("error", "").startswith("status:") and not by["BAD1"]["configured"])
    check("сбой в balance → error помечен, но сеть в обзоре есть",
          by["BAD2"].get("error", "").startswith("balance:") and by["BAD2"]["configured"])
    check("не созданный кошелёк: баланс НЕ запрашивается (assets пусты)",
          by["NEW"]["configured"] is False and by["NEW"]["assets"] == [])

    # include_balance=False — только статусы, без вызова balance()
    st_rows = R.overview(include_balance=False)
    check("include_balance=False: assets пусты у всех", all(r["assets"] == [] for r in st_rows))
finally:
    R.CHAINS = _orig

# реальные адаптеры зарегистрированы и в правильном порядке
names = R.chains()
check("реальные сети зарегистрированы: BTC/LTC/TRON/EVM/XRP",
      names == ["BTC", "LTC", "TRON", "EVM", "XRP"])

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
