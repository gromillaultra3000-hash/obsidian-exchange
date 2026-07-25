"""Горячий кошелёк EVM (ETH + ERC-20 USDT) для ObsidianExchange.

Секьюр-контур повторяет relay/wallet/tron_wallet.py (проверенный паттерн):
- приватный ключ шифруется ПАРОЛЕМ (PBKDF2-HMAC-SHA256, 390k → AES-GCM);
  в открытом виде на диске не лежит НИКОГДА;
- разлочка на сессию (ключ в памяти) с TTL 15 мин + lockout после 5 промахов;
- шифрованный бэкап + криптопроверка (расшифровать тем же паролем → тот же адрес);
- отправка ТОЛЬКО через two-step preview с истечением 120 с (fail-closed);
- идемпотентный журнал отправок: один логический перевод не уходит дважды;
- жёсткий потолок одной отправки (MAX_SEND, fail-closed);
- данные — в /root/wallet_data/secure (права 700), НЕ в git.

Подпись — через eth-account; RPC — чистый JSON-RPC (requests), без web3.py.
Сеть по умолчанию — Ethereum mainnet (chainId 1); адрес EVM один и тот же для
любых EVM-сетей, при желании EVM_CHAIN_ID/EVM_RPC_URLS переключают на L2.

⚠️ Отправка реализована, но подключение к авто-выплатам — отдельный gated-этап
(как было с BTC/LTC). Пароль нигде не хранится: чтобы разлочить/отправить, его
надо передать явно.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import secrets
import stat
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DATA = Path(os.getenv("WALLET_DATA_DIR", "/root/wallet_data"))
SECURE_DIR = DATA / "secure"
EVM_VAULT_PATH = SECURE_DIR / "evm-wallet-vault.json"
EVM_META_PATH = SECURE_DIR / "evm-wallet-meta.json"
EVM_BACKUP_PATH = DATA / "backups" / "obsidian-evm-wallet-backup.json"
EVM_HISTORY_PATH = DATA / "evm_wallet_history.jsonl"
EVM_SENDS_PATH = SECURE_DIR / "evm-sends.json"
EVM_PREVIEWS_PATH = SECURE_DIR / "evm-previews.json"
EVM_SENDLOCK_PATH = SECURE_DIR / "evm-send.lock"   # межпроцессный flock отправок
_AAD = b"OBSIDIAN-EVM-V1"

CHAIN_ID = int(os.getenv("EVM_CHAIN_ID", "1"))
NETWORK_ID = os.getenv("EVM_NETWORK_ID", "ethereum-mainnet")

# Публичные RPC mainnet. Порядок = приоритет; при сбое идём к следующему.
_DEFAULT_RPCS = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth.llamarpc.com",
    "https://rpc.ankr.com/eth",
    "https://cloudflare-eth.com",
)
EVM_RPC_URLS: List[str] = [u.strip() for u in os.getenv(
    "EVM_RPC_URLS", ",".join(_DEFAULT_RPCS)).split(",") if u.strip()]

# ERC-20 токены. USDT на mainnet — 6 знаков.
USDT_ERC20 = os.getenv("EVM_USDT_CONTRACT", "0xdAC17F958D2ee523a2206206994597C13D831ec7")
ERC20_TOKENS: Dict[str, Dict[str, Any]] = {
    "USDT": {"contract": USDT_ERC20, "decimals": 6},
}

MAX_SEND = {
    "ETH": float(os.getenv("WALLET_MAX_SEND_ETH", "100")),
    "USDT": float(os.getenv("WALLET_MAX_SEND_USDT", "100000")),
}

# Потолок цены газа (защита от абсурдного gasPrice из битого RPC). gwei.
MAX_GAS_PRICE_GWEI = float(os.getenv("EVM_MAX_GAS_PRICE_GWEI", "500"))
# Абсолютный потолок комиссии одной tx (gasLimit×gasPrice) в ETH — второй рубеж
# на случай, если RPC вернёт разумный gasPrice, но абсурдный gasLimit.
MAX_FEE_ETH = float(os.getenv("EVM_MAX_FEE_ETH", "0.05"))

_PREVIEWS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()
_UNLOCKED_KEY: Optional[str] = None
_UNLOCKED_ADDRESS: Optional[str] = None
_UNLOCKED_AT = 0.0
_FAILED_ATTEMPTS = 0
_LOCKOUT_UNTIL = 0.0
DEFAULT_TTL = 900


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except Exception:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 600
    except Exception:
        pass
    os.replace(tmp, path)


# ── шифрование ────────────────────────────────────────────────────────────────
@contextmanager
def _proc_lock():
    """Межпроцессный эксклюзивный лок (fcntl.flock) на время критической секции
    отправки. Защищает от двойной подписи, когда send() вызван из РАЗНЫХ процессов
    (потоковый _LOCK этого не ловит). Каталог/файл создаём под 700/600."""
    SECURE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(SECURE_DIR, 0o700)
    except Exception:
        pass
    f = open(EVM_SENDLOCK_PATH, "a+")
    try:
        os.chmod(EVM_SENDLOCK_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def _derive(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                      iterations=390000).derive(password.encode("utf-8"))


def _encrypt_secret(secret_hex: str, password: str) -> Dict[str, Any]:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive(password, salt)
    cipher = AESGCM(key).encrypt(nonce, secret_hex.encode("utf-8"), _AAD)
    return {
        "format": "OBSIDIAN_EVM_AESGCM_V1",
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": 390000,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(cipher).decode("ascii"),
    }


def _decrypt_secret(payload: Dict[str, Any], password: str) -> str:
    salt = base64.b64decode(payload["salt"])
    nonce = base64.b64decode(payload["nonce"])
    cipher = base64.b64decode(payload["ciphertext"])
    key = _derive(password, salt)
    return AESGCM(key).decrypt(nonce, cipher, _AAD).decode("utf-8")


# ── ключ/адрес ──────────────────────────────────────────────────────────────
def _account(key_hex: str):
    from eth_account import Account  # type: ignore
    return Account.from_key("0x" + key_hex if not key_hex.startswith("0x") else key_hex)


def _address_of(key_hex: str) -> str:
    return _account(key_hex).address


def _is_valid_address(address: str) -> bool:
    a = str(address)
    if not (a.startswith("0x") and len(a) == 42
            and all(c in "0123456789abcdefABCDEF" for c in a[2:])):
        return False
    body = a[2:]
    # all-lower / all-upper — checksum не задан, принимаем.
    if body == body.lower() or body == body.upper():
        return True
    # mixed-case → обязан быть валидным EIP-55, иначе это опечатка регистра
    # (is_address в текущей версии eth_utils её НЕ ловит — проверяем сами).
    try:
        from eth_utils import to_checksum_address  # type: ignore
        return to_checksum_address(a) == a
    except Exception:
        return False


def _checksum(address: str) -> str:
    try:
        from eth_utils import to_checksum_address  # type: ignore
        return to_checksum_address(str(address))
    except Exception:
        return str(address)


# ── JSON-RPC ────────────────────────────────────────────────────────────────
class RpcProtocolError(RuntimeError):
    """Ошибка уровня протокола (nonce too low, already known, underpriced, revert…)
    — сменой узла НЕ лечится и НЕ должна вызывать повтор на другом RPC."""


def _rpc(method: str, params: List[Any]) -> Any:
    """Один RPC-вызов с перебором узлов. Возвращает result или бросает.

    Протокольные ошибки (RpcProtocolError) пробрасываются СРАЗУ — иначе, например,
    'already known' на первом узле привёл бы к повторной попытке на втором."""
    last = None
    for url in EVM_RPC_URLS:
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1,
                                         "method": method, "params": params}, timeout=15)
            j = r.json()
            if "error" in j and j["error"]:
                msg = str(j["error"]).lower()
                if any(s in msg for s in ("nonce", "insufficient", "already known",
                                          "replacement", "underpriced", "revert",
                                          "known transaction")):
                    raise RpcProtocolError(f"rpc_error:{j['error']}")
                last = RuntimeError(f"rpc_error:{j['error']}")
                continue
            return j.get("result")
        except RpcProtocolError:
            raise
        except Exception as exc:
            last = exc
            continue
    raise ConnectionError(f"evm_rpc_unavailable:{type(last).__name__ if last else 'none'}")


_VERIFIED_CHAIN = {"ok": False}


def _verify_chain_id() -> None:
    """Одноразовая сверка chainId узла с ожидаемым (защита от отправки не в ту сеть
    из-за битой конфигурации RPC). Результат кешируется на процесс."""
    if _VERIFIED_CHAIN["ok"]:
        return
    got = _to_int(_rpc("eth_chainId", []))
    if got != CHAIN_ID:
        raise ValueError(f"evm_chain_id_mismatch: узел вернул {got}, ожидали {CHAIN_ID}")
    _VERIFIED_CHAIN["ok"] = True


def _to_int(hex_or_int: Any) -> int:
    if hex_or_int is None:
        return 0
    if isinstance(hex_or_int, int):
        return hex_or_int
    return int(str(hex_or_int), 16)


def _hex(n: int) -> str:
    return hex(int(n))


# ── создание / импорт ────────────────────────────────────────────────────────
def create_wallet(password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    if len(password) < 10:
        raise ValueError("wallet_password_too_short_min_10")
    with _LOCK:
        if EVM_VAULT_PATH.exists() and not overwrite:
            return {"ok": True, "alreadyExists": True, **status()}
        key_hex = os.urandom(32).hex()
        return _persist(key_hex, password, imported=False)


def import_wallet(private_key_hex: str, password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    if len(password) < 10:
        raise ValueError("wallet_password_too_short_min_10")
    key_hex = private_key_hex.strip().lower().removeprefix("0x")
    if len(key_hex) != 64 or any(c not in "0123456789abcdef" for c in key_hex):
        raise ValueError("invalid_private_key_hex")
    with _LOCK:
        if EVM_VAULT_PATH.exists() and not overwrite:
            raise FileExistsError("wallet_already_exists_use_overwrite")
        return _persist(key_hex, password, imported=True)


def _persist(key_hex: str, password: str, *, imported: bool) -> Dict[str, Any]:
    address = _address_of(key_hex)
    encrypted = _encrypt_secret(key_hex, password)
    encrypted["address"] = address
    encrypted["createdAt"] = _now()
    _atomic_write(EVM_VAULT_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2), secret=True)
    _atomic_write(EVM_BACKUP_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2), secret=True)
    # криптопроверка бэкапа: расшифровать тем же паролем и сверить адрес
    check_hex = _decrypt_secret(json.loads(EVM_BACKUP_PATH.read_text("utf-8")), password)
    backup_ok = _address_of(check_hex) == address
    _atomic_write(EVM_META_PATH, json.dumps({
        "address": address, "createdAt": _now(), "backupConfirmed": backup_ok,
        "imported": imported, "vaultPath": str(EVM_VAULT_PATH),
        "backupPath": str(EVM_BACKUP_PATH),
    }, ensure_ascii=False, indent=2))
    unlock(password)
    return {"ok": True, "address": address, "backupConfirmed": backup_ok,
            "imported": imported, "network": NETWORK_ID}


# ── разлочка ────────────────────────────────────────────────────────────────
def unlock(password: str) -> Dict[str, Any]:
    global _UNLOCKED_KEY, _UNLOCKED_ADDRESS, _UNLOCKED_AT, _FAILED_ATTEMPTS, _LOCKOUT_UNTIL
    with _LOCK:
        if time.time() < _LOCKOUT_UNTIL:
            raise PermissionError(f"evm_wallet_unlock_temporarily_locked:{int(_LOCKOUT_UNTIL - time.time())}s")
        if not EVM_VAULT_PATH.exists():
            raise FileNotFoundError("evm_wallet_not_created")
        try:
            key_hex = _decrypt_secret(json.loads(EVM_VAULT_PATH.read_text("utf-8")), password)
            address = _address_of(key_hex)
        except Exception:
            _FAILED_ATTEMPTS += 1
            if _FAILED_ATTEMPTS >= 5:
                _LOCKOUT_UNTIL = time.time() + 60
                _FAILED_ATTEMPTS = 0
            raise ValueError("invalid_wallet_password")
        _UNLOCKED_KEY = key_hex
        _UNLOCKED_ADDRESS = address
        _UNLOCKED_AT = time.time()
        _FAILED_ATTEMPTS = 0
        return {"ok": True, "address": address, "unlocked": True, "expiresInSec": DEFAULT_TTL}


def lock() -> Dict[str, Any]:
    global _UNLOCKED_KEY, _UNLOCKED_ADDRESS, _UNLOCKED_AT
    with _LOCK:
        _UNLOCKED_KEY = None
        _UNLOCKED_ADDRESS = None
        _UNLOCKED_AT = 0.0
    return {"ok": True, "unlocked": False}


def _expire() -> None:
    global _UNLOCKED_KEY, _UNLOCKED_ADDRESS, _UNLOCKED_AT
    if _UNLOCKED_KEY and time.time() - _UNLOCKED_AT >= DEFAULT_TTL:
        _UNLOCKED_KEY = None
        _UNLOCKED_ADDRESS = None
        _UNLOCKED_AT = 0.0


def address() -> str:
    _expire()
    if _UNLOCKED_ADDRESS:
        return _UNLOCKED_ADDRESS
    try:
        return str(json.loads(EVM_META_PATH.read_text("utf-8")).get("address") or "")
    except Exception:
        return ""


# ── баланс ──────────────────────────────────────────────────────────────────
def _eth_balance_wei(addr: str) -> int:
    return _to_int(_rpc("eth_getBalance", [addr, "latest"]))


def _erc20_balance_raw(addr: str, contract: str) -> int:
    # balanceOf(address) selector 0x70a08231 + 32-байтный адрес
    data = "0x70a08231" + addr.lower().removeprefix("0x").rjust(64, "0")
    res = _rpc("eth_call", [{"to": contract, "data": data}, "latest"])
    return _to_int(res)


def balance() -> Dict[str, Any]:
    addr = address()
    if not addr:
        return {"status": "BLOCKED", "reason": "evm_wallet_not_created",
                "balanceEth": 0.0, "tokens": []}
    try:
        wei = _eth_balance_wei(addr)
        eth = float(Decimal(wei) / Decimal(10 ** 18))
        tokens = []
        for symbol, cfg in ERC20_TOKENS.items():
            last_exc = None
            for attempt in range(3):
                try:
                    raw = _erc20_balance_raw(addr, cfg["contract"])
                    tokens.append({"symbol": symbol, "contract": cfg["contract"],
                                   "balance": float(Decimal(raw) / (Decimal(10) ** int(cfg["decimals"]))),
                                   "raw": str(raw), "decimals": int(cfg["decimals"])})
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        time.sleep(0.7 * (attempt + 1))
            else:
                tokens.append({"symbol": symbol, "contract": cfg["contract"],
                               "status": "ERROR", "error": f"{type(last_exc).__name__}"[:160]})
        return {"status": "OK", "address": addr, "balanceEth": eth,
                "balanceWei": str(wei), "tokens": tokens, "network": NETWORK_ID}
    except Exception as exc:
        return {"status": "WAIT", "address": addr, "balanceEth": 0.0, "tokens": [],
                "reason": f"{type(exc).__name__}"[:240]}


def status() -> Dict[str, Any]:
    _expire()
    meta: Dict[str, Any] = {}
    try:
        meta = json.loads(EVM_META_PATH.read_text("utf-8"))
    except Exception:
        pass
    return {
        "configured": EVM_VAULT_PATH.exists(),
        "address": address(),
        "unlocked": bool(_UNLOCKED_KEY),
        "signerState": "UNLOCKED" if _UNLOCKED_KEY else "LOCKED",
        "backupConfirmed": bool(meta.get("backupConfirmed")),
        "network": NETWORK_ID,
        "chainId": CHAIN_ID,
        "supportedAssets": ["ETH"] + sorted(ERC20_TOKENS.keys()),
        "unlockRemainingSec": max(0, int(DEFAULT_TTL - (time.time() - _UNLOCKED_AT))) if _UNLOCKED_KEY else 0,
    }


# ── история / идемпотентность ────────────────────────────────────────────────
def _append_history(row: Dict[str, Any]) -> None:
    EVM_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVM_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def history(limit: int = 100) -> Dict[str, Any]:
    rows = []
    try:
        for line in EVM_HISTORY_PATH.read_text("utf-8").splitlines()[-max(1, min(500, int(limit))):]:
            if line.strip():
                rows.append(json.loads(line))
    except Exception:
        pass
    return {"entries": rows, "count": len(rows)}


def _load_sends() -> Dict[str, Any]:
    """Идемпотентный журнал. Fail-CLOSED: отсутствие файла = пустой журнал (ок),
    но существующий, но НЕЧИТАЕМЫЙ/битый файл → бросаем. Иначе потеря/порча журнала
    после broadcast позволила бы повтору подписать новый nonce = двойная выплата."""
    if not EVM_SENDS_PATH.exists():
        return {}  # журнала ещё нет — легитимно пусто
    txt = EVM_SENDS_PATH.read_text("utf-8")  # ошибка чтения → пробрасываем (fail-closed)
    if txt.strip() == "":
        # СУЩЕСТВУЮЩИЙ, но пустой файл = обрезка/порча (валидный журнал пишется как
        # минимум "{}"). Не трактуем как пустой — иначе повтор подпишет новый nonce.
        raise RuntimeError("evm_sends_journal_corrupt:empty_file")
    try:
        data = json.loads(txt)
    except Exception as e:
        raise RuntimeError(f"evm_sends_journal_corrupt:{type(e).__name__}") from e
    if not isinstance(data, dict):
        raise RuntimeError("evm_sends_journal_corrupt:not_a_dict")
    return data


def _save_sends(obj: Dict[str, Any]) -> None:
    _atomic_write(EVM_SENDS_PATH, json.dumps(obj, ensure_ascii=False, indent=2), secret=True)


# ── газ ──────────────────────────────────────────────────────────────────────
def _gas_price_wei() -> int:
    gp = _to_int(_rpc("eth_gasPrice", []))
    cap = int(MAX_GAS_PRICE_GWEI * 1e9)
    if gp <= 0:
        raise ValueError("evm_gas_price_unavailable")
    if gp > cap:
        raise ValueError(f"evm_gas_price_too_high:{gp / 1e9:.1f}gwei>{MAX_GAS_PRICE_GWEI}gwei")
    return gp


def _check_fee_cap(fee_wei: int) -> None:
    cap_wei = int(MAX_FEE_ETH * 1e18)
    if fee_wei > cap_wei:
        raise ValueError(
            f"evm_fee_exceeds_cap: комиссия {fee_wei / 1e18:.6f} ETH > "
            f"потолок {MAX_FEE_ETH} ETH (EVM_MAX_FEE_ETH)")


def _estimate_gas(tx: Dict[str, Any], default: int, *, strict: bool) -> int:
    """Оценка газа. strict=True (ERC-20): revert → бросаем (fail-closed, tx обречена,
    комиссия сгорела бы впустую). Сетевой сбой оценки → default (не блокируем выплату).
    strict=False (ETH на EOA): 21000 гарантированно достаточно."""
    try:
        est = _to_int(_rpc("eth_estimateGas", [tx]))
        if est > 0:
            return int(est * 1.25)  # запас 25% на колебания
    except RpcProtocolError:
        # execution revert / insufficient funds — транзакция не пройдёт
        if strict:
            raise
    except Exception:
        pass  # сетевой сбой оценки — падаем на default
    return default


def _erc20_transfer_data(to_addr: str, raw_amount: int) -> str:
    # transfer(address,uint256) selector 0xa9059cbb
    return ("0xa9059cbb"
            + to_addr.lower().removeprefix("0x").rjust(64, "0")
            + format(int(raw_amount), "x").rjust(64, "0"))


# ── preview / send ───────────────────────────────────────────────────────────
def preview_send(asset: str, to_address: str, amount: float) -> Dict[str, Any]:
    _expire()
    if not _UNLOCKED_KEY:
        raise PermissionError("evm_signer_locked")
    if amount <= 0:
        raise ValueError("amount_must_be_positive")
    symbol = str(asset).upper().strip()
    if symbol != "ETH" and symbol not in ERC20_TOKENS:
        raise ValueError("asset_not_supported_on_evm")
    cap = MAX_SEND.get(symbol)
    if cap is not None and float(amount) > cap:
        raise ValueError(f"amount_exceeds_max_send_{symbol}:{cap}")
    if not _is_valid_address(str(to_address)):
        raise ValueError("invalid_evm_destination_address")

    _verify_chain_id()  # не отправить не в ту сеть из-за битой конфигурации RPC
    sender = address()
    to_cs = _checksum(str(to_address))
    bal = balance()
    if bal.get("status") != "OK":
        raise ValueError("evm_rpc_unavailable")
    eth_wei = int(bal.get("balanceWei") or 0)
    gas_price = _gas_price_wei()

    if symbol == "ETH":
        value_wei = int(Decimal(str(amount)) * (Decimal(10) ** 18))
        gas_limit = _estimate_gas(
            {"from": sender, "to": to_cs, "value": _hex(value_wei)}, 21000, strict=False)
        fee_wei = gas_limit * gas_price
        _check_fee_cap(fee_wei)
        if eth_wei < value_wei + fee_wei:
            raise ValueError(
                f"insufficient_eth: нужно {(value_wei + fee_wei) / 1e18:.6f}, "
                f"есть {eth_wei / 1e18:.6f} ETH (с комиссией)")
        fee_note = (f"Комиссия сети ≈ {fee_wei / 1e18:.6f} ETH "
                    f"(gas {gas_limit} × {gas_price / 1e9:.1f} gwei).")
    else:
        cfg = ERC20_TOKENS[symbol]
        raw_amount = int(Decimal(str(amount)) * (Decimal(10) ** int(cfg["decimals"])))
        token = next((t for t in bal.get("tokens", [])
                      if t.get("symbol") == symbol and "raw" in t), None)
        if not token or int(token.get("raw") or 0) < raw_amount:
            raise ValueError("insufficient_token_balance")
        data = _erc20_transfer_data(to_cs, raw_amount)
        # strict: если estimateGas реверта (напр. USDT paused/заблокирован адрес) —
        # fail-closed, иначе комиссия сгорела бы, а токены не ушли.
        gas_limit = _estimate_gas(
            {"from": sender, "to": cfg["contract"], "data": data}, 90000, strict=True)
        fee_wei = gas_limit * gas_price
        _check_fee_cap(fee_wei)
        if eth_wei < fee_wei:
            raise ValueError(
                f"insufficient_eth_for_gas: нужно ≈{fee_wei / 1e18:.6f} ETH на комиссию, "
                f"есть {eth_wei / 1e18:.6f}")
        fee_note = (f"Перевод ERC-20 {symbol}: комиссия ≈ {fee_wei / 1e18:.6f} ETH "
                    f"(gas {gas_limit} × {gas_price / 1e9:.1f} gwei).")

    preview_id = secrets.token_urlsafe(18)
    row = {
        "previewId": preview_id, "expiresAt": time.time() + 120, "expiresInSec": 120,
        "network": NETWORK_ID, "chainId": CHAIN_ID, "asset": symbol,
        "from": sender, "to": to_cs, "amount": float(amount),
        "gasPriceWei": str(gas_price), "gasLimit": gas_limit,
        "estimatedFeeEth": fee_wei / 1e18, "warning": fee_note, "createdAt": _now(),
    }
    _PREVIEWS[preview_id] = row
    # Персист под межпроцессным локом + read-modify-write общего файла: НЕ дампим
    # процесс-локальный _PREVIEWS (иначе другой процесс, потребивший preview, увидел
    # бы его «воскресшим», и его можно было бы применить второй раз = двойная выплата).
    try:
        with _proc_lock():
            data = {}
            if EVM_PREVIEWS_PATH.exists():
                try:
                    data = json.loads(EVM_PREVIEWS_PATH.read_text("utf-8")) or {}
                except Exception:
                    data = {}
            now = time.time()
            data = {k: v for k, v in data.items()
                    if isinstance(v, dict) and float(v.get("expiresAt") or 0) > now}
            data[preview_id] = row
            _atomic_write(EVM_PREVIEWS_PATH, json.dumps(data, ensure_ascii=False), secret=True)
    except Exception:
        pass
    return row


def _pop_preview_file(preview_id: str) -> None:
    try:
        with _LOCK:
            data = json.loads(EVM_PREVIEWS_PATH.read_text("utf-8"))
            if preview_id in data:
                data.pop(preview_id, None)
                _atomic_write(EVM_PREVIEWS_PATH, json.dumps(data, ensure_ascii=False), secret=True)
    except Exception:
        pass


def _tx_on_chain(tx_hash: str) -> Optional[Dict[str, Any]]:
    """Транзакция видна в сети (блок или мемпул)? receipt/pending или None."""
    if not tx_hash:
        return None
    try:
        rec = _rpc("eth_getTransactionReceipt", [tx_hash])
        if rec:
            return {"status": _to_int(rec.get("status"))}
    except Exception:
        pass
    try:
        tx = _rpc("eth_getTransactionByHash", [tx_hash])
        if tx:
            return {"status": None}  # в мемпуле, ещё не в блоке
    except Exception:
        pass
    return None


def _reconcile(prev: Dict[str, Any]) -> Dict[str, Any]:
    """Для ключа уже есть подписанная tx. Вернуть её актуальный статус, НЕ создавая
    новую транзакцию (защита от двойной выплаты). При необходимости — ре-broadcast
    ТОЙ ЖЕ подписанной raw (тот же nonce/hash → двойной отправки быть не может)."""
    tx_hash = prev.get("txHash")
    raw_tx = prev.get("rawTx")
    # терминальные статусы не требуют повторного обращения к сети
    if prev.get("status") == "CONFIRMED":
        return {**prev, "idempotent": True}
    if prev.get("status") == "FAILED":
        raise RuntimeError(f"evm_transaction_failed:{tx_hash}")
    onchain = _tx_on_chain(tx_hash) if tx_hash else None
    if onchain is not None:
        st = onchain.get("status")
        status = ("CONFIRMED" if st == 1 else
                  ("FAILED" if st == 0 else "SUBMITTED_UNCONFIRMED"))
        if status == "FAILED":
            raise RuntimeError(f"evm_transaction_failed:{tx_hash}")
        return {**prev, "status": status, "idempotent": True}
    if raw_tx:
        # tx не видно — ре-broadcast той же подписанной raw (идемпотентно по nonce/hash)
        try:
            _rpc("eth_sendRawTransaction", [raw_tx])
        except RpcProtocolError as e:
            m = str(e).lower()
            # benign: tx/nonce уже в сети. Иначе (underpriced/insufficient/revert) —
            # выдавать за «отправлено» НЕЛЬЗЯ: пусть уходит в ручной разбор.
            if not any(s in m for s in ("already known", "nonce too low", "known transaction")):
                raise RuntimeError(f"evm_rebroadcast_failed:{e}")
        except Exception:
            pass  # сетевой сбой — статус остаётся неопределённым (не «успех»)
        return {**prev, "status": "SUBMITTED_UNCONFIRMED", "idempotent": True, "rebroadcast": True}
    # записи без rawTx/txHash быть не должно (клейм 'signing' обрабатывается выше)
    raise PermissionError("send_ambiguous_prior_attempt_manual_review")


def send(asset: str, to_address: str, amount: float, preview_id: str = "",
         idempotency_key: str = "") -> Dict[str, Any]:
    _expire()
    if not _UNLOCKED_KEY:
        raise PermissionError("evm_signer_locked")
    if amount <= 0:
        raise ValueError("amount_must_be_positive")
    # idempotency_key ОБЯЗАТЕЛЕН: без него подписанная raw не журналируется и
    # сетевой таймаут после broadcast + повтор дали бы вторую tx с новым nonce
    # (двойная выплата). Требуем непустой ключ — все авто-выплаты его передают.
    if not idempotency_key:
        raise ValueError("idempotency_key_required")
    symbol = str(asset).upper().strip()
    cap = MAX_SEND.get(symbol)
    if cap is not None and float(amount) > cap:
        raise ValueError(f"amount_exceeds_max_send_{symbol}:{cap}")

    # быстрый короткозамыкатель повтора уже подписанной выплаты — реконсиляция той
    # же tx (без требования свежего preview). Авторитетный claim — ниже под flock.
    with _LOCK:
        prev = _load_sends().get(idempotency_key)
    if prev and (prev.get("txHash") or prev.get("rawTx")):
        return _reconcile(prev)
    if prev and prev.get("status") == "signing":
        raise PermissionError("send_in_progress_for_key")

    to_cs = _checksum(str(to_address))

    # ── КРИТИЧЕСКАЯ СЕКЦИЯ под межпроцессным flock ────────────────────────────
    # Потребление preview → claim → nonce → подпись → журнал → broadcast — всё под
    # ОС-блокировкой, чтобы два процесса (не только потока) не забрали один preview
    # и не подписали две tx с разными nonce = двойная выплата. Broadcast внутри
    # секции: nonce попадает в мемпул до её освобождения, следующий процесс возьмёт
    # nonce+1. Долгое ожидание receipt — вне секции.
    with _proc_lock():
        # потребление preview — атомарно под тем же локом, что и подпись. Источник
        # истины — ФАЙЛ (не процесс-локальный _PREVIEWS): если другой процесс уже
        # потребил preview из файла, устаревшая копия в памяти не должна разрешить
        # вторую отправку.
        try:
            preview = json.loads(EVM_PREVIEWS_PATH.read_text("utf-8")).get(preview_id or "")
        except Exception:
            preview = None
        if not preview:
            raise PermissionError("fresh_transfer_preview_required")
        if time.time() > float(preview.get("expiresAt") or 0):
            _PREVIEWS.pop(preview_id, None)
            _pop_preview_file(preview_id)
            raise PermissionError("transfer_preview_expired")
        if (str(preview.get("to")) != to_cs or str(preview.get("asset")) != symbol
                or abs(float(preview.get("amount") or 0) - float(amount)) > 1e-12):
            raise PermissionError("transfer_preview_mismatch")
        # НАДЁЖНОЕ потребление preview: удаляем из файла и подтверждаем запись. Если
        # запись не удалась — НЕ подписываем (иначе preview остался бы переиспользуемым
        # с другим idempotency_key = двойная выплата). Мы под _proc_lock — RMW атомарен.
        try:
            _pdata = {}
            if EVM_PREVIEWS_PATH.exists():
                _pdata = json.loads(EVM_PREVIEWS_PATH.read_text("utf-8")) or {}
            _pdata.pop(preview_id, None)
            _atomic_write(EVM_PREVIEWS_PATH, json.dumps(_pdata, ensure_ascii=False), secret=True)
        except Exception as _e:
            raise RuntimeError(f"preview_consume_failed:{type(_e).__name__}")
        _PREVIEWS.pop(preview_id, None)

        with _LOCK:
            sends = _load_sends()
            prev = sends.get(idempotency_key)
            if prev and (prev.get("txHash") or prev.get("rawTx")):
                consumed = True
            elif prev and prev.get("status") == "signing":
                raise PermissionError("send_in_progress_for_key")
            else:
                consumed = False
                sends[idempotency_key] = {"status": "signing", "asset": symbol,
                                          "to": to_cs, "amount": float(amount),
                                          "startedAt": _now()}
                _save_sends(sends)
        if consumed:
            return _reconcile(prev)

        sender = address()
        gas_price = int(preview.get("gasPriceWei") or 0) or _gas_price_wei()
        gas_limit = int(preview.get("gasLimit") or 0) or 21000
        nonce = _to_int(_rpc("eth_getTransactionCount", [sender, "pending"]))

        if symbol == "ETH":
            value_wei = int(Decimal(str(amount)) * (Decimal(10) ** 18))
            tx = {"nonce": nonce, "gasPrice": gas_price, "gas": gas_limit,
                  "to": to_cs, "value": value_wei, "chainId": CHAIN_ID}
        else:
            cfg = ERC20_TOKENS[symbol]
            raw_amount = int(Decimal(str(amount)) * (Decimal(10) ** int(cfg["decimals"])))
            tx = {"nonce": nonce, "gasPrice": gas_price, "gas": gas_limit,
                  "to": _checksum(cfg["contract"]), "value": 0, "chainId": CHAIN_ID,
                  "data": _erc20_transfer_data(to_cs, raw_amount)}

        from eth_account import Account  # type: ignore
        signed = Account.sign_transaction(tx, _UNLOCKED_KEY)
        raw = signed.raw_transaction if hasattr(signed, "raw_transaction") else signed.rawTransaction
        raw_hex = "0x" + raw.hex().removeprefix("0x")
        # Хеш EVM-tx детерминирован (keccak от подписанной raw). Знаем его ДО
        # broadcast — фиксируем в журнале ВМЕСТЕ с raw ПЕРЕД отправкой: повтор
        # реконсилит/ре-broadcastит ЭТУ ЖЕ tx (тот же nonce/hash), новую не подписываем.
        predicted_hash = "0x" + signed.hash.hex().removeprefix("0x")
        base = {
            "network": NETWORK_ID, "chainId": CHAIN_ID, "asset": symbol, "from": sender,
            "to": to_cs, "amount": float(amount), "txHash": predicted_hash, "rawTx": raw_hex,
            "nonce": nonce, "gasPriceWei": str(gas_price), "gasLimit": gas_limit,
        }
        with _LOCK:
            sends = _load_sends()
            sends[idempotency_key] = {**base, "status": "signed", "startedAt": _now(),
                                      "idempotencyKey": idempotency_key}
            _save_sends(sends)

        try:
            tx_hash = str(_rpc("eth_sendRawTransaction", [raw_hex]))
        except RpcProtocolError as e:
            m = str(e).lower()
            # benign: tx/nonce уже в сети — работаем с предсказанным хешем.
            # НЕ benign (underpriced/insufficient/revert) — tx НЕ принята: бросаем,
            # запись с rawTx остаётся, повтор реконсилит (не выдаём за отправленное).
            if any(s in m for s in ("already known", "nonce too low", "known transaction")):
                tx_hash = predicted_hash
            else:
                raise
        except Exception:
            # СЕТЕВОЙ сбой broadcast: tx могла уйти в мемпул. Запись НЕ трогаем (в ней
            # rawTx+hash) — повтор с тем же ключом реконсилит/ре-broadcastит ту же tx.
            raise
    # ── конец критической секции (flock отпущен) ─────────────────────────────

    # ждём receipt (до ~120 c); отсутствие receipt ≠ провал — tx в мемпуле
    receipt = None
    for _ in range(40):
        try:
            receipt = _rpc("eth_getTransactionReceipt", [tx_hash])
        except Exception:
            receipt = None
        if receipt:
            break
        time.sleep(3)
    rec_status = _to_int(receipt.get("status")) if receipt is not None else None

    row = {**base, "txHash": tx_hash,
           "status": ("CONFIRMED" if rec_status == 1 else
                      ("FAILED" if rec_status == 0 else "SUBMITTED_UNCONFIRMED")),
           "timestamp": _now()}
    _append_history({k: v for k, v in row.items() if k != "rawTx"})
    # финальное обновление журнала — под тем же межпроцессным локом (RMW свежего
    # журнала), иначе параллельный процесс мог бы потерять запись другой отправки.
    with _proc_lock():
        with _LOCK:
            sends = _load_sends()
            sends[idempotency_key] = {**row, "idempotencyKey": idempotency_key}
            _save_sends(sends)
    if row["status"] == "FAILED":
        raise RuntimeError(f"evm_transaction_failed:{tx_hash}")
    return row
