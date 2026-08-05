#!/usr/bin/env python3
"""Доказательство владения адресом подписью кошелька (core/sig_proof).

Проверки идут на НАСТОЯЩЕЙ криптографии: ключи, подписи и адреса считаются
здесь же. Моки тут были бы самообманом — весь смысл модуля в том, сходится ли
восстановленный из подписи ключ с заявленным адресом, а мок сойдётся с чем
угодно.
"""
import base64
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))
os.environ.setdefault("RELAY_SECRET", "test-sig-proof-secret")

from coincurve import PrivateKey                                    # noqa: E402
from core import address as ad                                      # noqa: E402
from core import sig_proof as sp                                    # noqa: E402
from core import assets as assets                                   # noqa: E402

failures = []


def check(name, cond):
    print(("✅ " if cond else "❌ ") + name)
    if not cond:
        failures.append(name)


# ── вспомогательное: адреса и подписи ────────────────────────────────────────
def b58(version, h160):
    return ad._b58check_encode_with(bytes([version]) + h160, ad._B58_ALPHABET)


def bech32(hrp, ver, prog):
    """Кодировщик segwit — только для тестов: в ядре нужен лишь разбор."""
    data = [ver] + ad._convertbits(prog, 8, 5, True)
    const = ad._BECH32_CONST if ver == 0 else ad._BECH32M_CONST
    polymod = ad._bech32_polymod(ad._bech32_hrp_expand(hrp) + data + [0] * 6) ^ const
    chk = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(ad._BECH32_CHARSET[d] for d in data + chk)


OWNER = PrivateKey.from_hex("11" * 32)
STRANGER = PrivateKey.from_hex("22" * 32)
PUB_C = OWNER.public_key.format(compressed=True)
PUB_U = OWNER.public_key.format(compressed=False)
H_C = sp._hash160(PUB_C)
H_U = sp._hash160(PUB_U)

UID = 900001
OTHER_UID = 900002

COINS = {"BTC": (0x00, 0x05, "bc"), "LTC": (0x30, 0x32, "ltc")}


def sign(key, currency, message, header_base=31):
    dig = sp.message_digest(currency, message)
    raw = key.sign_recoverable(dig, hasher=None)
    return base64.b64encode(bytes([header_base + raw[64]]) + raw[:64]).decode()


def proof(currency, address, subject=UID, key=OWNER, header_base=31):
    ready = sp.prepare(currency, address, subject)
    if not ready["ok"]:
        return ready, None
    return ready, sign(key, currency, ready["message"], header_base)


# ── реестр монет ─────────────────────────────────────────────────────────────
print("\n── реестр монет ──")
check("BTC и LTC подтверждаются подписью", {"BTC", "LTC"} <= sp.currencies())
check("монеты с тегом в список не попадают",
      not (sp.currencies() & set(assets.TAGGED_CURRENCIES)))
check("USDT подписью не подтверждается (нет реализации)", "USDT" not in sp.currencies())

# Нет движка восстановления ключа — нет и обещания: иначе клиент получит
# «подпись не разобрана» на безупречной подписи и будет копировать её заново.
_rec = sp.recovery_available
try:
    sp.recovery_available = lambda: False
    check("без coincurve монеты не предлагаются вовсе", sp.currencies() == set())
    check("и подготовка отказывает по монете, а не по адресу",
          sp.prepare("BTC", b58(0x00, H_C), UID)["reason"] == "bad_currency")
finally:
    sp.recovery_available = _rec

_saved = assets.SIGNED_MESSAGE_CURRENCIES
try:
    # Даже если монету с тегом впишут в реестр руками — она не пройдёт.
    assets.SIGNED_MESSAGE_CURRENCIES = {"BTC", "TON"}
    check("TON, вписанный в реестр, всё равно отсеян (адрес с memo склеен)",
          "TON" not in sp.currencies())
finally:
    assets.SIGNED_MESSAGE_CURRENCIES = _saved

# ── текст на подпись ─────────────────────────────────────────────────────────
print("\n── текст на подпись ──")
addr_btc = b58(0x00, H_C)
msg = sp.message_for("BTC", addr_btc, "code-1")
check("текст содержит адрес", addr_btc in msg)
check("текст содержит код", "code-1" in msg)
check("текст называет монету", "currency: BTC" in msg)
check("текст обещает, что перевода нет", "moves no funds" in msg)
check("текст только ASCII (экран аппаратного кошелька)", msg.isascii())
check("тот же вход — тот же текст", sp.message_for("BTC", addr_btc, "code-1") == msg)
check("чужая монета — текста нет", sp.message_for("DOGE", addr_btc, "code-1") is None)
check("без кода текста нет", sp.message_for("BTC", addr_btc, "") is None)
check("без адреса текста нет", sp.message_for("BTC", "", "code-1") is None)

