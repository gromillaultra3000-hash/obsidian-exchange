import re
from typing import Any, Dict

SENSITIVE_KEY_MARKERS = ["apikey", "api_key", "key", "secret", "token", "password", "authorization", "bearer", "secretref"]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(api[_\s-]?key|apikey)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(secret|token|password|passwd)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]+"),
    re.compile(r"(?i)vault:[A-Za-z0-9_\-:.]+"),
]


class RedactionUtil:
    def __init__(self, mask: str = "***REDACTED***"):
        self.mask = mask

    def redact_dict(self, data: Dict[str, Any] | None) -> Dict[str, Any]:
        if data is None:
            return {}
        result: Dict[str, Any] = {}
        for key, value in data.items():
            if self._is_sensitive_key(key):
                result[key] = self.mask
            else:
                result[key] = self.redact_any(value)
        return result

    def redact_any(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self.redact_dict(value)
        if isinstance(value, list):
            return [self.redact_any(v) for v in value]
        if isinstance(value, str):
            return self.redact_secret_like(value)
        return value

    def redact_model(self, model) -> dict:
        if hasattr(model, "model_dump"):
            return self.redact_dict(model.model_dump())
        if hasattr(model, "dict"):
            return self.redact_dict(model.dict())
        if isinstance(model, dict):
            return self.redact_dict(model)
        return {"value": self.redact_any(model)}

    def redact_value(self, key: str, value: Any) -> Any:
        if self._is_sensitive_key(key):
            return self.mask
        return self.redact_any(value)

    def redact_secret_like(self, text: str) -> str:
        redacted = text
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub(self.mask, redacted)
        return redacted

    def _is_sensitive_key(self, key: str) -> bool:
        key_lower = key.lower()
        return any(marker in key_lower for marker in SENSITIVE_KEY_MARKERS)
