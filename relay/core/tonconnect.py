"""TON Connect — подключение кошелька клиента вместо ввода адреса руками.

Зачем. Адрес получателя клиент сейчас копирует и вставляет сам. Опечатка в нём
не лечится ничем: перевод уходит в никуда, и это же самый частый повод для
обращения в поддержку. Кошелёк, подключённый по TON Connect, подставляет адрес
сам и доказывает подписью, что этот счёт действительно его.

Что здесь есть и чего здесь НЕТ. Модуль умеет ровно две вещи: собрать манифест
приложения и проверить `ton_proof`. Ключи клиента он не видит и видеть не может
— из кошелька к нам приходит только адрес и подпись.

Главная ловушка этой интеграции — проверка, которая ничего не проверяет.
Кошелёк присылает в одном сообщении и подпись, и публичный ключ, которым её
предлагается проверять. Взять ключ оттуда — значит принять любую подпись: кто
угодно подпишет своим ключом и приложит свой же ключ. Ключ здесь берётся ТОЛЬКО
из блокчейна (`public_key_of`), и если оттуда его получить не удалось, доказа-
тельства нет — вердикт отрицательный, а не «наверное, сойдёт».

Одноразовость payload. Спека советует потреблять nonce атомарно, то есть хра-
нить выданные. Мы вместо хранилища связываем payload с тем, кому он выдан
(`subject` = telegram id из подписанного initData): чужой перехваченный proof
не подойдёт другому клиенту, а свой собственный можно «переиспользовать» только
себе же и только 15 минут. Это осознанно более слабое свойство, чем у хранимого
nonce, и здесь оно достаточно: proof подставляет адрес выдачи в СВОЮ заявку —
подделав его себе, клиент навредит только себе. Если однажды подпись начнёт
что-то РАЗРЕШАТЬ (вход в кабинет, доступ к чужой истории), одного subject станет
мало и потребуется хранимый nonce.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

from core.address import parse_ton_address, ton_friendly_address

# Константы протокола (docs.ton.org + эталонная реализация ton-connect/
# demo-dapp-backend). Порядок байтов здесь не «как принято», а как подписывает
# кошелёк: workchain — big-endian, длина домена и время — little-endian.
PROOF_PREFIX = b"ton-proof-item-v2/"
CONNECT_PREFIX = b"ton-connect"
PROOF_TTL_SEC = 15 * 60          # окно жизни самой подписи
PAYLOAD_TTL_SEC = 15 * 60        # окно жизни выданного нами nonce
CHAIN_MAINNET = "-239"

# Причины отказа. Строкой, а не bool: «подпись не сошлась» и «кошелёк не
# активирован в сети» требуют РАЗНЫХ слов клиенту, а различить их постфактум
# по одному False невозможно.
REASON_TEXT = {
    "ok": "Кошелёк подключён",
    "not_configured": "Подключение кошелька не настроено на сервере",
    "crypto_unavailable": "Сервер не может проверить подпись",
    "bad_request": "Кошелёк прислал неполный ответ",
    "bad_address": "Адрес кошелька не разобран",
    "foreign_chain": "Это кошелёк тестовой сети — нужен основной",
    "foreign_domain": "Подпись выдана для другого сайта",
    "bad_domain_length": "Домен в подписи не совпадает с длиной",
    "bad_payload": "Проверочный код не наш или испорчен",
    "payload_expired": "Проверочный код устарел — начните заново",
    "payload_alien": "Проверочный код выдан другому клиенту",
    "proof_expired": "Подпись устарела — подключите кошелёк заново",
    "proof_from_future": "Время подписи в будущем",
    "pubkey_unavailable": "Кошелёк ещё не активирован в сети — адрес можно ввести вручную",
    "pubkey_mismatch": "Ключ кошелька не совпадает с ключом счёта",
    "bad_signature": "Подпись не подтверждает владение адресом",
}


def reason_text(code: str) -> str:
    return REASON_TEXT.get(code, "Не удалось подтвердить кошелёк")


# ── манифест ─────────────────────────────────────────────────────────────────
def app_base_url() -> str:
    """Адрес приложения. Он же идентификатор dApp для кошельков — поэтому без
    завершающего слэша: с ним кошелёк считает это ДРУГИМ приложением."""
    return (os.getenv("PUBLIC_RELAY") or "https://obsidian-exchange.org").strip().rstrip("/")


def manifest() -> Dict[str, str]:
    base = app_base_url()
    m = {
        "url": base,
        "name": (os.getenv("TONCONNECT_APP_NAME") or "ObsidianExchange").strip(),
        "iconUrl": (os.getenv("TONCONNECT_ICON_URL")
                    or f"{base}/static/img/tonconnect-icon.png").strip(),
        "termsOfUseUrl": f"{base}/offer",
    }
    return m


def manifest_problems(m: Dict[str, Any] = None) -> list:
    """Список претензий к манифесту, пустой = годен.

    Кошелёк на плохой манифест отвечает клиенту безымянной ошибкой подключения,
    и разбираться пришлось бы по скриншоту. Дешевле проверить у себя.
    """
    m = manifest() if m is None else m
    bad = []
    url = str(m.get("url") or "")
    if not url:
        bad.append("url пуст")
    else:
        if not url.startswith("https://"):
            bad.append("url должен быть https")
        if url.endswith("/"):
            bad.append("url без завершающего слэша")
        if not urlparse(url).hostname:
            bad.append("в url нет домена")
    if not str(m.get("name") or "").strip():
        bad.append("name пуст")
    icon = str(m.get("iconUrl") or "")
    if not icon:
        bad.append("iconUrl пуст")
    elif not icon.startswith("https://"):
        bad.append("iconUrl должен быть https")
    elif not icon.lower().split("?")[0].endswith((".png", ".ico")):
        bad.append("iconUrl должен вести на PNG или ICO")
    for opt in ("termsOfUseUrl", "privacyPolicyUrl"):
        v = str(m.get(opt) or "")
        if v and not v.startswith("https://"):
            bad.append(f"{opt} должен быть https")
    return bad


def allowed_domains() -> set:
    """Домены, для которых мы принимаем подпись.

    Подпись выдаётся кошельком КОНКРЕТНОМУ сайту. Принять её от чужого домена
    значит позволить постороннему приложению собирать доказательства и нести их
    нам. Список закрытый: `*` вычёркивается, потому что означает «не проверять».
    """
    doms = {d.strip().lower().lstrip(".")
            for d in (os.getenv("TONCONNECT_DOMAINS") or "").split(",") if d.strip()}
    host = urlparse(app_base_url()).hostname
    if host:
        doms.add(host.lower())
    doms.discard("*")
    return doms


# ── проверочный код (payload) ────────────────────────────────────────────────
def _secret() -> bytes:
    s = (os.getenv("RELAY_SECRET") or "").strip()
    return s.encode() if s and s != "fallback" else b""


def _sign_payload(key: bytes, body: str) -> str:
    return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()[:32]


def make_payload(subject: Any, now: float = None) -> Optional[str]:
    """Одноразовый код для кошелька. None — сервер не настроен (нет RELAY_SECRET).

    `subject` — кому выдан (telegram id из подписанного initData). Он внутри
    подписи, поэтому подменить его нельзя, а сравнить при проверке — можно.
    """
    key = _secret()
    if not key:
        return None
    body = f"{int(now or time.time())}.{_subject_tag(subject)}.{secrets.token_hex(12)}"
    return f"{body}.{_sign_payload(key, body)}"


def _subject_tag(subject: Any) -> str:
    """Короткая метка клиента внутри payload: без разделителей и не пустая."""
    s = str(subject if subject is not None else "").strip()
    return hashlib.sha256(s.encode()).hexdigest()[:12] if s else "anon"


def check_payload(payload: Any, subject: Any, now: float = None,
                  ttl: int = PAYLOAD_TTL_SEC) -> Optional[str]:
    """None — код наш, свежий и выдан этому клиенту. Иначе код причины."""
    key = _secret()
    if not key:
        return "not_configured"
    parts = str(payload or "").split(".")
    if len(parts) != 4:
        return "bad_payload"
    ts_s, subj, nonce, sig = parts
    if not hmac.compare_digest(sig, _sign_payload(key, f"{ts_s}.{subj}.{nonce}")):
        return "bad_payload"
    try:
        ts = int(ts_s)
    except ValueError:
        return "bad_payload"
    now = int(now or time.time())
    if now - ts > ttl:
        return "payload_expired"
    if ts - now > 60:
        return "bad_payload"
    if not hmac.compare_digest(subj, _subject_tag(subject)):
        return "payload_alien"
    return None


# ── подпись ──────────────────────────────────────────────────────────────────
def proof_message(address: str, domain: str, timestamp: int, payload: str) -> Optional[bytes]:
    """Байты, которые подписывал кошелёк. None — адрес не разобран.

    Раскладка задана протоколом и повторена здесь дословно; ошибка в порядке
    байтов не всплывёт как ошибка — она просто даст другую подпись, то есть
    «не подтверждено» на честном кошельке.
    """
    wc, h = parse_ton_address(address)
    if wc is None:
        return None
    dom = str(domain or "").encode("utf-8")
    return (PROOF_PREFIX
            + wc.to_bytes(4, "big", signed=True)
            + h
            + len(dom).to_bytes(4, "little")
            + dom
            + int(timestamp).to_bytes(8, "little")
            + str(payload or "").encode("utf-8"))


def proof_digest(message: bytes) -> bytes:
    """sha256(0xffff ++ "ton-connect" ++ sha256(message)) — то, что реально подписано."""
    return hashlib.sha256(b"\xff\xff" + CONNECT_PREFIX
                          + hashlib.sha256(message).digest()).digest()


def _ed25519_ok(public_key: bytes, signature: bytes, digest: bytes) -> Optional[bool]:
    """True/False — подпись сошлась или нет. None — проверять нечем."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except Exception:
        return None
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, digest)
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


