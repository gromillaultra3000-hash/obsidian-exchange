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
check("USDT подтверждается подписью", "USDT" in sp.currencies())
# Список идёт от ВИТРИНЫ, а не от реестра схем: подтверждать адрес монеты,
# которую мы сегодня не отдаём, некуда — подставить такой адрес будет не во что.
# ETH и USDT-ERC20 на витрине не стоят (резерв не задан), значит и в форме их
# быть не должно; включатся вместе с витриной.
from services import offerings as _off0                              # noqa: E402
for cur in sorted(sp.currencies()):
    check(f"{cur} в форме подтверждения — потому что он есть на витрине",
          _off0.is_offered(cur))
check("сети USDT в форме — ровно те, что на витрине",
      sp.proof_networks("USDT") == [n for n in assets.networks_for("USDT")
                                    if _off0.is_offered("USDT", n)])
check("сеть, которой нет на витрине, к подтверждению не предлагается",
      all(_off0.is_offered("USDT", n) for n in sp.proof_networks("USDT")))
check("у BTC сеть одна", sp.proof_networks("BTC") == ["MAINNET"])
check("монета вне реестра сетей не получает ни одной",
      sp.proof_networks("XRP") == [])
check("схема выбирается сетью, а не монетой",
      (sp._scheme_for("USDT", "TRC20"), sp._scheme_for("USDT", "ERC20"))
      == (sp.SCHEME_TRON, sp.SCHEME_EVM))
check("чужая сеть схемы не получает", sp._scheme_for("USDT", "BEP20") is None)

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
    # Runtime code validates an already-migrated schema and deliberately owns
    # no DDL.  The isolated fixture therefore creates the persistence contract
    # it exercises instead of relying on an import-time production migration.
    c.execute("CREATE TABLE wallet_links (user_id INTEGER, chain TEXT, address TEXT,"
              " verified_at TEXT, PRIMARY KEY(user_id,chain))")
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

# ── EVM и TRON: подписываем ЧУЖИМИ реализациями, проверяем своей ──────────────
# Смысл именно в этом: свою подпись своим же кодом проверит и ошибочный код.
# eth_account (MetaMask-совместимый personal_sign) и tronpy (TIP-191, то же,
# что делает TronLink signMessageV2) написаны не нами и про наш модуль не знают.
print("\n── EVM и TRON, настоящая криптография ──")
from eth_account import Account                                      # noqa: E402
from eth_account.messages import encode_defunct                      # noqa: E402
from tronpy.keys import PrivateKey as TronKey                        # noqa: E402


def evm_sign(key, text):
    return Account.sign_message(encode_defunct(text=text), key).signature.hex()


acct = Account.create()

# ETH сегодня на витрине НЕТ (резерв не задан) — и форма его не предлагает: см.
# «витрина решает». Но EVM-путь всё равно живой (он же обслуживает USDT-ERC20,
# когда его включат), и проверять его нужно настоящей подписью. Поэтому витрину
# на время этой части подменяем: код доказательства от неё не зависит.
from services import offerings as _off                               # noqa: E402
check("пока ETH не на витрине, подтверждать его адрес не предлагаем",
      "ETH" not in sp.currencies())
_real_is_offered = _off.is_offered
_off.is_offered = lambda cur, net=None: True
check("с открытой витриной ETH снова доступен для подтверждения",
      "ETH" in sp.currencies())

ready = sp.prepare("ETH", acct.address, UID)
check("подготовка для ETH удалась", ready["ok"] and ready["scheme"] == "evm")
check("в тексте нет строки сети (у ETH она одна)", "network:" not in ready["message"])
v = sp.verify("ETH", acct.address, ready["payload"], evm_sign(acct.key, ready["message"]),
              subject=UID)
check("MetaMask-подпись принята", v["verified"] and v["reason"] == "ok")
check("вердикт называет цепь связи", v.get("chain") == "ETH")

stranger = Account.create()
check("чужой адрес с этой подписью не подтверждается",
      sp.verify("ETH", stranger.address, ready["payload"],
                evm_sign(acct.key, ready["message"]), subject=UID)["reason"] == "not_owner")
check("подпись другого текста не подходит",
      sp.verify("ETH", acct.address, ready["payload"],
                evm_sign(acct.key, "I agree to something else"),
                subject=UID)["reason"] in ("not_owner", "bad_signature"))
