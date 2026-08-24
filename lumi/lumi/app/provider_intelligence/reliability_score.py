from datetime import datetime, timezone
from typing import List, Optional
from lumi.app.schemas.provider_intelligence import ProviderReliabilityScore

class ProviderReliabilityScorer:
    def __init__(self, usage_tracker):
        self.usage_tracker = usage_tracker
        self._scores = {}
    def compute_score(self, provider_id: str) -> ProviderReliabilityScore:
        summary = self.usage_tracker.get_provider_summary(provider_id)
        records = self.usage_tracker.list_usage(provider_id)
        total = summary.callsTotal
        if total <= 0:
            score = ProviderReliabilityScore(providerId=provider_id, status="unknown", lastUpdatedAt=datetime.now(timezone.utc).isoformat(), warnings=["No usage samples yet"])
            self._scores[provider_id] = score
            return score
        success = summary.callsSucceeded / total
        failure = summary.callsFailed / total
        blocked = summary.callsBlocked / total
        latencies = [r.latencyMs for r in records if getattr(r, "latencyMs", None) is not None]
        avg_latency = sum(latencies) / len(latencies) if latencies else None
        latency_component = 1 - min((avg_latency or 30000) / 60000, 1.0)
        value = (0.45 * success) + (0.25 * (1 - failure)) + (0.20 * (1 - blocked)) + (0.10 * latency_component)
        value = max(0.0, min(1.0, value))
        status = "healthy" if value >= 0.85 else "degraded" if value >= 0.65 else "poor" if value >= 0.40 else "blocked"
        score = ProviderReliabilityScore(providerId=provider_id, status=status, reliabilityScore=round(value,4), successRate=round(success,4), failureRate=round(failure,4), blockedRate=round(blocked,4), averageLatencyMs=round(avg_latency,2) if avg_latency is not None else None, callsTotal=total, callsSucceeded=summary.callsSucceeded, callsFailed=summary.callsFailed, callsBlocked=summary.callsBlocked, lastUpdatedAt=datetime.now(timezone.utc).isoformat())
        self._scores[provider_id] = score
        return score
    def compute_all(self, provider_ids: Optional[List[str]] = None) -> List[ProviderReliabilityScore]:
        if provider_ids is None:
            provider_ids = sorted({r.providerId for r in self.usage_tracker.list_usage()})
        return [self.compute_score(pid) for pid in provider_ids]