def _verdict(reason: str, address: str = None, **extra) -> Dict[str, Any]:
    v = {"verified": reason == "ok", "reason": reason,
         "message": reason_text(reason), "address": address}
    v.update(extra)
    return v


def verify_proof(account: Dict[str, Any], proof: Dict[str, Any], *,
                 subject: Any,
                 public_key_of: Callable[[str], Optional[bytes]],
                 now: float = None,
                 ttl: int = PROOF_TTL_SEC) -> Dict[str, Any]:
    """Вердикт о владении адресом: {'verified', 'reason', 'message', 'address'}.

    `public_key_of` — единственный источник ключа, и это осознанно параметр:
    ключ обязан приходить из блокчейна, а не из проверяемого сообщения.
    Положительный вердикт возможен ровно одним путём — через сошедшуюся подпись.
    """
    if not isinstance(account, dict) or not isinstance(proof, dict):
        return _verdict("bad_request")

    address = str(account.get("address") or "").strip()
    wc, _h = parse_ton_address(address)
    if wc is None:
        return _verdict("bad_address")

    chain = str(account.get("chain") or CHAIN_MAINNET).strip()
    if chain and chain != CHAIN_MAINNET:
        return _verdict("foreign_chain")

    # Всё, что ниже, — данные из внешнего мира: кошелёк, а то и просто чужой
    # POST. Форму каждого поля проверяем прежде, чем им пользоваться: иначе
    # `domain` строкой вместо объекта превращает отказ в 500, то есть в
    # «у них что-то сломалось» вместо «подпись не принята».
    dom = proof.get("domain")
    if dom is None:
        dom = {}
    if not isinstance(dom, dict):
        return _verdict("bad_request")
    domain_raw = str(dom.get("value") or "")
    if domain_raw.strip().lower() not in allowed_domains():
        return _verdict("foreign_domain")
    # Длину сверяем с ТЕМ ЖЕ значением, что уйдёт в подписываемые байты, — иначе
    # проверка сойдётся на одном, а сообщение соберётся из другого.
    declared = dom.get("lengthBytes")
    if declared is not None:
        try:
            declared = int(declared)
        except (TypeError, ValueError):
            return _verdict("bad_request")
        if declared != len(domain_raw.encode("utf-8")):
            return _verdict("bad_domain_length")

    try:
        ts = int(proof.get("timestamp"))
    except (TypeError, ValueError):
        return _verdict("bad_request")
    now_i = int(now or time.time())
    if ts - now_i > 60:
        return _verdict("proof_from_future")
    if now_i - ts > ttl:
        return _verdict("proof_expired")

    payload = proof.get("payload")
    bad = check_payload(payload, subject, now=now_i)
    if bad:
        return _verdict(bad)

    try:
        signature = base64.b64decode(str(proof.get("signature") or ""), validate=True)
    except Exception:
        return _verdict("bad_signature")
    if len(signature) != 64:
        return _verdict("bad_signature")

    key = public_key_of(address)
    if not key or len(key) != 32:
        return _verdict("pubkey_unavailable")
    # Ключ из ответа кошелька не заменяет цепной, но расхождение с ним —
    # признак того, что нам показывают чужой счёт: говорим об этом отдельно.
    claimed = str(account.get("publicKey") or "").strip()
    if claimed:
        try:
            if bytes.fromhex(claimed) != key:
                return _verdict("pubkey_mismatch")
        except ValueError:
            return _verdict("bad_request")

    message = proof_message(address, dom.get("value"), ts, payload)
    if message is None:
        return _verdict("bad_address")
    ok = _ed25519_ok(key, signature, proof_digest(message))
    if ok is None:
        return _verdict("crypto_unavailable")
    if not ok:
        return _verdict("bad_signature")

    return _verdict("ok", address=ton_friendly_address(address))
