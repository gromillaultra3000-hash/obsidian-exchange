import uuid
from datetime import datetime, timezone
from lumi.app.providers.redaction import RedactionUtil

class ProviderErrorTracker:
    def __init__(self, redaction: RedactionUtil | None = None):
        self._errors = {}
        self.redaction = redaction or RedactionUtil()
    def record_error(self, provider_id: str, error_type: str, safe_message: str):
        safe = self.redaction.redact_value("error", safe_message or "")[:500]
        rec = {"errorId": str(uuid.uuid4()), "providerId": provider_id, "type": error_type, "message": safe, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._errors.setdefault(provider_id, []).append(rec)
        return rec
    def get_error_summary(self, provider_id: str):
        records = self._errors.get(provider_id, [])
        by_type = {}
        for r in records: by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        return {"providerId": provider_id, "total": len(records), "byType": by_type}
    def get_errors(self, provider_id: str, limit: int = 100):
        return sorted(self._errors.get(provider_id, []), key=lambda x: x["timestamp"], reverse=True)[:limit]
    def list_errors(self, provider_id: str | None = None, limit: int = 100):
        records = self.get_errors(provider_id, limit) if provider_id else [r for rs in self._errors.values() for r in rs]
        return records[:limit]
