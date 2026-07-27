"""Secure-кошелёк XRP (XRP Ledger) — тот же контур, что у BTC/LTC и EVM.

Ключ хранится зашифрованным (PBKDF2-390k → AES-GCM), разлочка на сессию с TTL,
двухшаговая отправка (preview → send по previewId), идемпотентность по ключу
заявки, межпроцессный flock на отправку, потолок суммы. Ничего не отправляется
без явного гейта XRP_PAYOUTS_ENABLED.

Специфика XRPL, из-за которой нельзя просто скопировать EVM-модуль:

  * Резерв аккаунта. На счету обязан остаться base reserve (сейчас 1 XRP),
    иначе транзакция отклоняется. Доступно к отправке = баланс − резерв − комиссия.
    Отправка «всего баланса» на XRPL невозможна в принципе.
  * Destination tag. Биржи и кастодиальные сервисы принимают XRP ТОЛЬКО с тегом:
    без него средства попадают на общий счёт биржи и теряются для получателя.
    Тег — часть адреса назначения, поэтому он проходит через весь путь выплаты.
  * X-address. Современный формат (X…) кодирует адрес и тег вместе; принимаем оба,
    X-адрес разбираем в пару (classic, tag) — так тег невозможно потерять.
  * Неактивированный счёт. Перевод на счёт без резерва требует минимум 1 XRP,
    иначе транзакция отклоняется сетью.

Модуль инертен без xrpl-py: импорт библиотеки ленивый, status() честно скажет,
что кошелёк не сконфигурирован.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

DATA = Path(os.getenv("WALLET_DATA_DIR", "/root/wallet_data"))
SECURE_DIR = DATA / "secure"
XRP_VAULT_PATH = SECURE_DIR / "xrp-wallet-vault.json"
XRP_META_PATH = SECURE_DIR / "xrp-wallet-meta.json"
XRP_BACKUP_PATH = DATA / "backups" / "obsidian-xrp-wallet-backup.json"
XRP_HISTORY_PATH = DATA / "xrp_wallet_history.jsonl"
XRP_SENDS_PATH = SECURE_DIR / "xrp-sends.json"
XRP_PREVIEWS_PATH = SECURE_DIR / "xrp-previews.json"
XRP_SENDLOCK_PATH = SECURE_DIR / "xrp-send.lock"
XRP_LOCKOUT_PATH = SECURE_DIR / "xrp-lockout.json"
_AAD = b"OBSIDIAN-XRP-V1"      # свой домен: ключ EVM не расшифруется как XRP и наоборот

DROPS_PER_XRP = 1_000_000       # XRP считается в drops (1e-6)
# Базовый резерв счёта. Держим отдельной настройкой: сеть меняла его (было 20,
# затем 10, сейчас 1 XRP) — при изменении правим env, а не код.
BASE_RESERVE_XRP = float(os.getenv("XRP_BASE_RESERVE", "1"))
# Дополнительный резерв за каждый объект счёта (трастлайн, ордер и т.п.)
OWNER_RESERVE_XRP = float(os.getenv("XRP_OWNER_RESERVE", "0.2"))
MAX_SEND_XRP = float(os.getenv("XRP_MAX_SEND", "1000"))
MAX_FEE_XRP = float(os.getenv("XRP_MAX_FEE", "0.5"))
PREVIEW_TTL = 120
DEFAULT_TTL = 900
_LOCKOUT_AFTER = 5
_LOCKOUT_SECONDS = 300

_DEFAULT_RPC = os.getenv("XRP_RPC_URL", "https://xrplcluster.com/")

_LOCK = threading.RLock()
_UNLOCKED_SEED: Optional[str] = None
_UNLOCKED_ADDRESS: Optional[str] = None
_UNLOCKED_AT = 0.0


def payouts_enabled() -> bool:
    """Гейт авто-выплат XRP. По умолчанию ВЫКЛ: модуль может быть настроен и
    проверен задолго до того, как обменник начнёт продавать XRP."""
    return os.getenv("XRP_PAYOUTS_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


# ── служебное ────────────────────────────────────────────────────────────────
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
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    os.replace(tmp, path)


def _read_json(path: Path, default):
    """Мягкое чтение: нет файла — отдаём default. ⚠️ Для журналов, от которых
    зависит запрет повторной отправки, использовать _read_json_strict."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        return default


