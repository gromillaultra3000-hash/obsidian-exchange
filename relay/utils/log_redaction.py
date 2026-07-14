"""
Централизованная редакция секретов в логах (паттерн Lumi).

Маскирует в тексте лог-записей: Bearer-токены, API-ключи/присвоения, длинные
hex-ключи/хэши (≥32), номера карт (16–19 цифр), телефоны РФ, TRON-адреса.
Оставляет несколько символов по краям — по логам можно ориентироваться, но
сам секрет не утекает. Устанавливается на root-logger и его хендлеры разово.

Подключение (в начале сервиса, после настройки логирования):
    from utils.log_redaction import install_redaction
    install_redaction()
"""
import re
import logging

_installed = False


def _mask(s: str, keep: int = 3) -> str:
    if not s:
        return s
    if len(s) <= keep * 2:
        return "***"
    return f"{s[:keep]}…{s[-keep:]}"


# (regex, функция замены) — компилируются один раз
_PATTERNS = [
    # Bearer <token>
    (re.compile(r'(?i)(bearer\s+)([A-Za-z0-9._\-]{8,})'),
     lambda m: m.group(1) + _mask(m.group(2))),
    # api_key=..., token: "...", secret=... и т.п.
    (re.compile(r'(?i)((?:api[_-]?key|api[_-]?token|secret|token|password|access[_-]?token)'
                r'["\']?\s*[:=]\s*["\']?)([A-Za-z0-9._\-]{6,})'),
     lambda m: m.group(1) + _mask(m.group(2))),
    # длинные hex — ключи/хэши/токены (XPAY/montera/notification и пр.)
    (re.compile(r'\b[0-9a-fA-F]{32,}\b'), lambda m: _mask(m.group(0), 4)),
    # номера карт 16–19 цифр
    (re.compile(r'\b\d{16,19}\b'), lambda m: _mask(m.group(0), 4)),
    # телефоны РФ (7/8 + 10 цифр)
    (re.compile(r'\b[78]\d{10}\b'), lambda m: _mask(m.group(0), 3)),
    # TRON-адреса
    (re.compile(r'\bT[1-9A-HJ-NP-Za-km-z]{33}\b'), lambda m: _mask(m.group(0), 4)),
]


def redact(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    try:
        for rx, repl in _PATTERNS:
            text = rx.sub(repl, text)
    except Exception:
        pass
    return text


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # маскируем уже отформатированное сообщение (учитывает %-args)
            msg = record.getMessage()
            red = redact(msg)
            if red != msg:
                record.msg = red
                record.args = ()
        except Exception:
            pass
        return True


def install_redaction():
    """Идемпотентно вешает фильтр на root-logger и его хендлеры."""
    global _installed
    if _installed:
        return
    f = RedactionFilter()
    root = logging.getLogger()
    root.addFilter(f)
    for h in list(root.handlers):
        try:
            h.addFilter(f)
        except Exception:
            pass
    _installed = True
