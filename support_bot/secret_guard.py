"""Детектор секретов для клиентских сообщений (перенос из LUMI OnboardingSecretGuard
+ крипто-расширения Kairos, настроено под обменник и русскую аудиторию).

Замысел (fail-closed по приватным данным): клиент НЕ должен присылать в поддержку
seed-фразу, приватный ключ, пароль от кабинета и т.п. — если прислал, сообщение НЕ
пересылается сотрудникам и НЕ пишется в support.db, а клиента просят убрать секрет.
Так закрывается риск утечки ключей в чат/логи реальным механизмом, а не только текстом
предупреждения.

Ключевое отличие от наивного детектора — защита от ложных срабатываний:
- 64-hex (это может быть txid, который клиент законно присылает в вопросе) считается
  секретом ТОЛЬКО рядом с ключевым словом «ключ/key/seed/приват…»;
- seed-фраза детектится строго по форме BIP-39 (12/15/18/21/24 коротких латинских слова),
  а не «любые 12 слов подряд» — иначе ловили бы обычные английские фразы.

API:
    contains_secret(text) -> bool          # блокировать пересылку?
    secret_reason(text)   -> str | None    # что именно нашли (для лога, без самого секрета)
    redact(text)          -> str           # замаскировать секреты в строке (для логов)
"""
from __future__ import annotations
import re

# --- формы приватных данных ---
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I)
# key=value / key: value с секретным именем (лат. + рус.)
_KV = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd|mnemonic|seed[_-]?phrase|"
    r"private[_ ]?key|priv[_-]?key|пароль|сид|мнемоник\w*|приватн\w+\s+ключ)\s*[:=]\s*\S{4,}"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]{16,}")
# крипто-ключи с однозначным префиксом
_XKEY = re.compile(r"\b(xprv|xpub)[a-km-zA-HJ-NP-Z1-9]{50,}\b")
_WIF = re.compile(r"\b[5KL][1-9A-HJ-NP-Za-km-z]{50,51}\b")
# 64-hex рядом с секретным словом (иначе это может быть txid — не трогаем)
_HEX64_CTX = re.compile(
    r"(?i)(ключ|key|seed|сид|приват|privat|мнемон|mnemon|секрет|secret)\D{0,40}"
    r"\b(0x)?[0-9a-f]{64}\b"
)
# seed-фраза BIP-39: 12/15/18/21/24 латинских слова по 3-8 букв, через один пробел
_BIP39 = re.compile(r"(?i)\b(?:[a-z]{3,8}\s+){11,23}[a-z]{3,8}\b")


def _bip39_hit(text: str) -> bool:
    for m in _BIP39.finditer(text):
        words = m.group(0).split()
        if len(words) in (12, 15, 18, 21, 24):
            return True
    return False


_CHECKS = [
    ("pem_private_key", lambda t: bool(_PEM.search(t))),
    ("credential_kv", lambda t: bool(_KV.search(t))),
    ("bearer_token", lambda t: bool(_BEARER.search(t))),
    ("hd_key", lambda t: bool(_XKEY.search(t))),
    ("wif_key", lambda t: bool(_WIF.search(t))),
    ("hex_privkey", lambda t: bool(_HEX64_CTX.search(t))),
    ("seed_phrase", _bip39_hit),
]


def secret_reason(text: str | None) -> str | None:
    """Вернёт короткий код найденного секрета (без самого секрета) или None."""
    if not text:
        return None
    for name, fn in _CHECKS:
        try:
            if fn(text):
                return name
        except Exception:
            continue
    return None


def contains_secret(text: str | None) -> bool:
    return secret_reason(text) is not None


def redact(text: str | None) -> str:
    """Заменить найденные секреты на [REDACTED] — для безопасного логирования."""
    if not text:
        return text or ""
    out = text
    for rx in (_PEM, _KV, _BEARER, _XKEY, _WIF, _HEX64_CTX):
        out = rx.sub("[REDACTED]", out)
    for m in list(_BIP39.finditer(out)):
        if len(m.group(0).split()) in (12, 15, 18, 21, 24):
            out = out.replace(m.group(0), "[REDACTED seed phrase]")
    return out