def _read_json_strict(path: Path, default):
    """Чтение, где повреждение файла — ОТКАЗ, а не «данных нет».

    Журнал отправок отвечает на вопрос «мы это уже платили?». Если он не
    читается, ответ неизвестен, а трактовать неизвестность как «не платили»
    значит разрешить вторую отправку тех же денег.
    """
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"journal_unreadable: {path.name}: {type(e).__name__}") from e


def _norm_tag(tag):
    """Destination tag → int 0..2^32-1 или None. Тег 0 — ВАЛИДНОЕ значение и
    обязан отличаться от «тега нет»: часть бирж использует именно 0. Дробные и
    строковые значения не приводим молча (1.9 стало бы тегом 1 — чужой счёт)."""
    if tag is None:
        return None
    if isinstance(tag, bool) or not isinstance(tag, int):
        raise ValueError("invalid_destination_tag")
    if tag < 0 or tag > 0xFFFFFFFF:
        raise ValueError("invalid_destination_tag")
    return tag


def _same_tag(a, b) -> bool:
    """Сравнение тегов с различением None и 0."""
    if a is None or b is None:
        return a is None and b is None
    return int(a) == int(b)


@contextmanager
def _proc_lock():
    """Межпроцессный лок на отправку: потоковый _LOCK не спасает, когда send()
    вызван из разных процессов (бот и CLI)."""
    SECURE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(SECURE_DIR, 0o700)
    except Exception:
        pass
    f = open(XRP_SENDLOCK_PATH, "a+")
    try:
        os.chmod(XRP_SENDLOCK_PATH, stat.S_IRUSR | stat.S_IWUSR)
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


