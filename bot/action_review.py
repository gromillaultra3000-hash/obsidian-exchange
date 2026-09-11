"""Bounded, process-local approvals for the exact action shown to a user.

Restarting the process invalidates approvals. Redeem before any side effect;
an uncertain provider result must never restore a consumed approval.
"""

import hashlib
import json
import secrets
import threading
import time


def _binding(owner, fields):
    if not isinstance(owner, str) or not owner or not isinstance(fields, dict):
        raise ValueError("Invalid action review fields")

    def validate(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("Review keys must be strings")
                validate(item)
        elif isinstance(value, list):
            for item in value:
                validate(item)
        elif value is not None and type(value) not in (str, int, float, bool):
            raise ValueError("Review fields must be JSON values")

    try:
        validate(fields)
        snapshot = json.dumps(
            [owner, fields], sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        raise ValueError("Invalid action review fields") from None
    if len(snapshot) > 8192:
        raise ValueError("Action review is too large")
    return hashlib.sha256(snapshot).digest()


class ActionReviewCache:
    def __init__(self, *, ttl=120, max_entries=256, clock=time.monotonic):
        if not 0 < ttl <= 120 or not isinstance(max_entries, int) or not 0 < max_entries <= 256:
            raise ValueError("Invalid cache limits")
        self.ttl = ttl
        self.max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = {}

    def _expire(self, now):
        for token in [key for key, entry in self._entries.items() if entry[0] <= now]:
            del self._entries[token]

    def issue(self, owner: str, fields: dict) -> str:
        binding = _binding(owner, fields)
        with self._lock:
            now = self._clock()
            self._expire(now)
            if len(self._entries) >= self.max_entries:
                raise ValueError("Too many pending action reviews")
            token = secrets.token_urlsafe(24)
            while token in self._entries:
                token = secrets.token_urlsafe(24)
            self._entries[token] = (now + self.ttl, binding)
            return token

    def consume(self, token: str, owner: str, fields: dict) -> bool:
        """Return True exactly once; stale, changed or unknown approvals fail."""
        binding = _binding(owner, fields)
        if not isinstance(token, str):
            raise ValueError("Invalid action review token")
        with self._lock:
            self._expire(self._clock())
            entry = self._entries.get(token)
            if entry is None or not secrets.compare_digest(entry[1], binding):
                raise ValueError("Action review expired or changed")
            del self._entries[token]
            return True