check("хеш сообщения зависит от монеты (разные префиксы сетей)",
      sp.message_digest("BTC", msg) != sp.message_digest("LTC", msg))
check("хеш чужой монеты не считается", sp.message_digest("DOGE", msg) is None)

# ── prepare ──────────────────────────────────────────────────────────────────
print("\n── подготовка к подписи ──")
ready = sp.prepare("BTC", addr_btc, UID)
check("prepare отдаёт текст и код", ready["ok"] and ready["message"] and ready["payload"])
check("prepare нормализует адрес и монету",
      ready["currency"] == "BTC" and ready["address"] == addr_btc)
check("prepare при отказе НЕ кладёт причину в поле текста на подпись",
      "message" not in sp.prepare("BTC", "мусор", UID))
check("негодный адрес → bad_address", sp.prepare("BTC", "1мусор", UID)["reason"] == "bad_address")
check("чужая монета → bad_currency", sp.prepare("DOGE", addr_btc, UID)["reason"] == "bad_currency")
check("LTC-адрес под BTC не проходит",
      sp.prepare("BTC", b58(0x30, H_C), UID)["reason"] == "bad_address")
check("адрес с приклеенным тегом на подпись не берём",
      sp.prepare("BTC", addr_btc + "#memo", UID)["reason"] == "bad_address")
check("коды у двух вызовов разные (одноразовость)",
      sp.prepare("BTC", addr_btc, UID)["payload"] != sp.prepare("BTC", addr_btc, UID)["payload"])

# ── честная подпись всех типов адресов ───────────────────────────────────────
print("\n── честная подпись ──")
for cur, (v_pkh, v_sh, hrp) in COINS.items():
    a_pkh = b58(v_pkh, H_C)
    r, s = proof(cur, a_pkh)
    check(f"{cur}: P2PKH (сжатый ключ)", sp.verify(cur, a_pkh, r["payload"], s, subject=UID)["verified"])

    a_pkh_u = b58(v_pkh, H_U)
    r, s = proof(cur, a_pkh_u, header_base=27)
    check(f"{cur}: P2PKH (несжатый ключ)",
          sp.verify(cur, a_pkh_u, r["payload"], s, subject=UID)["verified"])

    a_w = bech32(hrp, 0, H_C)
    r, s = proof(cur, a_w)
    check(f"{cur}: P2WPKH (bech32)", sp.verify(cur, a_w, r["payload"], s, subject=UID)["verified"])

    a_sh = b58(v_sh, sp._hash160(b"\x00\x14" + H_C))
    r, s = proof(cur, a_sh)
    check(f"{cur}: P2SH-P2WPKH", sp.verify(cur, a_sh, r["payload"], s, subject=UID)["verified"])

    # Electrum подписывает segwit заголовком от P2PKH, а Trezor — «своим».
    # Заголовок даёт только номер восстановления, и разные его варианты
    # обязаны приниматься: иначе честный кошелёк объявляется чужим.
    for hb in (27, 31, 35, 39):
        r, s = proof(cur, a_w, header_base=hb)
        check(f"{cur}: заголовок подписи {hb}+recid принят",
              sp.verify(cur, a_w, r["payload"], s, subject=UID)["verified"])

# ── отказы ───────────────────────────────────────────────────────────────────
print("\n── отказы ──")
addr = b58(0x00, H_C)
r, s = proof("BTC", addr)

v = sp.verify("BTC", addr, r["payload"], sign(STRANGER, "BTC", r["message"]), subject=UID)
check("подпись чужим ключом → not_owner", v["reason"] == "not_owner")

v = sp.verify("BTC", addr, r["payload"], s, subject=OTHER_UID)
check("код, выданный другому клиенту → payload_alien", v["reason"] == "payload_alien")

v = sp.verify("BTC", addr, r["payload"], s, subject=UID, now=time.time() + 3600)
check("просроченный код → payload_expired", v["reason"] == "payload_expired")

v = sp.verify("BTC", addr, r["payload"][:-2] + "00", s, subject=UID)
check("подделанный код → bad_payload", v["reason"] == "bad_payload")

check("пустая подпись → bad_request",
      sp.verify("BTC", addr, r["payload"], "", subject=UID)["reason"] == "bad_request")
check("не base64 → bad_signature",
      sp.verify("BTC", addr, r["payload"], "не подпись!", subject=UID)["reason"] == "bad_signature")
