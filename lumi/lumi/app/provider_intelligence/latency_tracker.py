import uuid
from datetime import datetime, timezone
from typing import Optional

class ProviderLatencyTracker:
    def __init__(self):
        self._records = {}
    def record_latency(self, provider_id: str, latency_ms: int, status: str):
        rec = {"recordId": str(uuid.uuid4()), "providerId": provider_id, "latencyMs": int(latency_ms), "status": status, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._records.setdefault(provider_id, []).append(rec)
        return rec
    def get_average_latency(self, provider_id: str) -> Optional[float]:
        records = self._records.get(provider_id, [])
        return (sum(r["latencyMs"] for r in records) / len(records)) if records else None
    def get_latency_percentiles(self, provider_id: str):
        values = sorted(r["latencyMs"] for r in self._records.get(provider_id, []))
        if not values: return {"p50": None, "p95": None}
        def pct(p): return values[min(len(values)-1, int((len(values)-1)*p))]
        return {"p50": pct(0.5), "p95": pct(0.95)}
    def get_latency_records(self, provider_id: str | None = None):
        if provider_id: return list(self._records.get(provider_id, []))
        return [r for records in self._records.values() for r in records]
