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

import base64
import re
import hashlib

# ─────────────────────────── Base58Check ───────────────────────────

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58check_decode_with(address: str, alphabet: str, index: dict):
    """Общий Base58Check, параметризованный алфавитом.

    Алфавит — часть защиты, а не косметика: у XRPL он свой, и биткойновый адрес
    в нём не разберётся (как и наоборот). Перепутать сети на этом шаге нельзя.
    """
    if not address or not isinstance(address, str):
        return None
    num = 0
    for ch in address:
        idx = index.get(ch)
        if idx is None:
            return None                      # символ вне алфавита
        num = num * 58 + idx
    # Ведущий символ алфавита кодирует ведущие нулевые байты ('1' у BTC, 'r' у XRPL)
    zero = alphabet[0]
    pad = len(address) - len(address.lstrip(zero))
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    full = b"\x00" * pad + body
    if len(full) < 5:
        return None
    payload, checksum = full[:-4], full[-4:]
    if hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != checksum:
        return None
    return payload


def _b58check_encode_with(payload: bytes, alphabet: str) -> str:
    """Обратная операция — нужна, чтобы вернуть classic-адрес из X-адреса."""
    full = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    num = int.from_bytes(full, "big")
    out = ""
    while num > 0:
        num, rem = divmod(num, 58)
        out = alphabet[rem] + out
    pad = len(full) - len(full.lstrip(b"\x00"))
    return alphabet[0] * pad + out


def b58check_decode(address: str):
    """payload (версия+хеш) или None, если строка не Base58Check с верной суммой."""
    return _b58check_decode_with(address, _B58_ALPHABET, _B58_INDEX)


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


# ─────────────────────────── XRP Ledger ───────────────────────────
#
# Две формы адреса, и обе ходят живьём:
#   classic  r…  — 20-байтный AccountID, версия 0x00;
#   X-адрес  X…  — тот же AccountID ПЛЮС destination tag внутри самой строки.
#
# Тег критичен: перевод на биржу без него зачисляется «в никуда» и деньги
# клиента не возвращаются. Поэтому X-адрес разбираем здесь, а не полагаемся на
# то, что тег доедет отдельным полем через все три поверхности.
#
# Реализация на stdlib намеренно: assets.py импортируется всеми и не должен
# зависеть от библиотеки xrpl. Если её нет в окружении, валидация обязана
# работать всё равно — иначе «нет библиотеки» тихо превратится в «адрес
# невалиден» на живом клиенте.

_XRPL_ALPHABET = "rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"
_XRPL_INDEX = {c: i for i, c in enumerate(_XRPL_ALPHABET)}

_XRPL_ACCOUNT_VERSION = 0x00
_XRPL_X_PREFIX_MAIN = b"\x05\x44"
_XRPL_X_PREFIX_TEST = b"\x04\x93"


def _xrpl_decode(address: str):
    return _b58check_decode_with(address, _XRPL_ALPHABET, _XRPL_INDEX)


def is_valid_xrp_classic(address: str) -> bool:
    """Classic-адрес r… с верной контрольной суммой."""
    if not address or not isinstance(address, str) or not address.startswith("r"):
        return False
    payload = _xrpl_decode(address)
    return bool(payload) and len(payload) == 21 and payload[0] == _XRPL_ACCOUNT_VERSION


def parse_xrp_destination(address: str):
    """(classic_address, destination_tag) или (None, None).

    Принимает обе формы. Для classic тег всегда None — его задаёт клиент
    отдельно. Для X-адреса тег берётся ИЗ адреса и подменить его нельзя.

    Тег 0 — валидное значение и обязан отличаться от «тега нет»: часть бирж
    использует именно 0. Поэтому возвращаем int 0, а не None.
    """
    if not address or not isinstance(address, str):
        return (None, None)
    addr = address.strip()

    if addr.startswith("r"):
        return (addr, None) if is_valid_xrp_classic(addr) else (None, None)

    if not addr.startswith("X"):
        return (None, None)

    payload = _xrpl_decode(addr)
    # префикс(2) + AccountID(20) + флаг тега(1) + тег(8, little-endian)
    if not payload or len(payload) != 31:
        return (None, None)
    if payload[:2] != _XRPL_X_PREFIX_MAIN:
        return (None, None)          # testnet и неизвестные префиксы — отказ

    flag = payload[22]
    raw_tag = payload[23:31]
    if flag == 0:
        if raw_tag != b"\x00" * 8:
            return (None, None)      # «тега нет», а байты не пусты — мусор
        tag = None
    elif flag == 1:
        if raw_tag[4:] != b"\x00" * 4:
            return (None, None)      # тег объявлен 32-битным, а старшие байты заняты
        tag = int.from_bytes(raw_tag[:4], "little")
    else:
        return (None, None)          # 64-битные теги в XRPL не используются

    classic = _b58check_encode_with(
        bytes([_XRPL_ACCOUNT_VERSION]) + payload[2:22], _XRPL_ALPHABET)
    return (classic, tag)


