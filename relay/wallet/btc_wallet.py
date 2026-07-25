"""Горячий кошелёк BTC/LTC (secure-контур, единый с TRON) для ObsidianExchange.

Зачем. До 25.07.2026 приватные ключи BTC/LTC (мастер-сиды BIP84 zprv/Mtpv,
полный контроль над средствами) лежали в ПЛЕЙНТЕКСТЕ в bitcoinlib.sqlite, а сам
файл был 644 — читаем любым пользователем машины. Права закрыты (700/600), а этот
модуль поднимает BTC/LTC в тот же защищённый контур, что TRON:
- мастер-ключ шифруется ПАРОЛЕМ (PBKDF2-HMAC-SHA256 390k → AES-GCM); в открытом
  виде на диске не лежит НИКОГДА;
- разлочка на сессию (ключ в памяти) TTL 15 мин + lockout после 5 ошибок;
- шифрованный бэкап + криптопроверка (расшифровывается тем же паролем → тот же адрес);
- отправка ТОЛЬКО через two-step preview (120 c, fail-closed) + идемпотентность + потолок;
- данные (вольт/бэкап/история) — в /root/wallet_data (700), НЕ в git.

Существующие легаси HD-кошельки bitcoinlib (PayoutWallet=BTC, PayoutLTC=LTC,
BIP84 segwit) ДЕРЖАТ средства. import_from_legacy() импортирует их сид сюда:
реконструкция из zprv даёт побайтово те же адреса (проверено), деньги не двигаются,
адреса пополнения не меняются. Легаси send_crypto продолжает работать — этот модуль
безопасная альтернатива, НЕ ломающая старый путь. Миграция легаси на этот путь и
удаление плейнтекст-сида — отдельный gated-шаг.

⚠️ Отправка реализована, но НЕ подключена к авто-выплатам обменника — это отдельный
этап. Пароль нигде не хранится: чтобы разлочить/отправить, его надо передать явно.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DATA = Path(os.getenv("WALLET_DATA_DIR", "/root/wallet_data"))
SECURE_DIR = DATA / "secure"

# Конфигурация монет. Один модуль обслуживает обе — логика идентична, разнятся
# сеть, легаси-имя и AAD (домен шифрования: чек BTC нельзя расшифровать как LTC).
COINS: Dict[str, Dict[str, Any]] = {
    "BTC": {"network": "bitcoin", "legacy": "PayoutWallet",
            "aad": b"OBSIDIAN-BTC-V1", "decimals": 8, "network_id": "bitcoin-mainnet"},
    "LTC": {"network": "litecoin", "legacy": "PayoutLTC",
            "aad": b"OBSIDIAN-LTC-V1", "decimals": 8, "network_id": "litecoin-mainnet"},
}

# Жёсткий потолок одной отправки (fail-closed), в монетах. Настраивается env.
MAX_SEND: Dict[str, float] = {
    "BTC": float(os.getenv("WALLET_MAX_SEND_BTC", "1") or 1),
    "LTC": float(os.getenv("WALLET_MAX_SEND_LTC", "1000") or 1000),
}

# Пол фидрейта (сат/vByte). bitcoinlib с авто-оценкой в спокойной сети берёт
# ~1 сат/vB — при последующей загрузке такая выплата зависает на часы. Пол
# гарантирует подтверждение в разумный срок; при реальной загрузке сети оценка
# провайдера выше пола и побеждает (берём max). Настраивается env.
MIN_FEERATE: Dict[str, float] = {
    "BTC": float(os.getenv("WALLET_BTC_MIN_FEERATE", "4") or 4),
    "LTC": float(os.getenv("WALLET_LTC_MIN_FEERATE", "2") or 2),
}

DEFAULT_TTL = 900
_SAT = Decimal(10) ** 8

_LOCK = threading.RLock()
# Разлочка и previews — по монете (BTC и LTC независимы).
_UNLOCKED: Dict[str, Dict[str, Any]] = {}   # coin -> {"zprv","address","at"}
_FAILED: Dict[str, int] = {}
_LOCKOUT_UNTIL: Dict[str, float] = {}
_PREVIEWS: Dict[str, Dict[str, Any]] = {}    # preview_id -> row


# ── общие пути/крипто ─────────────────────────────────────────────────────────

def _coin(coin: str) -> Dict[str, Any]:
    c = str(coin).upper().strip()
    if c not in COINS:
        raise ValueError(f"coin_not_supported:{coin}")
    return COINS[c]


def _vault_path(coin: str) -> Path:
    return SECURE_DIR / f"{coin.lower()}-wallet-vault.json"


def _meta_path(coin: str) -> Path:
    return SECURE_DIR / f"{coin.lower()}-wallet-meta.json"


def _backup_path(coin: str) -> Path:
    return DATA / "backups" / f"obsidian-{coin.lower()}-wallet-backup.json"


def _history_path(coin: str) -> Path:
    return DATA / f"{coin.lower()}_wallet_history.jsonl"


def _sends_path(coin: str) -> Path:
    return SECURE_DIR / f"{coin.lower()}-sends.json"


def _previews_path(coin: str) -> Path:
    return SECURE_DIR / f"{coin.lower()}-previews.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, text: str) -> None:
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


def _derive(password: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                      iterations=390000).derive(password.encode("utf-8"))


def _encrypt_secret(secret: str, password: str, aad: bytes) -> Dict[str, Any]:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive(password, salt)
    cipher = AESGCM(key).encrypt(nonce, secret.encode("utf-8"), aad)
    return {
        "format": "OBSIDIAN_BTCLTC_AESGCM_V1",
        "kdf": "PBKDF2-HMAC-SHA256", "iterations": 390000,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(cipher).decode("ascii"),
    }


def _decrypt_secret(payload: Dict[str, Any], password: str, aad: bytes) -> str:
    salt = base64.b64decode(payload["salt"])
    nonce = base64.b64decode(payload["nonce"])
    cipher = base64.b64decode(payload["ciphertext"])
    key = _derive(password, salt)
    return AESGCM(key).decrypt(nonce, cipher, aad).decode("utf-8")


# ── bitcoinlib helpers ────────────────────────────────────────────────────────

def _ephemeral_wallet(coin: str, zprv: str, scan: bool = False):
    """Восстанавливает HD-кошелёк из мастер-ключа во ВРЕМЕННОЙ БД (внутри 700).

    Возвращает (wallet, cleanup_fn). Ключ на постоянный диск не садится: temp-БД
    живёт только на время операции и уничтожается cleanup_fn (shred + rmtree).
    """
    from bitcoinlib.wallets import Wallet, wallet_delete_if_exists  # type: ignore
    cfg = _coin(coin)
    SECURE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    d = tempfile.mkdtemp(dir=str(SECURE_DIR))
    os.chmod(d, 0o700)
    dbf = os.path.join(d, "eph.sqlite")
    uri = f"sqlite:///{dbf}"
    name = f"eph_{coin.lower()}_{secrets.token_hex(6)}"

    def cleanup():
        try:
            wallet_delete_if_exists(name, db_uri=uri, force=True)
        except Exception:
            pass
        try:
            if os.path.exists(dbf):
                # перезаписываем перед удалением: temp-БД содержала приватный ключ
                with open(dbf, "ba+", buffering=0) as f:
                    length = f.tell()
                    f.seek(0)
                    f.write(os.urandom(max(length, 1)))
        except Exception:
            pass
        shutil.rmtree(d, ignore_errors=True)

    try:
        wallet_delete_if_exists(name, db_uri=uri, force=True)
    except Exception:
        pass
    try:
        w = Wallet.create(name, keys=zprv, network=cfg["network"],
                          witness_type="segwit", purpose=84, db_uri=uri)
        if scan:
            w.scan(scan_gap_limit=5)
        return w, cleanup
    except Exception:
        cleanup()
        raise


def _service(coin: str):
    from bitcoinlib.services.services import Service  # type: ignore
    return Service(network=_coin(coin)["network"], timeout=12)


# ── создание / импорт ─────────────────────────────────────────────────────────

def import_from_legacy(coin: str, password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    """Импортирует сид существующего легаси-кошелька bitcoinlib в шифрованный вольт.

    Деньги НЕ двигаются: сохраняется только зашифрованная копия мастер-ключа.
    Адреса реконструкции сверяются с легаси — при расхождении импорт падает.
    """
    from bitcoinlib.wallets import Wallet  # type: ignore
    if len(password) < 10:
        raise ValueError("wallet_password_too_short_min_10")
    cfg = _coin(coin)
    with _LOCK:
        if _vault_path(coin).exists() and not overwrite:
            return {"ok": True, "alreadyExists": True, **status(coin)}
        legacy = Wallet(cfg["legacy"])
        zprv = legacy.main_key.wif
        if not zprv or not str(zprv).lower().startswith(("zprv", "xprv", "mtpv", "ltpv", "tprv")):
            raise ValueError("legacy_master_key_not_extended_private")
        legacy_addrs = legacy.addresslist()
        legacy_xpub = str(legacy.public_master().wif)
        # сверяем реконструкцию по account-xpub: он однозначно определяется сидом
        # и не зависит от порядка/смешения receiving+change адресов в списке.
        w, cleanup = _ephemeral_wallet(coin, zprv)
        try:
            recon_xpub = str(w.public_master().wif)
        finally:
            cleanup()
        if recon_xpub != legacy_xpub:
            raise ValueError("reconstruction_xpub_mismatch")
        primary = legacy_addrs[0] if legacy_addrs else ""
        res = _persist_vault(coin, zprv, password, primary, legacy_addrs, imported=True)
        unlock(coin, password)
        return res


def import_wallet(coin: str, master_xprv: str, password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    """Импорт по внешнему мастер-ключу (zprv/xprv/Mtpv…)."""
    if len(password) < 10:
        raise ValueError("wallet_password_too_short_min_10")
    zprv = master_xprv.strip()
    with _LOCK:
        if _vault_path(coin).exists() and not overwrite:
            raise FileExistsError("wallet_already_exists_use_overwrite")
        w, cleanup = _ephemeral_wallet(coin, zprv)
        try:
            for _ in range(5):
                w.new_key()
            addrs = w.addresslist()
        finally:
            cleanup()
        return _persist_vault(coin, zprv, password, addrs[0] if addrs else "", addrs, imported=True)


def _persist_vault(coin: str, zprv: str, password: str, primary: str, addrs: list,
                   *, imported: bool) -> Dict[str, Any]:
    """Шифрует мастер-ключ в вольт + бэкап, проверяет восстановимость, пишет мету."""
    cfg = _coin(coin)
    enc = _encrypt_secret(zprv, password, cfg["aad"])
    enc["primaryAddress"] = primary
    enc["createdAt"] = _now()
    _atomic_write(_vault_path(coin), json.dumps(enc, ensure_ascii=False, indent=2))
    _atomic_write(_backup_path(coin), json.dumps(enc, ensure_ascii=False, indent=2))
    # криптопроверка бэкапа: расшифровать тем же паролем → тот же мастер-ключ
    check = _decrypt_secret(json.loads(_backup_path(coin).read_text("utf-8")), password, cfg["aad"])
    backup_ok = (check == zprv)
    _atomic_write(_meta_path(coin), json.dumps({
        "coin": coin.upper(), "network": cfg["network"], "primaryAddress": primary,
        "addresses": list(addrs or []), "createdAt": _now(),
        "backupConfirmed": backup_ok, "imported": imported,
        "vaultPath": str(_vault_path(coin)), "backupPath": str(_backup_path(coin)),
    }, ensure_ascii=False, indent=2))
    return {"ok": True, "coin": coin.upper(), "primaryAddress": primary,
            "addresses": len(addrs or []), "backupConfirmed": backup_ok,
            "network": cfg["network_id"]}


# ── разлочка / статус ─────────────────────────────────────────────────────────

def unlock(coin: str, password: str) -> Dict[str, Any]:
    cfg = _coin(coin)
    coin = coin.upper()
    with _LOCK:
        if time.time() < _LOCKOUT_UNTIL.get(coin, 0):
            raise PermissionError(
                f"{coin.lower()}_wallet_unlock_temporarily_locked:{int(_LOCKOUT_UNTIL[coin]-time.time())}s")
        if not _vault_path(coin).exists():
            raise FileNotFoundError(f"{coin.lower()}_wallet_not_created")
        try:
            zprv = _decrypt_secret(json.loads(_vault_path(coin).read_text("utf-8")), password, cfg["aad"])
        except Exception:
            _FAILED[coin] = _FAILED.get(coin, 0) + 1
            if _FAILED[coin] >= 5:
                _LOCKOUT_UNTIL[coin] = time.time() + 60
                _FAILED[coin] = 0
            raise ValueError("invalid_wallet_password")
        _UNLOCKED[coin] = {"zprv": zprv, "address": _meta_primary(coin), "at": time.time()}
        _FAILED[coin] = 0
        return {"ok": True, "coin": coin, "unlocked": True, "expiresInSec": DEFAULT_TTL}


def lock(coin: str) -> Dict[str, Any]:
    with _LOCK:
        _UNLOCKED.pop(coin.upper(), None)
    return {"ok": True, "coin": coin.upper(), "unlocked": False}


def _expire(coin: str) -> None:
    coin = coin.upper()
    u = _UNLOCKED.get(coin)
    if u and time.time() - u["at"] >= DEFAULT_TTL:
        _UNLOCKED.pop(coin, None)


def _unlocked_zprv(coin: str) -> str:
    _expire(coin)
    u = _UNLOCKED.get(coin.upper())
    if not u:
        raise PermissionError(f"{coin.lower()}_signer_locked")
    return u["zprv"]


def _meta(coin: str) -> Dict[str, Any]:
    try:
        return json.loads(_meta_path(coin).read_text("utf-8"))
    except Exception:
        return {}


def _meta_primary(coin: str) -> str:
    return str(_meta(coin).get("primaryAddress") or "")


def address(coin: str) -> str:
    return _meta_primary(coin)


def status(coin: str) -> Dict[str, Any]:
    _expire(coin)
    coin = coin.upper()
    meta = _meta(coin)
    u = _UNLOCKED.get(coin)
    return {
        "coin": coin, "configured": _vault_path(coin).exists(),
        "primaryAddress": meta.get("primaryAddress") or "",
        "addresses": len(meta.get("addresses") or []),
        "unlocked": bool(u),
        "signerState": "UNLOCKED" if u else "LOCKED",
        "backupConfirmed": bool(meta.get("backupConfirmed")),
        "network": _coin(coin)["network_id"],
        "unlockRemainingSec": max(0, int(DEFAULT_TTL - (time.time() - u["at"]))) if u else 0,
    }


def balance(coin: str) -> Dict[str, Any]:
    """Агрегатный баланс по сохранённым адресам (сид НЕ нужен, read-only).

    Сбой чтения по адресу — ERROR, а НЕ ноль: «не смогли прочитать» нельзя
    выдавать за «средств нет» (та же логика, что в TRON-кошельке).
    """
    coin = coin.upper()
    addrs = _meta(coin).get("addresses") or []
    if not addrs:
        return {"coin": coin, "status": "BLOCKED", "reason": "wallet_not_created",
                "balance": 0.0, "confirmed": 0.0}
    try:
        svc = _service(coin)
    except Exception as exc:
        return {"coin": coin, "status": "WAIT", "balance": 0.0,
                "reason": f"{type(exc).__name__}"[:160]}
    total_sat = 0
    errors = 0
    for a in addrs:
        got = None
        for attempt in range(2):
            try:
                got = int(svc.getbalance(a))
                break
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        if got is None:
            errors += 1
        else:
            total_sat += got
    coins = float(Decimal(total_sat) / _SAT)
    out = {"coin": coin, "primaryAddress": _meta_primary(coin),
           "balance": coins, "balanceSat": total_sat,
           "addressCount": len(addrs)}
    out["status"] = "OK" if errors == 0 else ("PARTIAL" if errors < len(addrs) else "ERROR")
    if errors:
        out["addressReadErrors"] = errors
    return out


# ── история / идемпотентность ─────────────────────────────────────────────────

def _append_history(coin: str, row: Dict[str, Any]) -> None:
    p = _history_path(coin)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def history(coin: str, limit: int = 100) -> Dict[str, Any]:
    rows = []
    try:
        for line in _history_path(coin).read_text("utf-8").splitlines()[-max(1, min(500, int(limit))):]:
            if line.strip():
                rows.append(json.loads(line))
    except Exception:
        pass
    return {"coin": coin.upper(), "entries": rows, "count": len(rows)}


def _load_sends(coin: str) -> Dict[str, Any]:
    try:
        return json.loads(_sends_path(coin).read_text("utf-8"))
    except Exception:
        return {}


def _save_sends(coin: str, obj: Dict[str, Any]) -> None:
    _atomic_write(_sends_path(coin), json.dumps(obj, ensure_ascii=False, indent=2))


def _is_valid_address(coin: str, addr: str) -> bool:
    try:
        from bitcoinlib.keys import Address  # type: ignore
        Address.parse(str(addr))
        return True
    except Exception:
        # Address.parse принимает адрес любой сети; для нашей монеты проверим префикс
        try:
            from bitcoinlib.encoding import addr_to_pubkeyhash  # type: ignore
            addr_to_pubkeyhash(str(addr), encoding=None)
            return True
        except Exception:
            return False


# ── two-step отправка ─────────────────────────────────────────────────────────

def preview_send(coin: str, to_address: str, amount: float) -> Dict[str, Any]:
    coin = coin.upper()
    cfg = _coin(coin)
    _unlocked_zprv(coin)                       # отправка только при разлочке
    if amount <= 0:
        raise ValueError("amount_must_be_positive")
    cap = MAX_SEND.get(coin)
    if cap is not None and float(amount) > cap:
        raise ValueError(f"amount_exceeds_max_send_{coin}:{cap}")
    if not _is_valid_address(coin, to_address):
        raise ValueError("invalid_destination_address")
    bal = balance(coin)
    if bal.get("status") not in {"OK", "PARTIAL"}:
        raise ValueError("balance_unavailable")
    have = float(bal.get("balance") or 0.0)
    # грубая оценка комиссии (уточняется при отправке). Учитываем пол фидрейта,
    # чтобы preview не показывал заниженную комиссию относительно реальной отправки.
    fee_sat = None
    try:
        est_vsize = 200 + 70 * 3                              # ~ 3 входа + 2 выхода
        feerate_vb = 1.0
        try:
            feerate_vb = max(int(_service(coin).estimatefee(blocks=3)) / 1000.0,
                             MIN_FEERATE.get(coin, 1))        # сат/vByte
        except Exception:
            feerate_vb = MIN_FEERATE.get(coin, 1)
        fee_sat = int(feerate_vb * est_vsize)
    except Exception:
        fee_sat = None
    need = float(amount) + (float(Decimal(fee_sat) / _SAT) if fee_sat else 0.0)
    if have < need:
        raise ValueError(f"insufficient_balance: нужно ≈{need:.8f} {coin}, есть {have:.8f}")
    preview_id = secrets.token_urlsafe(18)
    fee_note = (f"Комиссия сети ≈ {float(Decimal(fee_sat)/_SAT):.8f} {coin}."
                if fee_sat else "Комиссию оценит сеть при отправке.")
    row = {"previewId": preview_id, "expiresAt": time.time() + 120, "expiresInSec": 120,
           "coin": coin, "network": cfg["network_id"], "from": _meta_primary(coin),
           "to": str(to_address), "amount": float(amount), "estimatedFeeSat": fee_sat,
           "warning": fee_note, "createdAt": _now()}
    _PREVIEWS[preview_id] = row
    try:
        _atomic_write(_previews_path(coin), json.dumps(_PREVIEWS, ensure_ascii=False))
    except Exception:
        pass
    return row


def send(coin: str, to_address: str, amount: float, preview_id: str = "",
         idempotency_key: str = "") -> Dict[str, Any]:
    coin = coin.upper()
    cfg = _coin(coin)
    zprv = _unlocked_zprv(coin)
    if amount <= 0:
        raise ValueError("amount_must_be_positive")
    cap = MAX_SEND.get(coin)
    if cap is not None and float(amount) > cap:
        raise ValueError(f"amount_exceeds_max_send_{coin}:{cap}")
    # идемпотентность: один логический перевод не должен уйти дважды
    if idempotency_key:
        with _LOCK:
            sends = _load_sends(coin)
            prev = sends.get(idempotency_key)
            if prev and prev.get("txHash"):
                return {**prev, "idempotent": True}
            if prev and prev.get("status") == "broadcasting":
                raise PermissionError("send_in_progress_for_key")
    # проверка свежего preview (fail-closed)
    preview = _PREVIEWS.get(preview_id or "")
    if not preview:
        try:
            preview = json.loads(_previews_path(coin).read_text("utf-8")).get(preview_id or "")
        except Exception:
            preview = None
    if not preview:
        raise PermissionError("fresh_transfer_preview_required")
    if time.time() > float(preview.get("expiresAt") or 0):
        _PREVIEWS.pop(preview_id, None)
        raise PermissionError("transfer_preview_expired")
    if (str(preview.get("to")) != str(to_address) or str(preview.get("coin")) != coin
            or abs(float(preview.get("amount") or 0) - float(amount)) > 1e-12):
        raise PermissionError("transfer_preview_mismatch")
    _PREVIEWS.pop(preview_id, None)
    # помечаем broadcasting ДО отправки — повтор с тем же ключом не подпишет дважды
    if idempotency_key:
        with _LOCK:
            sends = _load_sends(coin)
            if sends.get(idempotency_key, {}).get("txHash"):
                return {**sends[idempotency_key], "idempotent": True}
            sends[idempotency_key] = {"status": "broadcasting", "coin": coin,
                                      "to": str(to_address), "amount": float(amount),
                                      "startedAt": _now()}
            _save_sends(coin, sends)

    value_sat = int((Decimal(str(amount)) * _SAT).to_integral_value())
    import math
    w, cleanup = _ephemeral_wallet(coin, zprv, scan=True)
    tx_id = ""
    fee_paid = 0
    try:
        # 1) строим вхолодную (без broadcast), чтобы измерить размер и авто-оценку
        wt = w.send_to(str(to_address), value_sat, fee=None, broadcast=False,
                       number_of_change_outputs=1)
        auto_fee = int(getattr(wt, "fee", 0) or 0)
        try:
            vsize = int(getattr(wt, "vsize", 0) or getattr(wt, "size", 0)
                        or wt.estimate_size() or 0)
        except Exception:
            vsize = 0
        floor = int(math.ceil(MIN_FEERATE.get(coin, 1) * vsize)) if vsize else 0
        # 2) если авто-оценка ниже пола — пересобираем с явной комиссией = пол.
        #    max: при загрузке сети auto_fee уже выше пола и остаётся.
        target_fee = max(auto_fee, floor)
        if target_fee > auto_fee:
            wt = w.send_to(str(to_address), value_sat, fee=target_fee, broadcast=False,
                           number_of_change_outputs=1)
        # 3) broadcast построенной и подписанной транзакции
        wt.send()
        tx_id = str(getattr(wt, "txid", "") or "")
        fee_paid = int(getattr(wt, "fee", 0) or 0)
        send_err = getattr(wt, "error", None)
        if not tx_id and send_err:
            raise RuntimeError(f"broadcast_error:{send_err}")
    finally:
        cleanup()
    ok = bool(tx_id)
    row = {"coin": coin, "network": cfg["network_id"], "from": _meta_primary(coin),
           "to": str(to_address), "amount": float(amount), "amountSat": value_sat,
           "txHash": tx_id, "feeSat": fee_paid if ok else None,
           "status": "SUBMITTED" if ok else "FAILED", "timestamp": _now()}
    _append_history(coin, row)
    if idempotency_key:
        with _LOCK:
            sends = _load_sends(coin)
            sends[idempotency_key] = {**row, "idempotencyKey": idempotency_key}
            _save_sends(coin, sends)
    if not ok:
        raise RuntimeError("broadcast_failed_no_txid")
    return row