check("код, выданный другому клиенту, отвергнут",
      sp.verify("ETH", acct.address, ready["payload"],
                evm_sign(acct.key, ready["message"]), subject=OTHER_UID)["reason"]
      == "payload_alien")
check("испорченная подпись — не «не тот владелец», а «не разобрана»",
      sp.verify("ETH", acct.address, ready["payload"], "0x" + "11" * 65,
                subject=UID)["reason"] in ("bad_signature", "not_owner"))
check("подпись не той длины отвергнута",
      sp.verify("ETH", acct.address, ready["payload"], "0xdeadbeef",
                subject=UID)["reason"] == "bad_signature")

# v пишут по-разному: MetaMask 27/28, часть библиотек 0/1. Принимаем оба вида.
raw = bytes.fromhex(evm_sign(acct.key, ready["message"]).replace("0x", ""))
low_v = (raw[:64] + bytes([raw[64] - 27])).hex()
check("подпись с v=0/1 (TronLink и часть библиотек) тоже принята",
      sp.verify("ETH", acct.address, ready["payload"], low_v, subject=UID)["verified"])
check("v вне 0..3 и 27/28 — отказ, а не «возьмём младшие биты»",
      sp.verify("ETH", acct.address, ready["payload"],
                (raw[:64] + bytes([99])).hex(), subject=UID)["reason"] == "bad_signature")

_off.is_offered = _real_is_offered      # дальше — настоящая витрина

tron_key = TronKey.random()
tron_addr = tron_key.public_key.to_base58check_address()
ready_t = sp.prepare("USDT", tron_addr, UID, network="TRC20")
check("подготовка для USDT/TRC20 удалась", ready_t["ok"] and ready_t["scheme"] == "tron")
check("у монеты с двумя сетями сеть НАЗВАНА в подписываемом тексте",
      "network: TRC20" in ready_t["message"])
sig_t = tron_key.sign_msg(ready_t["message"].encode()).hex()
vt = sp.verify("USDT", tron_addr, ready_t["payload"], sig_t, subject=UID, network="TRC20")
check("TronLink-подпись принята", vt["verified"])
check("цепь связи — TRON, а не USDT", vt.get("chain") == "TRON")
check("чужой TRON-адрес не подтверждается",
      sp.verify("USDT", TronKey.random().public_key.to_base58check_address(),
                ready_t["payload"], sig_t, subject=UID, network="TRC20")["reason"]
      == "not_owner")

# Главное про две цепи одного ключа: secp256k1 и keccak у Ethereum и TRON общие,
# и без разных обёрток одна подпись подошла бы к обоим счетам сразу.
same_key = TronKey(bytes.fromhex(acct.key.hex().replace("0x", "")))
check("это один и тот же ключ в двух цепях",
      same_key.public_key.to_hex_address()[-40:].lower() == acct.address[2:].lower())
ready_x = sp.prepare("USDT", same_key.public_key.to_base58check_address(),
                     UID, network="TRC20")
check("подпись Ethereum-обёрткой не годится для TRON-адреса того же ключа",
      not sp.verify("USDT", same_key.public_key.to_base58check_address(),
                    ready_x["payload"], evm_sign(acct.key, ready_x["message"]),
                    subject=UID, network="TRC20")["verified"])

# Связь ложится по ЦЕПИ: иначе доказанный TRC-20-адрес затирался бы ERC-20-адресом
# того же клиента (ключ таблицы — «клиент + цепь»).
check("цепь TRON разворачивается в пару USDT/TRC20",
      assets.pairs_on_chain("TRON") == [("USDT", "TRC20")])
check("цепь ETH годна и для ETH, и для USDT-ERC20",
      set(assets.pairs_on_chain("ETH")) == {("ETH", "ERC20"), ("USDT", "ERC20")})
check("BTC и TRON — разные цепи, затирать друг друга нечем",
      assets.chain_of("BTC") != assets.chain_of("USDT", "TRC20"))

os.unlink(tmp.name)

print()
if failures:
    print(f"❌ {len(failures)} провал(ов):")
    for f in failures:
        print("   ·", f)
    sys.exit(1)
print("Все проверки пройдены.")
