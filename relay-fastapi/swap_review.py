"""Short-lived, session-bound approvals for website swap creation.

This intentionally uses process memory: a restart invalidates approvals and a
second worker cannot redeem them. No provider operation happens in this module.
"""

from decimal import Decimal, InvalidOperation
import hashlib
import secrets
import threading
import time


def _number(value, *, positive=False):
    if value is None or isinstance(value, bool):
        raise ValueError("Invalid quote number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid quote number") from None
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError("Invalid quote number")
    return number


def _fields(fields):
    try:
        values = tuple(fields[key] for key in ("coin_from", "coin_to", "address"))
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("Invalid swap fields")
        return (*values, _number(fields["amount"], positive=True))
    except (KeyError, TypeError):
        raise ValueError("Invalid swap fields") from None


def _owner(owner):
    if not isinstance(owner, str) or not owner:
        raise ValueError("Invalid review owner")
    return hashlib.sha256(owner.encode("utf-8")).digest()


def _quote(rate_info, amount):
    if not isinstance(rate_info, dict) or "error" in rate_info:
        raise ValueError("Invalid provider quote")
    quote = {}
    for name in ("estimated_receive", "rate", "min_amount", "max_amount", "withdraw_fee"):
        value = rate_info.get(name)
        required = name in ("estimated_receive", "rate")
        quote[name] = (
            _number(value, positive=required or name == "max_amount")
            if value is not None or required else None
        )
    minimum, maximum = quote["min_amount"], quote["max_amount"]
    if minimum is not None and amount < minimum:
        raise ValueError("Swap amount below provider minimum")
    if maximum is not None and amount > maximum:
        raise ValueError("Swap amount above provider maximum")
    return {key: str(value) if value is not None else None for key, value in quote.items()}


class SwapReviewCache:
    def __init__(self, *, ttl=120, max_entries=256, clock=time.monotonic):
        if not 0 < ttl <= 120 or not 0 < max_entries <= 256:
            raise ValueError("Invalid cache limits")
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = {}

    def _expire(self, now):
        for token in [key for key, entry in self._entries.items() if entry[0] <= now]:
            del self._entries[token]

    def issue(self, owner, fields, rate_info):
        """Create a review; owner must include authenticated user and session."""
        binding, validated = _owner(owner), _fields(fields)
        quote = _quote(rate_info, validated[-1])
        with self._lock:
            now = self._clock()
            self._expire(now)
            if len(self._entries) >= self.max_entries:
                raise ValueError("Too many pending swap reviews")
            token = secrets.token_urlsafe(32)
            while token in self._entries:
                token = secrets.token_urlsafe(32)
            self._entries[token] = (now + self.ttl, binding, validated, quote)
        return {"token": token, "quote": dict(quote), "ttl": self.ttl}

    def consume(self, token, owner, fields):
        """Redeem exactly once; invalid/expired reviews raise ValueError."""
        binding, validated = _owner(owner), _fields(fields)
        if not isinstance(token, str):
            raise ValueError("Invalid swap review")
        with self._lock:
            self._expire(self._clock())
            entry = self._entries.get(token)
            if entry is None or entry[1] != binding or entry[2] != validated:
                raise ValueError("Swap review expired or changed")
            del self._entries[token]
            return dict(entry[3])