def is_valid_xrp(address: str) -> bool:
    """Адрес XRP в любой из двух форм."""
    classic, _tag = parse_xrp_destination(address)
    return classic is not None


def is_valid_xrp_tag(tag) -> bool:
    """Destination tag: целое 0..2^32-1. Дробное и строковое НЕ приводим молча —
    1.9 стало бы тегом 1, то есть чужим счётом на бирже."""
    if tag is None:
        return True                  # тег необязателен
    if isinstance(tag, bool) or not isinstance(tag, int):
        return False
    return 0 <= tag <= 0xFFFFFFFF


def xrp_xaddress(classic: str, tag=None):
    """(classic, tag) → X-адрес. None, если адрес или тег некорректны."""
    if not is_valid_xrp_classic(classic) or not is_valid_xrp_tag(tag):
        return None
    payload = _xrpl_decode(classic)
    if not payload or len(payload) != 21:
        return None
    if tag is None:
        flag, raw_tag = 0, b"\x00" * 8
    else:
        flag, raw_tag = 1, int(tag).to_bytes(4, "little") + b"\x00" * 4
    return _b58check_encode_with(
        _XRPL_X_PREFIX_MAIN + payload[1:] + bytes([flag]) + raw_tag, _XRPL_ALPHABET)


def canonical_xrp_destination(address, tag=None):
    """Одна строка, в которой адрес и тег НЕРАЗДЕЛИМЫ. None — если что-то не так.

    Зачем именно так. Тег хранится не отдельной колонкой, а внутри адреса
    (X-формат). Отдельное поле пришлось бы протаскивать через все восемь мест
    создания заявки, обе панели выдачи и уведомления — и любое место, где его
    забыли бы, отправило бы XRP на биржу БЕЗ тега. Это не ошибка с сообщением:
    перевод подтверждается сетью, деньги попадают на общий счёт биржи и
    получателю не зачисляются. X-адрес делает такую потерю невозможной
    физически: тег едет вместе с адресом по любому пути, а `xrp_wallet.send`
    достаёт его из адреса сам.

    Тег без адреса-носителя (classic + tag) кодируется в X-адрес.
    Конфликт (X-адрес несёт один тег, а передан другой) → отказ: молча выбрать
    один из двух значило бы отправить деньги туда, куда клиент не просил.
    """
    classic, addr_tag = parse_xrp_destination(address)
    if classic is None:
        return None
    if not is_valid_xrp_tag(tag):
        return None
    if addr_tag is not None and tag is not None and addr_tag != tag:
        return None
    final_tag = addr_tag if addr_tag is not None else tag
    return classic if final_tag is None else xrp_xaddress(classic, final_tag)


def account_key(address, currency=None) -> str:
    """Идентичность СЧЁТА из строки адреса — для сравнений в стражах.

    Один и тот же счёт записывается по-разному, и сравнение строк это не
    ловит. Уже стоило нам двух дефектов:
      • чёрный список — заблокированный по X-адресу счёт XRPL проходил в
        classic-форме (30.07.2026);
      • `payout_circuit` считает повторы выплат на один адрес за сутки, а у
        XRPL один счёт с разными тегами даёт разные строки — лимит
        `PAYOUT_ADDR_REPEAT_MAX` не срабатывал бы вовсе.
    Оба места теперь спрашивают здесь.

    XRP — classic-адрес без тега: тег адресует получателя ВНУТРИ счёта, а для
    «сколько раз этот счёт получал» и «заблокирован ли он» важен сам счёт.
    EVM — нижний регистр (EIP-55 отличается только регистром букв).
    Остальное возвращается как есть: у BTC/LTC регистр значащий, и «нормализация»
    сломала бы сравнение вместо того, чтобы его починить.
    """
    s = str(address or "").strip()
    if not s:
        return ""
    cur = str(currency or "").upper()
    if cur == "XRP" or s[:1] in ("r", "X"):
        classic, _tag = parse_xrp_destination(s)
        if classic:
            return classic
        return s
    if cur in ("ETH", "BNB", "MATIC") or (s[:2].lower() == "0x" and len(s) == 42):
        return s.lower()
    return s


