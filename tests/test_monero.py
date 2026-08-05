#!/usr/bin/env python3
"""Monero: адрес, реестр, путь выплаты, цена.

Адреса здесь настоящие (донат-адрес проекта Monero и адрес CCS) плюс собранный
на месте integrated — его нельзя взять из документации, не раскрыв чей-то
payment id. Проверка контрольной суммы считается keccak-ом, поэтому подделать
адрес перестановкой символов нельзя, и тест это показывает.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core import address as ad                                      # noqa: E402
from core import assets as assets                                   # noqa: E402
from core import txid as txid                                       # noqa: E402
from wallet import payout_routing as routing                        # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# Настоящие mainnet-адреса Monero.
STD = "44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A"
SUB = "888tNkZrPN6JsEgekjMnABU4TBzc2Dt29EPAvkRxbANsAnjyPbb3iQ1YBRk1UXcdRsiKc9dhwMVgN5S9cQUiyoogDavup3H"


def xmr_encode(raw: bytes) -> str:
    """Кодировщик монеро-base58 — только для тестов: ядру нужен лишь разбор."""
    out = []
    for i in range(0, len(raw), 8):
        block = raw[i:i + 8]
        num = int.from_bytes(block, "big")
        size = ad._XMR_BLOCK_ENCODED[len(block)]
        s = ""
        while num:
            num, rem = divmod(num, 58)
            s = ad._B58_ALPHABET[rem] + s
        out.append(s.rjust(size, ad._B58_ALPHABET[0]))
    return "".join(out)


def build(prefix: int, spend: bytes, view: bytes, pid: bytes = b"") -> str:
    body = bytes([prefix]) + spend + view + pid
    return xmr_encode(body + ad.keccak256(body)[:4])


SPEND = bytes(range(32))
VIEW = bytes(range(32, 64))
PID = bytes.fromhex("0123456789abcdef")

# ── разбор адреса ────────────────────────────────────────────────────────────
print("\n── адрес ──")
check("обычный адрес принят", ad.is_valid_xmr(STD))
check("обычный адрес опознан как standard", ad.parse_monero_address(STD)[0] == "standard")
check("субадрес принят и опознан", ad.parse_monero_address(SUB)[0] == "subaddress")
check("у обычного адреса payment id пуст", ad.parse_monero_address(STD)[1] == "")

integrated = build(ad.XMR_PREFIX_INTEGRATED, SPEND, VIEW, PID)
kind, pid = ad.parse_monero_address(integrated)
check("integrated-адрес принят", kind == "integrated")
check("payment id читается из адреса", pid == PID.hex())
check("длина integrated — 106 символов", len(integrated) == 106)
check("длина обычного — 95 символов", len(build(ad.XMR_PREFIX_STANDARD, SPEND, VIEW)) == 95)

# ── подделки и чужие сети ────────────────────────────────────────────────────
print("\n── что не должно проходить ──")
check("опечатка в последнем символе ломает контрольную сумму",
      not ad.is_valid_xmr(STD[:-1] + ("B" if STD[-1] != "B" else "C")))
check("опечатка в середине ломает контрольную сумму",
      not ad.is_valid_xmr(STD[:40] + ("x" if STD[40] != "x" else "y") + STD[41:]))
# Перестановка двух символов сохраняет длину и алфавит — регулярка её пропустит.
swapped = STD[:10] + STD[11] + STD[10] + STD[12:]
check("перестановка символов не проходит (регулярке она незаметна)",
      not ad.is_valid_xmr(swapped))
check("testnet-адрес отвергнут (перевод в mainnet ушёл бы в никуда)",
      not ad.is_valid_xmr(build(53, SPEND, VIEW)))
check("stagenet-адрес отвергнут", not ad.is_valid_xmr(build(24, SPEND, VIEW)))
check("integrated без payment id (не та длина) отвергнут",
      not ad.is_valid_xmr(build(ad.XMR_PREFIX_INTEGRATED, SPEND, VIEW)))
check("обычный префикс с лишними 8 байтами отвергнут",
      not ad.is_valid_xmr(build(ad.XMR_PREFIX_STANDARD, SPEND, VIEW, PID)))
check("биткойн-адрес не монеро", not ad.is_valid_xmr("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))
check("пусто", not ad.is_valid_xmr(""))
check("не строка", not ad.is_valid_xmr(12345))
check("символ вне алфавита", not ad.is_valid_xmr(STD[:-1] + "0"))
# Блок длиной 1 или 4 символа в монеро-base58 невозможен — таблица длин их не
# содержит, и разбор обязан отказать, а не «додумать».
check("невозможная длина блока отвергнута", ad._xmr_b58_decode("4" * 12) is None)

# ── реестр валют ─────────────────────────────────────────────────────────────
print("\n── реестр ──")
check("XMR — поддержанная валюта", assets.is_supported_currency("XMR"))
check("сеть XMR — MONERO", assets.networks_for("XMR") == [assets.NET_MONERO])
check("синоним «monero» приводится к канону",
      assets.normalize_network("XMR", "monero") == assets.NET_MONERO)
check("чужая сеть для XMR отвергается",
      assets.normalize_network("XMR", "TRC20") is None)
check("метка сети человеческая", assets.network_label("XMR") == "Monero")
check("адрес проходит через реестр", assets.validate_address("XMR", STD))
check("субадрес проходит через реестр", assets.validate_address("XMR", SUB))
check("integrated проходит через реестр", assets.validate_address("XMR", integrated))
check("монеро-адрес не принимается как BTC", not assets.validate_address("BTC", STD))
# Первые два символа адреса кодируют префикс ВМЕСТЕ с началом ключа траты, а не
# один префиксный байт. Взятый из документации образец обычно приходится на
# нижний край диапазона и проходит любую, даже неверную, регулярку — поэтому
# проверяем верхний край: ключ, начинающийся со старшего байта.
HIGH = b"\xff" + bytes(range(31))
check("integrated-адрес с ключом из верхнего края диапазона принят",
      assets.validate_address("XMR", build(ad.XMR_PREFIX_INTEGRATED, HIGH, VIEW, PID)))
check("субадрес с ключом из верхнего края диапазона принят",
      assets.validate_address("XMR", build(ad.XMR_PREFIX_SUBADDRESS, HIGH, VIEW)))
check("обычный адрес с ключом из верхнего края диапазона принят",
      assets.validate_address("XMR", build(ad.XMR_PREFIX_STANDARD, HIGH, VIEW)))
check("биткойн-адрес не принимается как XMR",
      not assets.validate_address("XMR", "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))
check("назначение целиком принимается", assets.validate_destination("XMR", STD))
# Отдельного поля тега у XMR нет: payment id живёт ВНУТРИ integrated-адреса,
# и второе поле противоречило бы первому.
check("XMR не считается монетой с отдельным тегом",
      "XMR" not in assets.TAGGED_CURRENCIES)

# ── путь выплаты ─────────────────────────────────────────────────────────────
print("\n── выплата ──")
check("контур XMR — ручной, а не «никто не решал»",
      routing.payout_contour("XMR") == "manual")
check("XMR не уходит в EVM-контур", routing.evm_payout_asset("XMR") is None)
check("контур не путается от регистра", routing.payout_contour(" xmr ") == "manual")

# ── цена ─────────────────────────────────────────────────────────────────────
print("\n── цена ──")
from utils import exchange_calc as calc                             # noqa: E402
check("у XMR есть источник цены на сайте", "XMR" in calc._COINGECKO_IDS)
check("у XMR есть аварийная цена", calc._FALLBACK_RATES.get("XMR", 0) > 0)
check("у XMR НЕТ пары на Binance (снята в 2024) — и это записано явно",
      "XMR" not in calc._BINANCE_SYMBOL)
check("аварийная цена XMR не похожа на цену тезера",
      calc._FALLBACK_RATES["XMR"] > 100 * calc._FALLBACK_RATES["USDT"])
check("кеш курсов заведён для XMR", "XMR" in calc._rate_cache)

# Главное: при недоступном CoinGecko монета без пары на Binance НЕ должна
# получить цену USDTRUB. Раньше отсутствие пары означало ветку «значит, USDT».
class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def fake_get(url, timeout=8):
    if "coingecko" in url:
        raise RuntimeError("coingecko молчит")
    if "USDTRUB" in url:
        return FakeResp({"price": "91.5"})
    raise RuntimeError("нет такой пары")


_real = calc.requests.get
calc.requests.get = fake_get
try:
    calc._rate_cache["XMR"] = {"rate": 0, "ts": 0}
    rate = calc.get_cached_rate("XMR")
    check("без CoinGecko XMR идёт по аварийной цене, а НЕ по цене USDT",
          rate == calc._FALLBACK_RATES["XMR"])
    calc._rate_cache["USDT"] = {"rate": 0, "ts": 0}
    check("а вот USDT по паре USDTRUB считается как прежде",
          abs(calc.get_cached_rate("USDT") - 91.5) < 1e-9)
finally:
    calc.requests.get = _real
    calc._rate_cache["XMR"] = {"rate": 0, "ts": 0}
    calc._rate_cache["USDT"] = {"rate": 0, "ts": 0}

# ── обозреватель ─────────────────────────────────────────────────────────────
print("\n── ссылка на транзакцию ──")
TX = "9" * 64
check("ссылка на монеро-транзакцию существует",
      (txid.explorer_url("XMR", TX) or "").endswith(TX))
check("ссылка ведёт в монеро-обозреватель", "xmr" in (txid.explorer_url("XMR", TX) or ""))
check("XMR в списке известных обозревателей", "XMR" in txid.known_currencies())
check("пометка ручной выдачи ссылкой не становится",
      txid.explorer_url("XMR", "выдано вручную") is None)

# ── витрина ──────────────────────────────────────────────────────────────────
print("\n── витрина ──")
from services import offerings as off                               # noqa: E402
_real_reserves = off._reserves
try:
    off._reserves = lambda: {}
    off._cache["data"] = None
    check("без резерва XMR клиенту не предлагается", not off.is_offered("XMR"))
    check("причина названа человеческим языком",
          "setreserve XMR" in off.get_offerings(force=True)["reason_xmr_off"])
    off._reserves = lambda: {"XMR": 2.5}
    off._cache["data"] = None
    check("с резервом XMR открыт", off.is_offered("XMR", "MONERO"))
    check("но только в своей сети", not off.is_offered("XMR", "TRC20"))
    check("витрина отдаёт сеть монеты", off.offered_networks("XMR") == ["MONERO"])
    # Открытие XMR не должно тянуть за собой чужие направления.
    check("резерв XMR не открывает TON", not off.is_offered("TON"))
finally:
    off._reserves = _real_reserves
    off._cache["data"] = None

# ── сверка выдачи ────────────────────────────────────────────────────────────
# Цепь Monero прочитать нельзя: суммы и получатель скрыты устройством сети.
# Значит, сверка обязана СКАЗАТЬ это, а не вернуть пустой список — по пустому
# списку заявка считается проверенной и висит в 'paid' вечно.
print("\n── сверка выдачи ──")
from core import payout_discovery as pd                              # noqa: E402

check("XMR объявлена нечитаемой цепью", "XMR" in pd.UNREADABLE_CHAINS)
try:
    pd.incoming_transfers("XMR", STD)
    check("чтение цепи XMR отказывает, а не отдаёт пустой список", False)
except pd.ChainUnreadable as e:
    check("чтение цепи XMR отказывает, а не отдаёт пустой список", True)
    check("отказ несёт человеческую причину", len(e.why) > 40)
    check("отказ помнит монету", e.currency == "XMR")
except Exception as e:                                               # noqa: BLE001
    check(f"чтение цепи XMR отказывает своим типом, а не {type(e).__name__}", False)

# Проход сверки: заявка в нечитаемой цепи обязана попасть человеку, а не в
# корзину «попробуем позже» и не в тишину.
_real_stuck, _real_used, _real_trusted = pd.stuck_orders, pd._used_txids, pd.trusted_senders
try:
    pd.stuck_orders = lambda: [{"order_id": 777, "user_id": 1, "rub_amount": 9000,
                                "currency": "XMR", "network": "MONERO",
                                "crypto_address": STD, "agreed_crypto_amount": 0.3,
                                "paid_ts": 0}]
    pd._used_txids = lambda: set()
    pd.trusted_senders = lambda cur: set()
    res = pd.discover(rate_fn=lambda cur, rub: 30000)
    check("заявка в нечитаемой цепи попала в список «только руками»",
          [v["order_id"] for v in res.get("manual", [])] == [777])
    check("и НЕ выглядит временным сбоем сети", not res.get("errors"))
    check("и не посчитана как «ничего не нашли»", res.get("none") == 0)
    report = pd.format_report(res)
    check("отчёт о ней рассказывает", "777" in report)
    check("в отчёте названа причина", "Monero" in report)
    check("в отчёте дана готовая команда закрытия", "/force_payout 777" in report)
    fp_one = pd.alert_fingerprint(res)
    res2 = {**res, "manual": res["manual"] + [{"order_id": 778}]}
    check("новая такая заявка пробивает окно молчания",
          pd.alert_fingerprint(res2) != fp_one)
    check("та же самая — не продлевает его", pd.alert_fingerprint({**res}) == fp_one)
finally:
    pd.stuck_orders, pd._used_txids, pd.trusted_senders = _real_stuck, _real_used, _real_trusted

print()
if failures:
    print(f"❌ {len(failures)} провал(ов):")
    for f in failures:
        print("   ·", f)
    sys.exit(1)
print("Все проверки пройдены.")
