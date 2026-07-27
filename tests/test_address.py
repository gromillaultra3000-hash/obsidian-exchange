#!/usr/bin/env python3
"""Тесты контрольных сумм криптоадресов (core.address).

Регуляркой «похоже на адрес» опечатка в одном символе проходит насквозь, и
крипта уходит в никуда безвозвратно. Контрольная сумма ловит это до отправки.

Векторы Bech32/Bech32m взяты ДОСЛОВНО из официального BIP-350 (раздел
«Test vectors»), а не из памяти. Keccak-256 отдельно сверен с pycryptodome
(см. tests/test_address_keccak.py — требует venv бота).

Запуск: python3 tests/test_address.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import address as A  # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# ── Bech32m: валидные строки (BIP-350) ──────────────────────────────────────
VALID_BECH32M = [
    "A1LQFN3A",
    "a1lqfn3a",
    "an83characterlonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber11sg7hg6",
    "abcdef1l7aum6echk45nj3s0wdvt2fg8x9yrzpqzd3ryx",
    "11llllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllllludsr8",
    "split1checkupstagehandshakeupstreamerranterredcaperredlc445v",
    "?1v759aa",
]
ok = all(A.bech32_decode(s)[2] == "bech32m" for s in VALID_BECH32M)
check(f"BIP-350: {len(VALID_BECH32M)} валидных строк Bech32m распознаны", ok)

# Ни одна из них не должна быть валидным Bech32 (спека это гарантирует)
check("те же строки НЕ являются Bech32",
      all(A.bech32_decode(s)[2] != "bech32" for s in VALID_BECH32M))

# ── Bech32m: невалидные строки (BIP-350) ────────────────────────────────────
INVALID_BECH32M = [
    "\x201xj0phk",            # HRP вне диапазона
    "\x7f1g6xzxy",            # HRP вне диапазона
    "\x801vctc34",            # HRP вне диапазона
    "an84characterslonghumanreadablepartthatcontainsthetheexcludedcharactersbioandnumber11d6pts4",
    "qyrz8wqd2c9m",           # нет разделителя
    "1qyrz8wqd2c9m",          # пустой HRP
    "y1b0jsk6g",              # недопустимый символ данных
    "lt1igcx5c0",             # недопустимый символ данных
    "in1muywd",               # слишком короткая контрольная сумма
    "mm1crxm3i",              # недопустимый символ в сумме
    "au1s5cgom",              # недопустимый символ в сумме
    "M1VUXWEZ",               # сумма посчитана по HRP в верхнем регистре
    "16plkw9",                # пустой HRP
    "1p2gdwpf",               # пустой HRP
]
bad = [s for s in INVALID_BECH32M if A.bech32_decode(s)[2] is not None]
check(f"BIP-350: {len(INVALID_BECH32M)} невалидных строк отклонены", not bad)
if bad:
    print("   не отклонены:", bad)

# ── Segwit-адреса: валидные (BIP-350) ───────────────────────────────────────
VALID_SEGWIT = [
    "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4",
    "bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7kt5nd6y",
    "BC1SW50QGDZ25J",
    "bc1zw508d6qejxtdg4y5r3zarvaryvaxxpcs",
    "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0",
]
bad = [a for a in VALID_SEGWIT if not A.is_valid_btc(a)]
check(f"BIP-350: {len(VALID_SEGWIT)} валидных BTC segwit-адресов приняты", not bad)
if bad:
    print("   отвергнуты:", bad)

# ── Segwit-адреса: невалидные (BIP-350) ─────────────────────────────────────
INVALID_SEGWIT = [
    ("tc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq5zuyut", "чужой HRP"),
    ("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqh2y7hd", "Bech32 вместо Bech32m"),
    ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kemeawh", "Bech32m вместо Bech32"),
    ("bc1p38j9r5y49hruaue7wxjce0updqjuyyx0kh56v8s25huc6995vvpql3jow4", "символ вне алфавита"),
    ("BC130XLXVLHEMJA6C4DQV22UAPCTQUPFHLXM9H8Z3K2E72Q4K9HCZ7VQ7ZWS8R", "неверная версия свидетеля"),
    ("bc1pw5dgrnzv", "программа 1 байт"),
    ("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7v8n0nx0muaewav253zgeav", "программа 41 байт"),
    ("BC1QR508D6QEJXTDG4Y5R3ZARVARYV98GJ9P", "неверная длина для версии 0"),
    ("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7v07qwwzcrf", "лишнее дополнение битами"),
    ("bc1gmk9yu", "пустая секция данных"),
]
bad = [(a, why) for a, why in INVALID_SEGWIT if A.is_valid_btc(a)]
check(f"BIP-350: {len(INVALID_SEGWIT)} невалидных segwit-адресов отклонены", not bad)
if bad:
    print("   приняты ошибочно:", bad)

check("смешанный регистр отклоняется (BIP-350)",
      not A.is_valid_btc("tb1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vq47Zagq"))

# Верхний регистр bech32 валиден по BIP-173 — предфильтр не должен его резать
from core import assets as _AS  # noqa: E402
check("BC1… в верхнем регистре доходит до проверки суммы",
      _AS.validate_address("BTC", "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4"))
check("короткая witness-программа (BC1SW50QGDZ25J) принята",
      _AS.validate_address("BTC", "BC1SW50QGDZ25J"))
check("bc1z…-адрес (16-байтная программа) принят",
      _AS.validate_address("BTC", "bc1zw508d6qejxtdg4y5r3zarvaryvaxxpcs"))

# ── Base58Check: подмена одного символа ломает сумму ────────────────────────
BTC_LEGACY = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
check("валидный BTC legacy принят", A.is_valid_btc(BTC_LEGACY))
check("BTC legacy с опечаткой отклонён",
      not A.is_valid_btc(BTC_LEGACY[:-1] + ("A" if BTC_LEGACY[-1] != "A" else "B")))
check("BTC P2SH (3…) принят", A.is_valid_btc("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"))
check("символ вне алфавита Base58 отклонён", not A.is_valid_btc("1Boat0SLRHtKNngkdXEeobR76b53LETtpy"))
check("пустая строка отклонена", not A.is_valid_btc(""))
check("None не роняет", not A.is_valid_btc(None))

# ── Кросс-валюта: адрес одной монеты не должен проходить как другая ─────────
LTC_ADDR = "LhK2kQwiaAvhjWY799cZvMyYwnQAcxkarr"
check("валидный LTC принят", A.is_valid_ltc(LTC_ADDR))
check("BTC-адрес НЕ проходит как LTC", not A.is_valid_ltc(BTC_LEGACY))
check("LTC-адрес НЕ проходит как BTC", not A.is_valid_btc(LTC_ADDR))
check("LTC bech32 (ltc1…) принят",
      A.is_valid_ltc("ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kgmn4n9"))
check("BTC bech32 НЕ проходит как LTC",
      not A.is_valid_ltc("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4"))

# ── TRON ────────────────────────────────────────────────────────────────────
TRON_ADDR = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"   # контракт USDT-TRC20
check("валидный TRON-адрес принят", A.is_valid_tron(TRON_ADDR))
check("TRON с опечаткой отклонён",
      not A.is_valid_tron(TRON_ADDR[:-1] + ("a" if TRON_ADDR[-1] != "a" else "b")))
check("BTC-адрес НЕ проходит как TRON", not A.is_valid_tron(BTC_LEGACY))
check("строка нужной длины из алфавита, но без верной суммы, отклонена",
      not A.is_valid_tron("TXYZabcdefghijklmnopqrstuvwxyzABCD"))

# ── EIP-55 ──────────────────────────────────────────────────────────────────
EVM_MIXED = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
check("валидный EIP-55 адрес принят", A.is_valid_evm_address(EVM_MIXED))
# Единый регистр контрольной суммы НЕ несёт: опечатка hex→hex неотличима от
# настоящего адреса. По умолчанию такие отклоняем (EVM_REQUIRE_EIP55=1).
os.environ.pop("EVM_REQUIRE_EIP55", None)
check("всё строчными ОТКЛОНЕНО по умолчанию (нет контрольной суммы)",
      not A.is_valid_evm_address(EVM_MIXED.lower()))
check("всё прописными ОТКЛОНЕНО по умолчанию",
      not A.is_valid_evm_address("0x" + EVM_MIXED[2:].upper()))
check("адрес из одних цифр принят (сумму кодировать нечем)",
      A.is_valid_evm_address("0x" + "1234567890" * 4))
os.environ["EVM_REQUIRE_EIP55"] = "0"
check("EVM_REQUIRE_EIP55=0 разрешает единый регистр",
      A.is_valid_evm_address(EVM_MIXED.lower()))
check("но смешанный регистр с битой суммой отклонён и при ослаблении",
      not A.is_valid_evm_address("0x5aAeb6053f3E94C9b9A09f33669435E7Ef1BeAed"))
os.environ.pop("EVM_REQUIRE_EIP55", None)
check("смешанный регистр с неверной суммой отклонён",
      not A.is_valid_evm_address("0x5aAeb6053f3E94C9b9A09f33669435E7Ef1BeAed"))
check("короткий адрес отклонён", not A.is_valid_evm_address("0x5aAeb6053F3E94C9b9A09f3366"))
check("без 0x отклонён", not A.is_valid_evm_address("5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"))
check("не-hex отклонён", not A.is_valid_evm_address("0xZZAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"))

# Официальные примеры EIP-55
for a in ("0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
          "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
          "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb"):
    check(f"EIP-55 пример {a[:10]}… принят", A.is_valid_evm_address(a))

# ── Keccak-256 против эталонной библиотеки ──────────────────────────────────
# Своя реализация Keccak без сверки с эталоном не стоит ничего. pycryptodome
# есть в venv бота, но не в системном python3 — если его нет, проверку
# пропускаем (BIP-векторы выше от этого не зависят).
try:
    from Crypto.Hash import keccak as _pk  # type: ignore

    def _ref(b):
        h = _pk.new(digest_bits=256)
        h.update(b)
        return h.digest()

    import random
    random.seed(20260727)
    # Границы блока (rate=136) — самое частое место ошибок в реализациях губки
    probes = [b"", b"abc", b"a" * 135, b"a" * 136, b"a" * 137, b"a" * 271,
              b"a" * 272, bytes(range(256))]
    probes += [os.urandom(random.randint(0, 400)) for _ in range(60)]
    mismatch = [len(p) for p in probes if A.keccak256(p) != _ref(p)]
    check(f"Keccak-256 совпадает с эталоном на {len(probes)} входах", not mismatch)
    if mismatch:
        print("   расхождения на длинах:", mismatch[:10])
except ImportError:
    print("⏭  Keccak-сверка пропущена: нет pycryptodome (запустите в venv бота)")

if failures:
    print(f"\n{len(failures)} провал(ов): {failures}")
    sys.exit(1)
print("\nВсе проверки пройдены.")
