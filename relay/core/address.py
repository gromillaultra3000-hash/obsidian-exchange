"""Проверка контрольных сумм криптоадресов — чистый stdlib, без зависимостей.

Зачем. До этого адрес проверялся ТОЛЬКО регуляркой «похоже на адрес». Опечатка
в одном символе проходит такую проверку насквозь: строка остаётся нужной длины и
из нужного алфавита. Крипта уходит на несуществующий адрес — безвозвратно, без
шанса на возврат. Контрольная сумма ровно для этого и придумана: она ловит
случайные искажения ДО отправки.

Почему без библиотек. relay-fastapi работает на системном /usr/bin/python3, где
нет ни base58, ни bitcoinlib, ни eth_hash (они есть только в venv бота). Общий
модуль обязан работать в обоих окружениях, поэтому всё реализовано на hashlib.

Что проверяем:
  * Base58Check (BTC/LTC legacy, TRON) — двойной SHA-256, 4 байта контрольной суммы;
  * Bech32 и Bech32m (BTC bc1…, LTC ltc1…) — BIP-173 / BIP-350;
  * EIP-55 (0x…) — регистровая контрольная сумма на Keccak-256.

Фейл-клоуз: всё, что не удалось разобрать, считается невалидным.
"""
from __future__ import annotations
import hashlib

# ─────────────────────────── Base58Check ───────────────────────────

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def b58check_decode(address: str):
    """payload (версия+хеш) или None, если строка не Base58Check с верной суммой."""
    if not address or not isinstance(address, str):
        return None
    num = 0
    for ch in address:
        idx = _B58_INDEX.get(ch)
        if idx is None:
            return None                      # символ вне алфавита Base58
        num = num * 58 + idx
    # Ведущие '1' в Base58 кодируют ведущие нулевые байты
    pad = len(address) - len(address.lstrip("1"))
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    full = b"\x00" * pad + body
    if len(full) < 5:
        return None
    payload, checksum = full[:-4], full[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        return None
    return payload


# ─────────────────────────── Bech32 / Bech32m ───────────────────────────

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2BC830A3


def _bech32_polymod(values):
    gen = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)
    chk = 1
    for v in values:
        top = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if (top >> i) & 1:
                chk ^= gen[i]
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def bech32_decode(address: str):
    """(hrp, data5bit, spec) где spec — 'bech32' | 'bech32m'; иначе (None, None, None)."""
    if not address or not isinstance(address, str):
        return (None, None, None)
    # Смешанный регистр запрещён спецификацией (иначе контрольная сумма неоднозначна)
    if address.lower() != address and address.upper() != address:
        return (None, None, None)
    s = address.lower()
    if len(s) < 8 or len(s) > 90:
        return (None, None, None)
    pos = s.rfind("1")
    if pos < 1 or pos + 7 > len(s):
        return (None, None, None)
    hrp = s[:pos]
    if any(ord(c) < 33 or ord(c) > 126 for c in hrp):
        return (None, None, None)
    data = []
    for c in s[pos + 1:]:
        idx = _BECH32_CHARSET.find(c)
        if idx < 0:
            return (None, None, None)
        data.append(idx)
    const = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if const == _BECH32_CONST:
        spec = "bech32"
    elif const == _BECH32M_CONST:
        spec = "bech32m"
    else:
        return (None, None, None)
    return (hrp, data[:-6], spec)


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def segwit_decode(hrp_expected: str, address: str):
    """(версия свидетеля, программа) для валидного segwit-адреса, иначе (None, None).

    Проверяется связка версия↔кодировка (BIP-350): версия 0 — только bech32,
    версии 1..16 — только bech32m. Именно эта связка отличает валидный taproot
    от адреса, собранного по старым правилам.
    """
    hrp, data, spec = bech32_decode(address)
    if hrp is None or hrp != hrp_expected or not data:
        return (None, None)
    ver = data[0]
    if ver > 16:
        return (None, None)
    prog = _convertbits(data[1:], 5, 8, False)
    if prog is None or len(prog) < 2 or len(prog) > 40:
        return (None, None)
    if ver == 0:
        if len(prog) not in (20, 32) or spec != "bech32":
            return (None, None)
    elif spec != "bech32m":
        return (None, None)
    return (ver, bytes(prog))


# ─────────────────────────── Keccak-256 (для EIP-55) ───────────────────────────
# hashlib.sha3_256 НЕ подходит: SHA-3 использует другое дополнение (0x06 против
# 0x01 у оригинального Keccak), результат отличается. Ethereum использует именно
# исходный Keccak, поэтому перманентность — своя реализация Keccak-f[1600].

_KECCAK_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_KECCAK_ROTATIONS = (
    (0, 36, 3, 41, 18), (1, 44, 10, 45, 2), (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56), (27, 20, 39, 8, 14),
)
_MASK64 = (1 << 64) - 1