# ─────────────────────────────────────────────────────────────────
# TON (The Open Network)
# ─────────────────────────────────────────────────────────────────
# У адреса TON две формы, и обе встречаются у клиентов:
#   • «дружественная» — 48 символов base64url, внутри 36 байт:
#       флаг(1) + workchain(1) + hash(32) + CRC16-CCITT(2);
#   • «сырая» — `workchain:hex64`, например `0:83df…31a8`, без контрольной суммы.
# Проверять надо ровно контрольную сумму: опечатка в одном символе сохраняет и
# длину, и алфавит, а адрес превращается в несуществующий — монеты уходят
# безвозвратно. Именно так проверка спасла TRON-адрес на реальных данных.
_TON_B64_RE = re.compile(r"^[A-Za-z0-9+/_-]{48}$")
_TON_RAW_RE = re.compile(r"^(-?\d+):([0-9a-fA-F]{64})$")


def _crc16_xmodem(data: bytes) -> int:
    """CRC16-CCITT (XMODEM): полином 0x1021, начальное 0. Именно им TON
    подписывает адрес — не путать с другими вариантами CRC16, дающими иное
    значение на тех же данных."""
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def parse_ton_address(address: str):
    """(workchain, hash-32-байта) или (None, None). Понимает обе формы.

    Фейл-клоуз: любая неувязка — длина, алфавит, контрольная сумма, чужой
    workchain — это отказ, а не «наверное сойдёт».
    """
    if not address or not isinstance(address, str):
        return (None, None)
    addr = address.strip()

    m = _TON_RAW_RE.match(addr)
    if m:
        wc = int(m.group(1))
        # В TON рабочие цепочки 0 (basechain) и -1 (masterchain). Остальные не
        # существуют, и адрес с ними — опечатка либо чужая сеть.
        if wc not in (0, -1):
            return (None, None)
        return (wc, bytes.fromhex(m.group(2)))

    if not _TON_B64_RE.match(addr):
        return (None, None)
    try:
        raw = base64.urlsafe_b64decode(addr.replace("+", "-").replace("/", "_") + "=")
    except Exception:
        return (None, None)
    if len(raw) != 36:
        return (None, None)
    if _crc16_xmodem(raw[:34]) != int.from_bytes(raw[34:], "big"):
        return (None, None)
    # Байт флагов: 0x11 bounceable, 0x51 non-bounceable; +0x80 = testnet.
    flags = raw[0]
    if flags & 0x80:
        return (None, None)          # testnet-адрес в проде — не наш случай
    if flags & ~0x80 not in (0x11, 0x51):
        return (None, None)
    wc = raw[1] if raw[1] < 0x80 else raw[1] - 0x100
    if wc not in (0, -1):
        return (None, None)
    return (wc, raw[2:34])


def is_valid_ton(address: str) -> bool:
    """Адрес TON в любой из двух форм, с проверкой контрольной суммы."""
    wc, _h = parse_ton_address(address)
    return wc is not None


def is_valid_ton_memo(memo) -> bool:
    """Комментарий (memo) к переводу TON.

    У TON это не число, как destination tag у XRP, а произвольный текст — но
    биржи используют его как идентификатор счёта, и промах здесь стоит тех же
    денег. Пустой memo допустим (личный кошелёк), слишком длинный — нет: в одну
    ячейку TON влезает 127 байт, длиннее придётся дробить, и биржа такой
    комментарий не разберёт.
    """
    if memo is None or memo == "":
        return True
    if not isinstance(memo, str):
        return False
    if "\n" in memo or "\r" in memo:
        return False                 # перевод строки ломает разбор на стороне биржи
    return len(memo.encode("utf-8")) <= 127


# ─────────────────────────────────────────────────────────────────────
# Диспетчер по валюте: адрес + тег как одна неразделимая строка
# ─────────────────────────────────────────────────────────────────────
# Монет с «тегом» стало больше одной, и это сразу вскрыло цену прежней
# конструкции: `assets.canonical_address` и `_split_destination` в боте вели
# ЛЮБУЮ валюту из TAGGED_CURRENCIES в `parse_xrp_destination`. Пока такая
# валюта была одна, всё сходилось. Стоило завести TON — и его адрес перестал
# разбираться везде: заявку не создать, а работнику в панели выдачи вместо
# реквизитов показалось бы «адрес не разобран».
#
# Ошибка тут не в TON, а в форме: общий список валют обслуживался частным
# разборщиком. Поэтому вход теперь один, а ветвление — внутри него, рядом с
# самими разборщиками. Добавляя монету с тегом, её правят в ОДНОМ месте.
#
# Склейка у TON — 'адрес#memo'. Разделитель однозначен: в дружественной форме
# адреса допустимы только буквы, цифры, '-', '_', в сырой — 'workchain:hex'.