def _encrypt_secret(secret: str, password: str) -> Dict[str, Any]:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    cipher = AESGCM(_derive(password, salt)).encrypt(nonce, secret.encode("utf-8"), _AAD)
    return {
        "format": "OBSIDIAN_XRP_AESGCM_V1",
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
    return AESGCM(_derive(password, salt)).decrypt(nonce, cipher, _AAD).decode("utf-8")


# ── xrpl-py (ленивый импорт) ─────────────────────────────────────────────────
def _xrpl():
    import xrpl  # type: ignore
    return xrpl


def library_available() -> bool:
    try:
        _xrpl()
        return True
    except Exception:
        return False


def _wallet_from_seed(seed: str):
    from xrpl.wallet import Wallet  # type: ignore
    return Wallet.from_seed(seed)


def parse_destination(address: str):
    """(classic_address, destination_tag) или (None, None).

    Принимает classic (r…) и X-адрес (X…). X-адрес несёт тег внутри себя —
    разбираем его здесь, чтобы тег физически не мог потеряться по пути.
    """
    if not address or not isinstance(address, str):
        return (None, None)
    addr = address.strip()
    try:
        from xrpl.core import addresscodec  # type: ignore
    except Exception:
        return (None, None)
    try:
        if addresscodec.is_valid_xaddress(addr):
            classic, tag, _is_test = addresscodec.xaddress_to_classic_address(addr)
            return (classic, tag)
        if addresscodec.is_valid_classic_address(addr):
            return (addr, None)
    except Exception:
        return (None, None)
    return (None, None)


def is_valid_address(address: str) -> bool:
    classic, _tag = parse_destination(address)
    return classic is not None


# ── создание/импорт вольта ───────────────────────────────────────────────────
def create_wallet(password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    if XRP_VAULT_PATH.exists() and not overwrite:
        raise RuntimeError("vault_exists")
    from xrpl.wallet import Wallet  # type: ignore
    w = Wallet.create()
    return _persist(w.seed, password, imported=False)


def import_wallet(seed: str, password: str, *, overwrite: bool = False) -> Dict[str, Any]:
    if XRP_VAULT_PATH.exists() and not overwrite:
        raise RuntimeError("vault_exists")
    _wallet_from_seed(seed)   # проверяем, что сид валиден, до записи
    return _persist(seed, password, imported=True)


def _persist(seed: str, password: str, *, imported: bool) -> Dict[str, Any]:
    address = _wallet_from_seed(seed).classic_address
    vault = _encrypt_secret(seed, password)
    _atomic_write(XRP_VAULT_PATH, json.dumps(vault, indent=2))
    meta = {"address": address, "created_at": _now(), "imported": imported,
            "network": os.getenv("XRP_NETWORK_ID", "xrpl-mainnet")}
    _atomic_write(XRP_META_PATH, json.dumps(meta, indent=2))
    # Шифр-бэкап рядом: вольт без копии — одна точка отказа
    _atomic_write(XRP_BACKUP_PATH, json.dumps(
        {"address": address, "created_at": _now(), "vault": vault}, indent=2))
    # Криптопроверка: бэкап обязан расшифровываться тем же паролем
    if _decrypt_secret(_read_json(XRP_BACKUP_PATH, {}).get("vault", {}), password) != seed:
        raise RuntimeError("backup_verify_failed")
    return {"address": address, "backup": str(XRP_BACKUP_PATH)}


# ── разлочка ─────────────────────────────────────────────────────────────────
def _lockout_state() -> Dict[str, Any]:
    return _read_json(XRP_LOCKOUT_PATH, {"fails": 0, "until": 0.0})


def _lockout_save(fails: int, until: float) -> None:
    _atomic_write(XRP_LOCKOUT_PATH, json.dumps({"fails": fails, "until": until}))


def unlock(password: str, ttl: int = DEFAULT_TTL) -> Dict[str, Any]:
    global _UNLOCKED_SEED, _UNLOCKED_ADDRESS, _UNLOCKED_AT
    with _LOCK:
        # Счётчик неудач — НА ДИСКЕ: в памяти его обнуляли перезапуск процесса и
        # параллельные процессы (каждый получал свои 5 попыток).
        ls = _lockout_state()
        if time.time() < float(ls.get("until", 0)):
            raise RuntimeError("locked_out")
        vault = _read_json(XRP_VAULT_PATH, None)
        if not vault:
            raise RuntimeError("vault_missing")
        try:
            seed = _decrypt_secret(vault, password)
        except Exception:
            fails = int(ls.get("fails", 0)) + 1
            if fails >= _LOCKOUT_AFTER:
                _lockout_save(0, time.time() + _LOCKOUT_SECONDS)
            else:
                _lockout_save(fails, 0.0)
            raise ValueError("invalid_wallet_password")
        _lockout_save(0, 0.0)
        _UNLOCKED_SEED = seed
        _UNLOCKED_ADDRESS = _wallet_from_seed(seed).classic_address
        _UNLOCKED_AT = time.time() + max(60, int(ttl))
        return {"unlocked": True, "address": _UNLOCKED_ADDRESS}


def lock() -> Dict[str, Any]:
    global _UNLOCKED_SEED, _UNLOCKED_ADDRESS, _UNLOCKED_AT
    with _LOCK:
        _UNLOCKED_SEED = None
        _UNLOCKED_ADDRESS = None
        _UNLOCKED_AT = 0.0
        return {"unlocked": False}


def _expire() -> None:
    global _UNLOCKED_SEED, _UNLOCKED_ADDRESS
    if _UNLOCKED_SEED and time.time() > _UNLOCKED_AT:
        _UNLOCKED_SEED = None
        _UNLOCKED_ADDRESS = None


def status() -> Dict[str, Any]:
    _expire()
    meta = _read_json(XRP_META_PATH, {}) or {}
    return {
        "configured": XRP_VAULT_PATH.exists(),
        "unlocked": bool(_UNLOCKED_SEED),
        "address": meta.get("address", ""),
        "network": meta.get("network", "xrpl-mainnet"),
        "library": library_available(),
        "payouts_enabled": payouts_enabled(),
        "base_reserve_xrp": BASE_RESERVE_XRP,
    }


# ── сеть ─────────────────────────────────────────────────────────────────────
def _client():
    from xrpl.clients import JsonRpcClient  # type: ignore
    return JsonRpcClient(_DEFAULT_RPC)


def account_state(address: str = None) -> Dict[str, Any]:
    """Состояние счёта: баланс, OwnerCount, доступно к отправке.

    status: OK | NOT_FOUND (счёт не активирован) | ERROR (сеть/узел).
    Сетевую ошибку НЕ выдаём за нулевой баланс: «ноль» и «не знаем» —
    разные вещи, и на витрине они не должны выглядеть одинаково.
    """
    addr = address or (_read_json(XRP_META_PATH, {}) or {}).get("address")
    if not addr:
        return {"status": "ERROR", "reason": "no_address", "balance": None,
                "spendable": None, "ownerCount": None}
    from xrpl.models.requests import AccountInfo  # type: ignore
    try:
        resp = _client().request(AccountInfo(account=addr, ledger_index="validated"))
        data = resp.result.get("account_data") or {}
        if not data:
            # Счёт без резерва в леджере не существует
            return {"status": "NOT_FOUND", "balance": 0.0, "spendable": 0.0, "ownerCount": 0}
        bal = int(data["Balance"]) / DROPS_PER_XRP
        owners = int(data.get("OwnerCount", 0))
        # Полный резерв = базовый + owner-инкремент за каждый объект счёта
        # (трастлайны, ордера…). Плюс запас на комиссию — иначе preview одобрит
        # сумму, на которую в момент отправки не хватит.
        reserve = BASE_RESERVE_XRP + owners * OWNER_RESERVE_XRP
        avail = max(0.0, bal - reserve - MAX_FEE_XRP)
        return {"status": "OK", "balance": bal, "spendable": avail,
                "ownerCount": owners, "reserve": reserve}
    except Exception as e:
        msg = str(e)
        if "actNotFound" in msg or "Account not found" in msg:
            return {"status": "NOT_FOUND", "balance": 0.0, "spendable": 0.0, "ownerCount": 0}
        return {"status": "ERROR", "reason": type(e).__name__, "balance": None,
                "spendable": None, "ownerCount": None}


def get_balance(address: str = None) -> float:
    """Баланс в XRP. Неизвестен (сеть недоступна) → 0.0; для отличия
    «нет средств» от «не знаем» используйте account_state()."""
    st = account_state(address)
    return st["balance"] if st.get("balance") is not None else 0.0


def spendable(address: str = None) -> float:
    """Сколько реально можно отправить: баланс минус полный резерв и комиссия.
    На XRPL нельзя опустошить счёт — резерв обязан остаться. Неизвестно → 0.0
    (фейл-клоуз: лучше отказать в отправке, чем одобрить недоступную сумму)."""
    st = account_state(address)
    return st["spendable"] if st.get("spendable") is not None else 0.0


# ── двухшаговая отправка ─────────────────────────────────────────────────────
def preview_send(destination: str, amount_xrp: float, destination_tag=None) -> Dict[str, Any]:
    """Расчёт отправки. Подтверждается вызовом send(previewId) не позже PREVIEW_TTL."""
    _expire()
    if not _UNLOCKED_SEED:
        raise RuntimeError("wallet_locked")
    classic, tag_from_addr = parse_destination(destination)
    if not classic:
        raise ValueError("invalid_destination")
    # Тег из X-адреса приоритетнее переданного отдельно: он неотделим от адреса
    tag = _norm_tag(tag_from_addr) if tag_from_addr is not None else _norm_tag(destination_tag)
    amount = float(amount_xrp)
    if amount <= 0:
        raise ValueError("invalid_amount")
    if amount > MAX_SEND_XRP:
        raise ValueError("amount_exceeds_max_send")
    avail = spendable()
    if amount > avail:
        raise ValueError(f"insufficient_spendable: доступно {avail:.6f} XRP "
                         f"(баланс минус резерв {BASE_RESERVE_XRP} XRP)")
    pid = uuid.uuid4().hex
    preview = {
        "previewId": pid,
        "destination": classic,
        "destinationTag": tag,
        "amountXrp": amount,
        "createdAt": time.time(),
        "expiresAt": time.time() + PREVIEW_TTL,
    }
    previews = _read_json(XRP_PREVIEWS_PATH, {})
    # чистим протухшие, чтобы файл не рос
    previews = {k: v for k, v in previews.items() if v.get("expiresAt", 0) > time.time()}
    previews[pid] = preview
    _atomic_write(XRP_PREVIEWS_PATH, json.dumps(previews))
    return preview


def send(destination: str, amount_xrp: float, preview_id: str,
         idempotency_key: str = "", destination_tag=None) -> Dict[str, Any]:
    """Отправка XRP. Требует свежий preview и (для авто-выплат) гейт.

    idempotency_key обязателен для авто-выплат: повторный вызов с тем же ключом
    возвращает прежний результат, а не отправляет второй раз.
    """
    # Ключ идемпотентности обязателен: без него повтор после сетевого таймаута
    # отправит те же деньги второй раз.
    if not idempotency_key:
        raise ValueError("idempotency_key_required")
    _expire()
    if not _UNLOCKED_SEED:
        raise RuntimeError("wallet_locked")

    with _proc_lock():
        # Гейт перечитываем ПОД локом: пока процесс ждал лок, оператор мог
        # выключить выплаты — отправлять после этого нельзя.
        if not payouts_enabled():
            raise RuntimeError("xrp_payouts_disabled")

        sends = _read_json_strict(XRP_SENDS_PATH, {})
        prior = sends.get(idempotency_key)
        if prior:
            if prior.get("state") == "in_flight":
                # Прошлая попытка ушла в сеть, но результат не записался (падение
                # процесса/таймаут). Транзакция МОГЛА пройти. Вторую не шлём —
                # нужна сверка в леджере человеком.
                raise RuntimeError(
                    "send_result_unknown: предыдущая отправка по этому ключу не "
                    "завершилась записью результата — проверьте леджер вручную "
                    f"(account={prior.get('account')}, seq≈{prior.get('claimedAt')})")
            return prior

        previews = _read_json(XRP_PREVIEWS_PATH, {})
        pv = previews.get(preview_id)
        if not pv:
            raise ValueError("preview_not_found")
        if pv.get("expiresAt", 0) < time.time():
            raise ValueError("preview_expired")

        classic, tag_from_addr = parse_destination(destination)
        tag = _norm_tag(tag_from_addr) if tag_from_addr is not None else _norm_tag(destination_tag)
        # Параметры обязаны совпасть с подтверждёнными: иначе подтверждали одно,
        # а отправляем другое.
        if classic != pv["destination"] or abs(float(amount_xrp) - pv["amountXrp"]) > 1e-9:
            raise ValueError("preview_mismatch")
        if not _same_tag(pv.get("destinationTag"), tag):
            raise ValueError("preview_tag_mismatch")

        from xrpl.models.transactions import Payment  # type: ignore
        from xrpl.transaction import submit_and_wait  # type: ignore
        from xrpl.utils import xrp_to_drops  # type: ignore

        wallet = _wallet_from_seed(_UNLOCKED_SEED)

        # Durable claim ДО отправки: если процесс упадёт между submit и записью
        # результата, ключ уже помечен in_flight и повторная авто-отправка будет
        # запрещена (fail-closed). flock защищает только живые процессы.
        sends[idempotency_key] = {"state": "in_flight", "account": wallet.classic_address,
                                  "destination": classic, "destinationTag": tag,
                                  "amountXrp": float(amount_xrp), "claimedAt": _now()}
        _atomic_write(XRP_SENDS_PATH, json.dumps(sends))

        kwargs = {
            "account": wallet.classic_address,
            "amount": xrp_to_drops(float(amount_xrp)),
            "destination": classic,
        }
        if tag is not None:
            kwargs["destination_tag"] = tag
        tx = Payment(**kwargs)
        resp = submit_and_wait(tx, _client(), wallet)
        result = resp.result
        engine = (result.get("meta") or {}).get("TransactionResult")
        tx_hash = result.get("hash", "")
        if engine != "tesSUCCESS" or not tx_hash:
            # Сеть дала окончательный отказ — снимаем claim, повтор допустим.
            sends.pop(idempotency_key, None)
            _atomic_write(XRP_SENDS_PATH, json.dumps(sends))
            raise RuntimeError(f"xrp_send_failed: {engine or 'no_txhash'}")
        out = {
            "state": "sent",
            "txHash": tx_hash,
            "destination": classic,
            "destinationTag": tag,
            "amountXrp": float(amount_xrp),
            "sentAt": _now(),
        }
        sends[idempotency_key] = out
        _atomic_write(XRP_SENDS_PATH, json.dumps(sends))
        previews.pop(preview_id, None)
        _atomic_write(XRP_PREVIEWS_PATH, json.dumps(previews))
        with open(XRP_HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        return out