check("подпись не той длины → bad_signature",
      sp.verify("BTC", addr, r["payload"], base64.b64encode(b"\x1f" * 40).decode(),
                subject=UID)["reason"] == "bad_signature")
check("заголовок вне диапазона → bad_signature",
      sp.verify("BTC", addr, r["payload"],
                base64.b64encode(bytes([99]) + base64.b64decode(s)[1:]).decode(),
                subject=UID)["reason"] == "bad_signature")

# Подпись верна, но сделана для ДРУГОГО адреса того же клиента: текст внутри
# подписи другой, значит ключ восстановится не тот.
other_addr = b58(0x00, sp._hash160(STRANGER.public_key.format(compressed=True)))
check("подпись, снятая с другого адреса, не подходит",
      not sp.verify("BTC", other_addr, r["payload"], s, subject=UID)["verified"])

# Та же подпись под другой монетой: префикс сети в хеше другой.
ltc_addr = b58(0x30, H_C)
r_ltc, _ = proof("LTC", ltc_addr)
check("подпись BTC не годится для LTC",
      not sp.verify("LTC", ltc_addr, r_ltc["payload"], s, subject=UID)["verified"])

# Несжатый ключ не может стоять за segwit-адресом.
a_w = bech32("bc", 0, H_U)
check("P2WPKH из несжатого ключа не считается адресом клиента",
      not sp.verify("BTC", a_w, r["payload"], sign(OWNER, "BTC", r["message"], 27),
                    subject=UID)["verified"])

# Типы адресов, за которыми стоит не один ключ.
taproot = bech32("bc", 1, bytes(range(32)))
check("taproot → честный отказ, а не «не совпало»",
      sp.verify("BTC", taproot, r["payload"], s, subject=UID)["reason"]
      in ("unsupported_address", "bad_address"))
p2wsh = bech32("bc", 0, bytes(range(32)))
check("P2WSH → честный отказ",
      sp.verify("BTC", p2wsh, r["payload"], s, subject=UID)["reason"]
      in ("unsupported_address", "bad_address"))

check("монета вне реестра → bad_currency",
      sp.verify("DOGE", addr, r["payload"], s, subject=UID)["reason"] == "bad_currency")
check("пустой адрес → bad_request",
      sp.verify("BTC", "", r["payload"], s, subject=UID)["reason"] == "bad_request")
check("у каждой причины есть человеческий текст",
      all(sp.reason_text(c) and sp.reason_text(c) != "Подтвердить владение не удалось."
          for c in ("ok", "bad_address", "not_owner", "payload_alien", "bad_signature")))
check("неизвестная причина не остаётся пустой строкой", bool(sp.reason_text("что-то новое")))

# ── подтверждённый адрес доходит до книги ────────────────────────────────────
# Связь пишется под именем ЦЕПИ («BTC»), а книга проверяет адрес по СЕТИ.
# Сеть BTC называется MAINNET, и запись с сетью «BTC» не прошла бы проверку —
# подтверждённый подписью адрес молча исчез бы ровно там, где клиент его ждёт.
print("\n── подтверждённый адрес в книге ──")
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
from core import wallet_link as wl                                  # noqa: E402
from core import address_book as ab                                 # noqa: E402
wl.DB_PATH = ab.DB_PATH = tmp.name
import sqlite3                                                      # noqa: E402
with sqlite3.connect(tmp.name) as c:
    c.execute("CREATE TABLE orders (order_id TEXT, user_id INTEGER, currency TEXT,"
              " network TEXT, crypto_address TEXT, status TEXT, created_at TEXT,"
              " updated_at TEXT, agreed_crypto_amount REAL, paid_btc_tx TEXT)")
    c.commit()

check("связь по подписи сохранена", wl.remember(UID, "BTC", addr))
book = ab.entries_for(UID)
check("подтверждённый адрес есть в книге", any(e["address"] == addr for e in book))
entry = next((e for e in book if e["address"] == addr), {})
check("он помечен подтверждённым", entry.get("verified") is True)
check("сеть у него каноническая (MAINNET, а не «BTC»)", entry.get("network") == "MAINNET")
check("книга находит его при выборе BTC в форме заявки",
      any(e["address"] == addr for e in ab.entries_for(UID, "BTC", "MAINNET")))
check("владение подтверждается для подстановки", ab.owns(UID, "BTC", addr))
check("чужому клиенту он не виден", not ab.owns(OTHER_UID, "BTC", addr))
os.unlink(tmp.name)

print()
if failures:
    print(f"❌ {len(failures)} провал(ов):")
    for f in failures:
        print("   ·", f)
    sys.exit(1)
print("Все проверки пройдены.")
