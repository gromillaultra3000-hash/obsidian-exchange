"""Горячий кошелёк TRON (TRX + USDT-TRC20) для ObsidianExchange.

Перенос из Kairos v20.4.2 app/tron_wallet.py (проверенный код) с адаптацией под
обменник:
- приватный ключ шифруется ПАРОЛЕМ (PBKDF2-HMAC-SHA256, 390k итераций → AES-GCM);
  в открытом виде ключ на диске не лежит НИКОГДА;
- разлочка на сессию (ключ в памяти) с TTL 15 мин + lockout после 5 неверных попыток;
- шифрованный бэкап + криптопроверка (бэкап расшифровывается тем же паролем и даёт
  тот же адрес);
- отправка ТОЛЬКО через two-step preview с истечением 120 c (fail-closed);
- данные (вольт/бэкап/история) — в /root/wallet_data (права 700), НЕ в git.

⚠️ Этап 1: используется для create/status/address/balance/receive. Отправка (send)
реализована, но НЕ подключена к авто-выплатам обменника — это отдельный gated-этап.
Пароль нигде не хранится: чтобы разлочить/отправить, его надо передать явно.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Хранилище ключей — вне git, только владелец.
DATA = Path(os.getenv("WALLET_DATA_DIR", "/root/wallet_data"))
SECURE_DIR = DATA / "secure"
TRON_VAULT_PATH = SECURE_DIR / "tron-wallet-vault.json"
TRON_META_PATH = SECURE_DIR / "tron-wallet-meta.json"
TRON_BACKUP_PATH = DATA / "backups" / "obsidian-tron-wallet-backup.json"
TRON_HISTORY_PATH = DATA / "tron_wallet_history.jsonl"
_AAD = b"OBSIDIAN-TRON-V1"

_TRON_PREVIEWS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.RLock()
_UNLOCKED_KEY: Optional[str] = None
_UNLOCKED_ADDRESS: Optional[str] = None
_UNLOCKED_AT = 0.0
_FAILED_ATTEMPTS = 0
_LOCKOUT_UNTIL = 0.0
DEFAULT_TTL = 900

USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRC20_TOKENS: Dict[str, Dict[str, Any]] = {"USDT": {"contract": USDT_TRC20, "decimals": 6}}
NETWORK_ID = "tron-mainnet"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if secret:
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 600
        except Exception:
            pass
    os.replace(tmp, path)


def _derive(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390000).derive(password.encode("utf-8"))


def _encrypt_secret(secret_hex: str, password: str) -> Dict[str, Any]:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive(password, salt)
    cipher = AESGCM(key).encrypt(nonce, secret_hex.encode("utf-8"), _AAD)
    return {
        "format": "OBSIDIAN_TRON_AESGCM_V1",
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


def _priv(key_hex: str):
    from tronpy.keys import PrivateKey  # type: ignore
    return PrivateKey(bytes.fromhex(key_hex))


def _client():
    from tronpy import Tron  # type: ignore
    try:
        client = Tron()  # публичный trongrid endpoint
        client.get_latest_block_number()
        return client, "trongrid-public"
    except Exception as exc:
        raise ConnectionError(f"tron_rpc_unavailable:{type(exc).__name__}")


def create_tron_wallet(password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    if len(password) < 10:
        raise ValueError("wallet_password_too_short_min_10")
    with _LOCK:
        if TRON_VAULT_PATH.exists() and not overwrite:
            return {"ok": True, "alreadyExists": True, **tron_status()}
        key_hex = os.urandom(32).hex()
        address = _priv(key_hex).public_key.to_base58check_address()
        encrypted = _encrypt_secret(key_hex, password)
        encrypted["address"] = address
        encrypted["createdAt"] = _now()
        _atomic_write(TRON_VAULT_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2), secret=True)
        _atomic_write(TRON_BACKUP_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2), secret=True)
        # Проверка бэкапа: расшифровать тем же паролем и сверить адрес.
        check_hex = _decrypt_secret(json.loads(TRON_BACKUP_PATH.read_text("utf-8")), password)
        backup_ok = _priv(check_hex).public_key.to_base58check_address() == address
        _atomic_write(TRON_META_PATH, json.dumps({
            "address": address, "createdAt": _now(), "backupConfirmed": backup_ok,
            "vaultPath": str(TRON_VAULT_PATH), "backupPath": str(TRON_BACKUP_PATH),
        }, ensure_ascii=False, indent=2))
        unlock_tron_wallet(password)
        return {"ok": True, "address": address, "backupConfirmed": backup_ok, "network": NETWORK_ID}


def import_tron_wallet(private_key_hex: str, password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    if len(password) < 10:
        raise ValueError("wallet_password_too_short_min_10")
    key_hex = private_key_hex.strip().lower().removeprefix("0x")
    if len(key_hex) != 64 or any(c not in "0123456789abcdef" for c in key_hex):
        raise ValueError("invalid_private_key_hex")
    with _LOCK:
        if TRON_VAULT_PATH.exists() and not overwrite:
            raise FileExistsError("wallet_already_exists_use_overwrite")
        address = _priv(key_hex).public_key.to_base58check_address()
        encrypted = _encrypt_secret(key_hex, password)
        encrypted["address"] = address
        encrypted["createdAt"] = _now()
        _atomic_write(TRON_VAULT_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2), secret=True)
        _atomic_write(TRON_BACKUP_PATH, json.dumps(encrypted, ensure_ascii=False, indent=2), secret=True)
        check_hex = _decrypt_secret(json.loads(TRON_BACKUP_PATH.read_text("utf-8")), password)
        backup_ok = _priv(check_hex).public_key.to_base58check_address() == address
        _atomic_write(TRON_META_PATH, json.dumps({
            "address": address, "createdAt": _now(), "backupConfirmed": backup_ok, "imported": True,
        }, ensure_ascii=False, indent=2))
        return {"ok": True, "address": address, "backupConfirmed": backup_ok, "imported": True}


def unlock_tron_wallet(password: str) -> Dict[str, Any]:
    global _UNLOCKED_KEY, _UNLOCKED_ADDRESS, _UNLOCKED_AT, _FAILED_ATTEMPTS, _LOCKOUT_UNTIL
    with _LOCK:
        if time.time() < _LOCKOUT_UNTIL:
            raise PermissionError(f"tron_wallet_unlock_temporarily_locked:{int(_LOCKOUT_UNTIL - time.time())}s")
        if not TRON_VAULT_PATH.exists():
            raise FileNotFoundError("tron_wallet_not_created")
        try:
            key_hex = _decrypt_secret(json.loads(TRON_VAULT_PATH.read_text("utf-8")), password)
            address = _priv(key_hex).public_key.to_base58check_address()
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


def lock_tron_wallet() -> Dict[str, Any]:
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


def tron_address() -> str:
    _expire()
    if _UNLOCKED_ADDRESS:
        return _UNLOCKED_ADDRESS
    try:
        return str(json.loads(TRON_META_PATH.read_text("utf-8")).get("address") or "")
    except Exception:
        return ""


def tron_balance() -> Dict[str, Any]:
    address = tron_address()
    if not address:
        return {"status": "BLOCKED", "reason": "tron_wallet_not_created", "balanceTrx": 0.0, "tokens": []}
    try:
        client, rpc = _client()
        try:
            trx = float(client.get_account_balance(address))
            activated = True
        except Exception:
            trx = 0.0
            activated = False
        tokens = []
        for symbol, cfg in TRC20_TOKENS.items():
            try:
                contract = client.get_contract(cfg["contract"])
                raw = int(contract.functions.balanceOf(address))
                tokens.append({"symbol": symbol, "contract": cfg["contract"], "balance": raw / (10 ** int(cfg["decimals"])), "raw": str(raw), "decimals": int(cfg["decimals"])})
            except Exception as exc:
                tokens.append({"symbol": symbol, "contract": cfg["contract"], "status": "ERROR", "error": f"{type(exc).__name__}"[:160]})
        return {"status": "OK" if activated else "UNFUNDED", "address": address, "balanceTrx": trx, "activated": activated, "tokens": tokens, "rpc": rpc}
    except Exception as exc:
        return {"status": "WAIT", "address": address, "balanceTrx": 0.0, "tokens": [], "reason": f"{type(exc).__name__}"[:240]}


def tron_status() -> Dict[str, Any]:
    _expire()
    meta: Dict[str, Any] = {}
    try:
        meta = json.loads(TRON_META_PATH.read_text("utf-8"))
    except Exception:
        pass
    return {
        "configured": TRON_VAULT_PATH.exists(),
        "address": tron_address(),
        "unlocked": bool(_UNLOCKED_KEY),
        "signerState": "UNLOCKED" if _UNLOCKED_KEY else "LOCKED",
        "backupConfirmed": bool(meta.get("backupConfirmed")),
        "network": NETWORK_ID,
        "supportedAssets": ["TRX"] + sorted(TRC20_TOKENS.keys()),
        "unlockRemainingSec": max(0, int(DEFAULT_TTL - (time.time() - _UNLOCKED_AT))) if _UNLOCKED_KEY else 0,
    }


def _append_history(row: Dict[str, Any]) -> None:
    TRON_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRON_HISTORY_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def tron_history(limit: int = 100) -> Dict[str, Any]:
    rows = []
    try:
        for line in TRON_HISTORY_PATH.read_text("utf-8").splitlines()[-max(1, min(500, int(limit))):]:
            if line.strip():
                rows.append(json.loads(line))
    except Exception:
        pass
    return {"entries": rows, "count": len(rows)}


def _is_valid_address(address: str) -> bool:
    try:
        from tronpy.keys import to_hex_address  # type: ignore
        to_hex_address(address)
        return str(address).startswith("T") and len(str(address)) == 34
    except Exception:
        return False


def preview_tron_send(asset: str, to_address: str, amount: float) -> Dict[str, Any]:
    _expire()
    if not _UNLOCKED_KEY:
        raise PermissionError("tron_signer_locked")
    if amount <= 0:
        raise ValueError("amount_must_be_positive")
    symbol = str(asset).upper().strip()
    if symbol != "TRX" and symbol not in TRC20_TOKENS:
        raise ValueError("asset_not_supported_on_tron")
    if not _is_valid_address(str(to_address)):
        raise ValueError("invalid_tron_destination_address")
    balance = tron_balance()
    if balance.get("status") not in {"OK", "UNFUNDED"}:
        raise ValueError("tron_rpc_unavailable")
    if symbol == "TRX":
        if float(balance.get("balanceTrx") or 0.0) <= float(amount):
            raise ValueError("insufficient_trx_balance")
        fee_note = "Комиссия сети TRON списывается в TRX (bandwidth/energy)."
    else:
        token = next((t for t in balance.get("tokens", []) if t.get("symbol") == symbol and "balance" in t), None)
        if not token or float(token.get("balance") or 0.0) < float(amount):
            raise ValueError("insufficient_token_balance")
        if float(balance.get("balanceTrx") or 0.0) <= 0:
            raise ValueError("insufficient_trx_for_energy_fee")
        fee_note = "Перевод TRC-20 сжигает TRX за energy. Держите хотя бы 25-30 TRX на счету."
    preview_id = secrets.token_urlsafe(18)
    row = {
        "previewId": preview_id, "expiresAt": time.time() + 120, "expiresInSec": 120,
        "network": NETWORK_ID, "asset": symbol, "from": tron_address(), "to": str(to_address),
        "amount": float(amount), "warning": fee_note, "createdAt": _now(),
    }
    _TRON_PREVIEWS[preview_id] = row
    return row


def send_tron_asset(asset: str, to_address: str, amount: float, preview_id: str = "") -> Dict[str, Any]:
    _expire()
    if not _UNLOCKED_KEY:
        raise PermissionError("tron_signer_locked")
    if amount <= 0:
        raise ValueError("amount_must_be_positive")
    symbol = str(asset).upper().strip()
    preview = _TRON_PREVIEWS.get(preview_id or "")
    if not preview:
        raise PermissionError("fresh_transfer_preview_required")
    if time.time() > float(preview.get("expiresAt") or 0):
        _TRON_PREVIEWS.pop(preview_id, None)
        raise PermissionError("transfer_preview_expired")
    if str(preview.get("to")) != str(to_address) or str(preview.get("asset")) != symbol or abs(float(preview.get("amount") or 0) - float(amount)) > 1e-12:
        raise PermissionError("transfer_preview_mismatch")
    _TRON_PREVIEWS.pop(preview_id, None)
    client, rpc = _client()
    priv = _priv(_UNLOCKED_KEY)
    sender = tron_address()
    if symbol == "TRX":
        amount_sun = int(Decimal(str(amount)) * Decimal(1_000_000))
        txn = client.trx.transfer(sender, str(to_address), amount_sun).build().sign(priv)
    else:
        cfg = TRC20_TOKENS[symbol]
        raw_amount = int(Decimal(str(amount)) * (Decimal(10) ** int(cfg["decimals"])))
        contract = client.get_contract(cfg["contract"])
        txn = contract.functions.transfer(str(to_address), raw_amount).with_owner(sender).fee_limit(40_000_000).build().sign(priv)
    result = txn.broadcast()
    try:
        receipt = result.wait(timeout=90)
    except Exception:
        receipt = {}
    tx_id = str(result.get("txid") or getattr(result, "txid", "") or "")
    receipt_status = str((receipt or {}).get("receipt", {}).get("result") or (receipt or {}).get("result") or "")
    confirmed = bool(receipt) and receipt_status in {"SUCCESS", ""}
    row = {
        "network": NETWORK_ID, "asset": symbol, "from": sender, "to": str(to_address),
        "amount": float(amount), "txHash": tx_id, "result": receipt_status or ("CONFIRMED" if confirmed else "PENDING"),
        "status": "CONFIRMED" if confirmed else ("FAILED" if receipt_status and receipt_status != "SUCCESS" else "SUBMITTED_UNCONFIRMED"),
        "rpc": rpc, "timestamp": _now(),
    }
    _append_history(row)
    if row["status"] == "FAILED":
        raise RuntimeError(f"tron_transaction_failed:{receipt_status}")
    return row