def canonical_ton_destination(address, memo=None):
    """Адрес TON и memo одной строкой. None — если что-то не так.

    Memo у TON текстовый, а не числовой, и в отличие от XRP в самом адресе не
    живёт: если клиент прислал 'адрес#memo', это наша же склейка, вернувшаяся
    с прошлого круга. Конфликт двух разных memo — отказ, как и у XRP: выбрать
    один молча значит отправить деньги не туда, куда просил клиент.
    """
    addr, addr_memo = parse_ton_destination(address)
    if addr is None:
        return None
    if memo is not None and not is_valid_ton_memo(memo):
        return None
    if addr_memo is not None and memo is not None and addr_memo != memo:
        return None
    final = addr_memo if addr_memo is not None else memo
    return addr if final is None else f"{addr}#{final}"


def parse_ton_destination(address):
    """'адрес#memo' → (адрес, memo). (None, None), если адрес невалиден."""
    if not address or not isinstance(address, str):
        return (None, None)
    s = address.strip()
    memo = None
    if "#" in s:
        s, _, memo = s.partition("#")
        s, memo = s.strip(), memo.strip()
        if not is_valid_ton_memo(memo):
            return (None, None)
    if not is_valid_ton(s):
        return (None, None)
    return (s, memo)


def parse_destination(address, currency):
    """(адрес, тег) для валюты с тегом. (None, None) — разобрать не удалось.

    Валюта без тегов сюда попадать не должна: у неё адрес и есть адрес.
    """
    cur = str(currency or "").strip().upper()
    if cur == "XRP":
        return parse_xrp_destination(address)
    if cur == "TON":
        return parse_ton_destination(address)
    return (None, None)


def canonical_destination(address, tag, currency):
    """Единый вход: адрес + тег → одна строка для хранения. None при отказе."""
    cur = str(currency or "").strip().upper()
    if cur == "XRP":
        return canonical_xrp_destination(address, tag)
    if cur == "TON":
        return canonical_ton_destination(address, tag)
    return None


def is_valid_tag(tag, currency) -> bool:
    """Тег корректен для этой валюты. У XRP — число, у TON — текст."""
    cur = str(currency or "").strip().upper()
    if cur == "XRP":
        return is_valid_xrp_tag(tag)
    if cur == "TON":
        return tag is None or is_valid_ton_memo(tag)
    return False


def parse_tag_input(raw, currency):
    """Недоверенный ввод → тег ТОГО типа, который нужен этой валюте.

    Возвращает (значение, код ошибки). Пустой ввод — это (None, None): «клиент
    ничего не указал», а не «тега нет». Разница принципиальная: у биржевого
    адреса второе означает перевод на общий счёт биржи, который сеть подтвердит,
    а получателю не зачислит. Решение принимает поверхность — она одна знает,
    нажал ли клиент «у меня личный кошелёк».

    Отдельная функция нужна потому, что тип значения у валют РАЗНЫЙ: у XRP это
    целое, у TON — текст. Поверхности проверяли ввод через `.isdigit()`, и на
    TON это давало отказ «тег должен быть числом» на совершенно правильном
    memo — клиент не мог создать заявку вообще.

    Догадками ввод не чистим ни у одной валюты: «12 345» и «tag: 42» — отказ,
    а не тег 12345. Неверно распознанный тег отправляет деньги чужому.
    """
    cur = str(currency or "").strip().upper()
    s = "" if raw is None else str(raw).strip()
    if cur == "XRP":
        if isinstance(raw, bool):
            return (None, "bad_number")
        if isinstance(raw, int):
            return (raw, None) if is_valid_xrp_tag(raw) else (None, "bad_number")
        if s == "":
            return (None, None)
        if not s.isdigit() or int(s) > 0xFFFFFFFF:
            return (None, "bad_number")
        return (int(s), None)
    if cur == "TON":
        if s == "":
            return (None, None)
        return (s, None) if is_valid_ton_memo(s) else (None, "bad_text")
    return (None, None if s == "" else "not_tagged")
