"""Strict freshness check shared by Telegram-authenticated connector flows."""

from __future__ import annotations

import time


def valid_auth_date(raw, *, max_age: int, now: float | None = None, future_skew: int = 30) -> bool:
    try:
        auth_date = int(raw)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else float(now)
    age = current - auth_date
    return auth_date > 0 and age >= -future_skew and (not max_age or age <= max_age)
