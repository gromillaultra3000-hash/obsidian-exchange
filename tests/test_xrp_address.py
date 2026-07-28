#!/usr/bin/env python3
"""XRP: адреса обеих форм и destination tag.

Почему отдельным набором. XRP — первая валюта, где тег может быть зашит В САМ
АДРЕС (X-адрес). Ошибка здесь не роняет ничего: перевод уходит, подтверждается
в сети и просто не зачисляется получателю — деньги клиента исчезают тихо.

Векторы получены от библиотеки xrpl-py (эталонная реализация) и вморожены сюда
намеренно: в CI библиотеки нет, а проверка обязана работать всё равно. Если
понадобится обновить — сгенерировать через
xrpl.core.addresscodec.classic_address_to_xaddress.

Запуск: python3 tests/test_xrp_address.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relay"))

from core.address import (  # noqa: E402
    parse_xrp_destination, is_valid_xrp, is_valid_xrp_classic, is_valid_xrp_tag,
    is_valid_btc, is_valid_ltc, is_valid_tron,
)
from core import assets as A  # noqa: E402

FAILURES = []


def check(name, got, exp):
    if got != exp:
        FAILURES.append(f"{name}: ждали {exp!r}, получили {got!r}")


# (X-адрес, ожидаемый classic, ожидаемый тег)
_X_VECTORS = [
    ("XVJeAMwkBxiJhrTTCXGX3m59mNvNGfF5tpAAKWxNkCtrVmY", "rGnsgZGispvHPBx6UvbHrJP4choYyC1Z6G", None),
    ("XVJeAMwkBxiJhrTTCXGX3m59mNvNGfuZnKQZrf4B22ytvZF", "rGnsgZGispvHPBx6UvbHrJP4choYyC1Z6G", 0),
    ("XVJeAMwkBxiJhrTTCXGX3m59mNvNGfu2woL2WsUJFLu9USF", "rGnsgZGispvHPBx6UvbHrJP4choYyC1Z6G", 1),
    ("XVJeAMwkBxiJhrTTCXGX3m59mNvNGfvMsYXdxaDRZM1BZHm", "rGnsgZGispvHPBx6UvbHrJP4choYyC1Z6G", 42),
    ("XVJeAMwkBxiJhrTTCXGX3m59mNvNGfzPGb19AtEvqqE3Drk", "rGnsgZGispvHPBx6UvbHrJP4choYyC1Z6G", 4294967295),
    ("X7czcheDsTAyLxU38bacxH6dUuSVMmqbftFjrVdb36nfpwj", "rsufEYGqDCYjj1PaVSz8BnbehmHHZohiPT", None),
    ("X7czcheDsTAyLxU38bacxH6dUuSVMmvRKBHL6asXxcAydpm", "rsufEYGqDCYjj1PaVSz8BnbehmHHZohiPT", 0),
    ("X7czcheDsTAyLxU38bacxH6dUuSVMmADHQQRehtmA44LvHH", "rsufEYGqDCYjj1PaVSz8BnbehmHHZohiPT", 42),
    ("XV2V66D935EdGhDsP8xmGB4QbAjkZGwDLnQJW7SCrjaAoYY", "rLAraCnQB5CZtpq8qq2RvSSvrhPntUMsYs", None),
    ("XV2V66D935EdGhDsP8xmGB4QbAjkZGEsXMivUhibqeC34Fh", "rLAraCnQB5CZtpq8qq2RvSSvrhPntUMsYs", 0),
    ("XV2V66D935EdGhDsP8xmGB4QbAjkZGK15eKX3qkMavpjjYG", "rLAraCnQB5CZtpq8qq2RvSSvrhPntUMsYs", 4294967295),
    ("X7i54zZAtnjgdZcdrEvgpHPAiUC4HLE1iMjgeypaRGDz2yv", "r3fKXTf7NirWSziq2c8Wss6aTgN9bpVAVZ", None),
    ("X7i54zZAtnjgdZcdrEvgpHPAiUC4HLMWr1KPHYHHNrM8Sti", "r3fKXTf7NirWSziq2c8Wss6aTgN9bpVAVZ", 42),
    ("XV49GsK2WGML6ydV51bXCKks8iG91qeiBpGxqHPAtsdEjLb", "rH93tV2D1kY7GQBieHYy6PS9Sy2fuepSsm", None),
    ("XV49GsK2WGML6ydV51bXCKks8iG91qj6T8CcroerAjLTr3H", "rH93tV2D1kY7GQBieHYy6PS9Sy2fuepSsm", 1),
    ("X7FbjZiaHpdPETBjeW5w9mNQpf3P9HgmQXwnAV1XMPRAibv", "rfTgXhbYytHBB4yrd2ref4DC1Kxsu9j4D9", None),
    ("X7FbjZiaHpdPETBjeW5w9mNQpf3P9Hmbboc6daH7BEfUVWF", "rfTgXhbYytHBB4yrd2ref4DC1Kxsu9j4D9", 0),
]

_CLASSIC_OK = [
    "rrpDp2dLMs7KyhZhg5RbReRagjWuvH7qB",
    "rrrrrrrrrrrrrrrrrrrrrhoLvTp",      # ACCOUNT_ZERO
    "rrrrrrrrrrrrrrrrrrrrBZbvji",       # ACCOUNT_ONE
    "rGnsgZGispvHPBx6UvbHrJP4choYyC1Z6G",
]

# Тот же аккаунт и тег, но сеть testnet. Мы работаем в mainnet: принять такой
# адрес — значит отправить в сеть, где монет нет.
_TESTNET_X = "T7PnNYsX9KwKKyMSW8M3hgHuJs9NRqRzCPs4veFG9zLLMNE"


def test_x_addresses_carry_their_tag():
    for x, classic, tag in _X_VECTORS:
        check(f"X→classic {x[:18]}…", parse_xrp_destination(x), (classic, tag))
        check(f"X валиден {x[:18]}…", is_valid_xrp(x), True)


def test_tag_zero_differs_from_no_tag():
    """Тег 0 — валидное значение, часть бирж использует именно его. Схлопывание
    0 и None отправило бы средства на общий счёт биржи без опознания."""
    by_tag = {}
    for x, classic, tag in _X_VECTORS:
        by_tag.setdefault((classic, tag), x)
    for (classic, tag), x in by_tag.items():
        if tag != 0:
            continue
        none_x = by_tag.get((classic, None))
        if none_x:
            check(f"X с тегом 0 ≠ X без тега ({classic[:10]}…)", x == none_x, False)
        check(f"тег 0 сохраняется ({classic[:10]}…)", parse_xrp_destination(x)[1], 0)


def test_classic_addresses():
    for c in _CLASSIC_OK:
        check(f"classic валиден {c[:14]}…", is_valid_xrp_classic(c), True)
        check(f"classic без тега {c[:14]}…", parse_xrp_destination(c), (c, None))


def test_corrupted_address_rejected():
    """Опечатка в одном символе сохраняет длину и алфавит, но делает адрес
    несуществующим. Ловит только контрольная сумма."""
    base = _CLASSIC_OK[0]
    alphabet = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"
    checked = 0
    for i in range(len(base)):
        repl = next(ch for ch in alphabet if ch != base[i])
        broken = base[:i] + repl + base[i + 1:]
        check(f"битый classic поз.{i} отвергнут", is_valid_xrp_classic(broken), False)
        checked += 1
    if checked < 20:
        FAILURES.append("проверено подозрительно мало позиций")

    x = _X_VECTORS[0][0]
    for i in range(0, len(x), 3):
        repl = next(ch for ch in alphabet if ch != x[i])
        check(f"битый X поз.{i} отвергнут", parse_xrp_destination(x[:i] + repl + x[i + 1:]),
              (None, None))


def test_testnet_and_foreign_networks_rejected():
    check("testnet X отвергнут", parse_xrp_destination(_TESTNET_X), (None, None))
    foreign = ["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
               "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
               "TJRabPrwbZy45sbavfcjinPJC18kjpRTv8",
               "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"]
    for a in foreign:
        check(f"чужая сеть не XRP: {a[:14]}…", is_valid_xrp(a), False)
    # и обратно — XRP не должен проходить как чужая валюта
    c = _CLASSIC_OK[0]
    check("XRP не BTC", is_valid_btc(c), False)
    check("XRP не LTC", is_valid_ltc(c), False)
    check("XRP не TRON", is_valid_tron(c), False)


def test_tag_validation():
    for tag, exp in [(None, True), (0, True), (42, True), (4294967295, True),
                     (4294967296, False), (-1, False), (1.9, False), ("42", False),
                     (True, False), ([], False)]:
        check(f"тег {tag!r}", is_valid_xrp_tag(tag), exp)


def test_registry_offers_xrp():
    """XRP обязан быть предложен клиенту, а не только уметь отправляться."""
    check("XRP поддерживается", A.is_supported_currency("XRP"), True)
    check("сеть XRP", A.networks_for("XRP"), ["XRPL"])
    check("метка сети", A.network_label("XRP"), "XRP Ledger")
    check("имя тега", A.tag_name("XRP"), "destination tag")
    check("у BTC тега нет", A.tag_name("BTC"), None)

    c = _CLASSIC_OK[0]
    x_tag = _X_VECTORS[3][0]
    x_none = _X_VECTORS[0][0]
    check("реестр: classic валиден", A.validate_address("XRP", c), True)
    check("реестр: X валиден", A.validate_address("XRP", x_tag), True)
    check("реестр: чужая сеть", A.validate_address("XRP", c, "TRC20"), False)
    check("реестр: нестроковый", A.validate_address("XRP", 12345), False)
    check("X с тегом несёт тег", A.address_carries_tag("XRP", x_tag), True)
    check("X без тега не несёт", A.address_carries_tag("XRP", x_none), False)
    check("classic не несёт тег", A.address_carries_tag("XRP", c), False)
    check("тег 0 принят", A.validate_tag("XRP", 0), True)
    check("тег у BTC отвергнут", A.validate_tag("BTC", 42), False)


def test_canonical_destination_binds_tag_to_address():
    """Тег хранится ВНУТРИ адреса, а не отдельным полем.

    Отдельная колонка означала бы, что каждое из восьми мест создания заявки,
    обе панели выдачи и уведомления обязаны её протащить. Место, где забыли,
    отправило бы XRP на биржу без тега — сеть подтвердит перевод, а получателю
    не зачислится. X-адрес делает потерю невозможной физически.
    """
    c = _CLASSIC_OK[0]
    x_tag = _X_VECTORS[3][0]          # тег 42 на другом аккаунте
    x_classic = _X_VECTORS[3][1]

    check("classic без тега хранится как есть", A.canonical_address("XRP", c, None), c)

    joined = A.canonical_address("XRP", c, 777)
    check("classic + тег → X-адрес", joined.startswith("X"), True)
    check("склейка разбирается обратно", parse_xrp_destination(joined), (c, 777))
    check("повторная канонизация устойчива", A.canonical_address("XRP", joined, None), joined)
    check("тот же тег ещё раз — не ошибка", A.canonical_address("XRP", joined, 777), joined)

    check("тег 0 не теряется", parse_xrp_destination(A.canonical_address("XRP", c, 0))[1], 0)
    check("тег 0 ≠ отсутствие тега", A.canonical_address("XRP", c, 0) == c, False)

    # Конфликт: адрес несёт один тег, а рядом передан другой. Молчаливый выбор
    # любого из двух = отправка не туда, куда просил клиент.
    check("конфликт тегов отвергнут", A.canonical_address("XRP", x_tag, 9), None)
    check("тег из X-адреса сохранён", parse_xrp_destination(A.canonical_address("XRP", x_tag, 42)),
          (x_classic, 42))

    for bad in (1.9, "42", True, -1, 2 ** 32, []):
        check(f"негодный тег {bad!r} отвергнут", A.canonical_address("XRP", c, bad), None)

    check("битый адрес отвергнут", A.canonical_address("XRP", c[:-1] + "9", 5), None)
    check("чужая сеть отвергнута",
          A.canonical_address("XRP", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", 5), None)


def test_tag_on_untagged_currency_is_refused():
    """У BTC/LTC/USDT тега не бывает. Пришедший тег — признак путаницы на входе,
    и проглотить его молча значит записать заявку не тем, чем её создавали."""
    btc = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
    check("BTC без тега — как есть", A.canonical_address("BTC", btc, None), btc)
    check("BTC с тегом — отказ", A.canonical_address("BTC", btc, 5), None)
    check("пробелы по краям обрезаются", A.canonical_address("BTC", f"  {btc} ", None), btc)
    check("неизвестная валюта — отказ", A.canonical_address("DOGE", "x", None), None)
    check("нестроковый адрес — отказ", A.canonical_address("BTC", 12345, None), None)


def main():
    for fn in (test_x_addresses_carry_their_tag, test_tag_zero_differs_from_no_tag,
               test_classic_addresses, test_corrupted_address_rejected,
               test_testnet_and_foreign_networks_rejected, test_tag_validation,
               test_registry_offers_xrp, test_canonical_destination_binds_tag_to_address,
               test_tag_on_untagged_currency_is_refused):
        try:
            fn()
        except Exception as e:
            FAILURES.append(f"{fn.__name__}: {type(e).__name__}: {e}")

    if FAILURES:
        print(f"❌ Провалов: {len(FAILURES)}\n")
        for f in FAILURES[:25]:
            print(f"  {f}")
        return 1
    print("✅ XRP: обе формы адреса, тег внутри X-адреса, тег 0 ≠ «тега нет», "
          "порча ловится суммой, чужие сети и testnet отвергнуты.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
