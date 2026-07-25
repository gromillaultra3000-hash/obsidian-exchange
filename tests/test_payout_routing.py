#!/usr/bin/env python3
"""Тесты роутинга авто-выплат по сетям (wallet.payout_routing).

Фаза B (EVM→бот): ETH/USDT-ERC20 идут в evm_wallet под фиче-гейтом, USDT-TRC20 —
НЕ через EVM. Ловит: (1) гейт по умолчанию ВЫКЛ; (2) USDT без сети не уходит в EVM
(иначе Tron-выплата ушла бы не в ту сеть = потеря средств).

Запуск: /root/bot/venv/bin/python3 tests/test_payout_routing.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
from wallet import payout_routing as P  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# ── фиче-гейт ─────────────────────────────────────────────────────────────────
os.environ.pop("EVM_PAYOUTS_ENABLED", None)
check("гейт по умолчанию ВЫКЛ", P.evm_payouts_enabled() is False)
for v in ("1", "true", "YES", "on"):
    os.environ["EVM_PAYOUTS_ENABLED"] = v
    check(f"гейт включается значением {v!r}", P.evm_payouts_enabled() is True)
os.environ["EVM_PAYOUTS_ENABLED"] = "0"
check("гейт '0' → ВЫКЛ", P.evm_payouts_enabled() is False)
os.environ.pop("EVM_PAYOUTS_ENABLED", None)

# ── определение актива EVM ─────────────────────────────────────────────────────
check("ETH → EVM(ETH)", P.evm_payout_asset("ETH") == "ETH")
check("USDT + ERC20 → EVM(USDT)", P.evm_payout_asset("USDT", "ERC20") == "USDT")
check("USDT + ETHEREUM → EVM(USDT)", P.evm_payout_asset("USDT", "ethereum") == "USDT")
check("код USDT_ERC20 → EVM(USDT)", P.evm_payout_asset("USDT_ERC20") == "USDT")
check("код USDT-ERC20 → EVM(USDT)", P.evm_payout_asset("USDT-ERC20") == "USDT")

# ключевая защита: USDT без сети / TRC20 НЕ уходит в EVM (это Tron)
check("USDT без сети → НЕ EVM (Tron)", P.evm_payout_asset("USDT") is None)
check("USDT + TRC20 → НЕ EVM (Tron)", P.evm_payout_asset("USDT", "TRC20") is None)
check("BTC → НЕ EVM", P.evm_payout_asset("BTC") is None)
check("LTC → НЕ EVM", P.evm_payout_asset("LTC") is None)
check("пусто → НЕ EVM", P.evm_payout_asset("") is None and P.evm_payout_asset(None) is None)

# fail-closed при ПРОТИВОРЕЧИИ кода и сети: явный TRC20 побеждает (не в чужую сеть)
check("USDT_ERC20 + TRC20 (конфликт) → None (fail-closed)",
      P.evm_payout_asset("USDT_ERC20", "TRC20") is None)
check("USDT-ERC20 + TRON (конфликт) → None (fail-closed)",
      P.evm_payout_asset("USDT-ERC20", "TRON") is None)
check("ETH + TRC20 (бессмыслица) → None (fail-closed)",
      P.evm_payout_asset("ETH", "TRC20") is None)

# allowlist сетей: неизвестная/чужая EVM-совместимая сеть → None (не в ту сеть)
check("USDT_ERC20 + BSC → None (сеть не в allowlist)",
      P.evm_payout_asset("USDT_ERC20", "BSC") is None)
check("ETH + POLYGON → None (сеть не в allowlist)",
      P.evm_payout_asset("ETH", "POLYGON") is None)
# нормализация: пробелы/регистр не обходят защиту и не ломают распознавание
check("' TRC20 ' с пробелами → None (нормализация strip)",
      P.evm_payout_asset("USDT", " TRC20 ") is None)
check("' erc20 ' с пробелами/регистром → EVM(USDT)",
      P.evm_payout_asset("USDT", " erc20 ") == "USDT")
check("' eth ' валюта с пробелами → EVM(ETH)",
      P.evm_payout_asset(" eth ") == "ETH")

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