def _rotl64(x, n):
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _MASK64


def _keccak_f1600(state):
    for rnd in range(24):
        # θ
        c = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= d[x]
        # ρ и π
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rotl64(state[x][y], _KECCAK_ROTATIONS[x][y])
        # χ
        for x in range(5):
            for y in range(5):
                state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y] & _MASK64) & b[(x + 2) % 5][y])
        # ι
        state[0][0] ^= _KECCAK_ROUND_CONSTANTS[rnd]
    return state


def keccak256(data: bytes) -> bytes:
    """Оригинальный Keccak-256 (тот, что использует Ethereum), не SHA3-256."""
    rate = 136  # 1088 бит для 256-битного варианта
    state = [[0] * 5 for _ in range(5)]
    padded = bytearray(data)
    padded.append(0x01)                       # дополнение исходного Keccak
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80
    for off in range(0, len(padded), rate):
        block = padded[off:off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:(i + 1) * 8], "little")
            state[i % 5][i // 5] ^= lane
        _keccak_f1600(state)
    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            if len(out) >= 32:
                break
            out += state[i % 5][i // 5].to_bytes(8, "little")
    return bytes(out[:32])


def eip55_checksum(address_hex_lower: str) -> str:
    """Адрес в каноничном регистре EIP-55 (вход — 40 hex-символов без 0x)."""
    digest = keccak256(address_hex_lower.encode("ascii")).hex()
    return "".join(
        ch.upper() if ch.isalpha() and int(digest[i], 16) >= 8 else ch
        for i, ch in enumerate(address_hex_lower)
    )


def evm_requires_eip55() -> bool:
    """Требовать ли контрольную сумму EIP-55 у всех 0x-адресов.

    По умолчанию ДА. Причина: адрес в одном регистре контрольной суммы не несёт
    вовсе, и опечатка в нём (замена hex-символа на hex-символ) неотличима от
    настоящего адреса — то есть именно тот сценарий потери средств, ради
    которого вся эта проверка и делается. Все современные кошельки показывают
    адрес уже в форме EIP-55, поэтому требование не мешает обычному копированию.

    EVM_REQUIRE_EIP55=0 ослабляет проверку (принимать адреса в одном регистре),
    если у клиентов найдётся источник, отдающий их без контрольной суммы.
    """
    import os
    return os.getenv("EVM_REQUIRE_EIP55", "1").strip().lower() not in ("0", "false", "no", "off")


def is_valid_evm_address(address: str, require_checksum=None) -> bool:
    """0x-адрес: длина/алфавит + контрольная сумма EIP-55.

    Смешанный регистр ВСЕГДА обязан совпасть с канонической формой. Адрес в
    едином регистре формально допустим по EIP-55, но защиты не даёт — по
    умолчанию отклоняем (см. evm_requires_eip55).
    """
    if not address or not isinstance(address, str):
        return False
    if len(address) != 42 or not address.startswith("0x"):
        return False
    body = address[2:]
    try:
        int(body, 16)
    except ValueError:
        return False
    single_case = body == body.lower() or body == body.upper()
    if single_case:
        strict = evm_requires_eip55() if require_checksum is None else bool(require_checksum)
        # Адрес из одних цифр контрольную сумму не несёт физически (нет букв,
        # чей регистр её кодирует) — такой принимаем независимо от строгости.
        if strict and any(ch.isalpha() for ch in body):
            return False
        return True
    return body == eip55_checksum(body.lower())


# ─────────────────────────── Публичные проверки по валютам ───────────────────────────

# Версии Base58Check. LTC: 0x30 → «L…», 0x32 → «M…». Легаси «3…» (0x05) у LTC
# сознательно НЕ принимаем — оно неотличимо от BTC P2SH и путает клиентов.
_BTC_VERSIONS = {0x00, 0x05}
_LTC_VERSIONS = {0x30, 0x32}
_TRON_VERSION = 0x41


def _b58_ok(address, versions):
    payload = b58check_decode(address)
    return bool(payload) and len(payload) == 21 and payload[0] in versions


def is_valid_btc(address: str) -> bool:
    if not address or not isinstance(address, str):
        return False
    if address.lower().startswith("bc1"):
        ver, _ = segwit_decode("bc", address)
        return ver is not None
    return _b58_ok(address, _BTC_VERSIONS)


def is_valid_ltc(address: str) -> bool:
    if not address or not isinstance(address, str):
        return False
    if address.lower().startswith("ltc1"):
        ver, _ = segwit_decode("ltc", address)
        return ver is not None
    return _b58_ok(address, _LTC_VERSIONS)


def is_valid_tron(address: str) -> bool:
    if not address or not isinstance(address, str) or not address.startswith("T"):
        return False
    return _b58_ok(address, {_TRON_VERSION})
