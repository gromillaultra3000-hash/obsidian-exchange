#!/usr/bin/env python3
"""Тесты единого источника валют/сетей/валидации адресов (relay/core/assets.py).

Фаза C: правила «какие валюты», «в каких сетях», «валиден ли адрес» раньше
дублировались в bot/main_bot.py, relay/utils/exchange_calc.py и
relay-fastapi/main.py и расходились. Этот модуль — единственный источник
правды, импортируется всеми тремя. Ловит: (1) фейл-клоуз на неизвестной
валюте/сети; (2) адрес не в ту сеть (0x-адрес как USDT-TRC20) не проходит;
(3) флаг MULTICHAIN_UI_ENABLED по умолчанию ВЫКЛ; (4) нормализация сети не
даёт обойти защиту пробелами/регистром/синонимами.

Запуск: python3 tests/test_assets.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))
from core import assets as A  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# ── фиче-гейт ────────────────────────────────────────────────────────────────
os.environ.pop("MULTICHAIN_UI_ENABLED", None)
check("мультичейн-UI флаг по умолчанию ВЫКЛ", A.multichain_ui_enabled() is False)
for v in ("1", "true", "YES", "on"):
    os.environ["MULTICHAIN_UI_ENABLED"] = v
    check(f"флаг включается значением {v!r}", A.multichain_ui_enabled() is True)
os.environ.pop("MULTICHAIN_UI_ENABLED", None)

# ── допустимые валюты/сети ───────────────────────────────────────────────────
check("BTC поддерживается", A.is_supported_currency("BTC"))
check("btc (регистр) поддерживается", A.is_supported_currency("btc"))
check("DOGE не поддерживается", not A.is_supported_currency("DOGE"))
check("BTC сеть по умолчанию MAINNET", A.default_network("BTC") == A.NET_MAINNET)
check("USDT сеть по умолчанию TRC20", A.default_network("USDT") == A.NET_TRC20)
check("ETH сеть по умолчанию ERC20", A.default_network("ETH") == A.NET_ERC20)
check("неизвестная валюта → default_network None", A.default_network("DOGE") is None)

# ── normalize_network: пусто → дефолт, синонимы, фейл-клоуз ────────────────
check("USDT + '' → TRC20 (дефолт)", A.normalize_network("USDT", "") == A.NET_TRC20)
check("USDT + 'tron' → TRC20 (синоним)", A.normalize_network("USDT", "tron") == A.NET_TRC20)
check("USDT + ' erc-20 ' (пробелы/регистр) → ERC20", A.normalize_network("USDT", " erc-20 ") == A.NET_ERC20)
check("USDT + 'bsc' → None (не в allowlist)", A.normalize_network("USDT", "bsc") is None)
check("BTC + 'ERC20' → None (чужая сеть для BTC)", A.normalize_network("BTC", "ERC20") is None)
check("неизвестная валюта + любая сеть → None", A.normalize_network("DOGE", "MAINNET") is None)

# ── validate_address: формат валюты И сети ──────────────────────────────────
check("BTC bech32 валиден", A.validate_address("BTC", "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"))
check("BTC legacy валиден", A.validate_address("BTC", "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"))
check("LTC невалидный (BTC-адрес под LTC)", not A.validate_address("LTC", "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"))
check("USDT TRC20-адрес по умолчанию (network=None)",
      A.validate_address("USDT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"))
check("USDT 0x-адрес БЕЗ network=ERC20 → отказ (не та сеть по умолчанию)",
      not A.validate_address("USDT", "0x1234567890123456789012345678901234567890"))
check("USDT 0x-адрес С network=ERC20 → ок",
      A.validate_address("USDT", "0x1234567890123456789012345678901234567890", "ERC20"))
check("ETH валидный 0x-адрес", A.validate_address("ETH", "0x1234567890123456789012345678901234567890"))
check("ETH T-адрес (TRON) невалиден", not A.validate_address("ETH", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"))
check("пустой адрес → отказ", not A.validate_address("BTC", ""))
# Контрольная сумма: строка проходит регулярку по форме, но адресом не является.
# Ровно этот класс ошибок раньше пропускался и крипта уходила безвозвратно.
check("BTC с опечаткой (форма верна, сумма нет) → отказ",
      not A.validate_address("BTC", "1BoatSLRHtKNngkdXEeobR76b53LETtpyA"))
check("USDT-TRC20 с опечаткой → отказ",
      not A.validate_address("USDT", "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6a"))
check("выдуманная строка нужного вида → отказ",
      not A.validate_address("USDT", "TXYZabcdefghijklmnopqrstuvwxyzABCD"))
check("неизвестная валюта → отказ", not A.validate_address("DOGE", "anything"))
check("сеть не из allowlist валюты → отказ (fail-closed)",
      not A.validate_address("USDT", "0x1234567890123456789012345678901234567890", "BSC"))

# ── фейл-клоуз на нестроковый вход (не должен кидать исключение) ────────────
check("normalize_currency(None) → ''", A.normalize_currency(None) == "")
check("normalize_currency(123) → '' (не строка)", A.normalize_currency(123) == "")
check("normalize_currency([1,2]) → '' (не строка)", A.normalize_currency([1, 2]) == "")
check("normalize_network('BTC', 123) → None (сеть не строка)", A.normalize_network("BTC", 123) is None)
check("validate_address('BTC', None) → False (без исключения)", A.validate_address("BTC", None) is False)
check("validate_address('BTC', 12345) → False (адрес не строка)", A.validate_address("BTC", 12345) is False)
check("validate_address(None, 'addr') → False (валюта не строка)", A.validate_address(None, "addr") is False)

# ── network_label ────────────────────────────────────────────────────────────
check("network_label USDT TRC20 → 'TRC-20'", A.network_label("USDT", "TRC20") == "TRC-20")
check("network_label USDT ERC20 → 'ERC-20'", A.network_label("USDT", "ERC20") == "ERC-20")
check("network_label BTC → 'Mainnet'", A.network_label("BTC") == "Mainnet")
check("network_label неизвестной валюты → ''", A.network_label("DOGE") == "")

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
