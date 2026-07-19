"""Recurring-failure паттерны провайдеров (перенос идеи LUMI PatternEngine.recurring).

Причины сбоев провайдеров в БД не хранятся (payment_sessions.failed → пустой payload),
зато есть в структурном логе payment_service: /root/relay/logs/relay.log. Здесь мы
читаем ОГРАНИЧЕННЫЙ хвост лога, извлекаем события отказа (провайдер + нормализованная
причина), группируем в паттерны с частотой/severity/confidence.

Честно: это association (корреляция повторов), НЕ причинность. Advisory — на роутинг
не влияет.
"""
from __future__ import annotations
import re
import time
from collections import defaultdict

LOG_PATH = "/root/relay/logs/relay.log"
_TAIL_BYTES = 1_500_000          # читаем последние ~1.5 МБ (bounded)
_CACHE = {"ts": 0.0, "data": None}
_TTL = 120

# Сигнатуры строк отказа: (regex, группа_провайдера, группа_причины)
_PATTERNS = [
    re.compile(r"(\w+) тоже не выдал реквизиты для order \d+: (.+)$"),
    re.compile(r"Эскалаци[яю] order \d+ на (\w+): (.+)$"),
    re.compile(r"providers\.(\w+) - ERROR - .*?'message': '([^']+)'"),
]
_PRIMARY = re.compile(r"Попытка \d+/\d+ для order \d+ не удалась: (.+)$")


def _norm_reason(r: str) -> str:
    r = r.strip().rstrip(".")
    r = re.sub(r"\s+", " ", r)
    # укоротить до устойчивой сигнатуры
    low = r.lower()
    if "не найден" in low or "подходящ" in low:
        return "нет подходящих реквизитов"
    if "не удалось выдать" in low:
        return "не удалось выдать сделку"
    if "нет свободных" in low:
        return "нет свободных реквизитов"
    if "заблокир" in low:
        return "мерчант заблокирован"
    if "timeout" in low or "read timed out" in low:
        return "таймаут провайдера"
    if "auth" in low or "401" in low or "403" in low:
        return "ошибка авторизации/доступа"
    return r[:60]


def _severity(n: int) -> str:
    return "high" if n >= 15 else "medium" if n >= 5 else "low"


def provider_failure_patterns(force: bool = False) -> dict:
    now = time.time()
    if not force and _CACHE["data"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["data"]

    counts = defaultdict(int)          # (provider, reason) -> count
    try:
        with open(LOG_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - _TAIL_BYTES))
            chunk = f.read().decode("utf-8", "replace")
    except Exception as e:
        return {"error": str(e), "patterns": [], "total_failures": 0}

    for line in chunk.splitlines():
        matched = False
        for rx in _PATTERNS:
            m = rx.search(line)
            if m:
                prov, reason = m.group(1), _norm_reason(m.group(2))
                counts[(prov.lower(), reason)] += 1
                matched = True
                break
        if not matched:
            mp = _PRIMARY.search(line)
            if mp:
                counts[("(основной)", _norm_reason(mp.group(1)))] += 1

    patterns = [
        {
            "provider": prov,
            "reason": reason,
            "count": n,
            "severity": _severity(n),
            "confidence": round(min(0.95, 0.45 + 0.05 * n), 2),
            "note": "association, не причинность",
        }
        for (prov, reason), n in counts.items()
    ]
    patterns.sort(key=lambda p: -p["count"])
    result = {
        "patterns": patterns[:20],
        "total_failures": sum(counts.values()),
        "window": "хвост лога payment_service (~1.5МБ)",
    }
    _CACHE["ts"] = now
    _CACHE["data"] = result
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(provider_failure_patterns(force=True), ensure_ascii=False, indent=2))
