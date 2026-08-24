from datetime import datetime, timezone
from typing import Optional, List
from lumi.app.schemas.provider_intelligence import ProviderQualityScore

class ProviderQualityScorer:
    def __init__(self, audit_log=None):
        self._samples = {}
        self._scores = {}
        self.audit_log = audit_log
    def record_sample(self, provider_id: str, validation_status: str, confidence: float, risk_flags: Optional[list] = None, empty: bool = False, malformed: bool = False, conflict: bool = False):
        sample = {"validation_status": validation_status, "confidence": max(0.0, min(1.0, float(confidence or 0.0))), "risk_flags": risk_flags or [], "empty": bool(empty), "malformed": bool(malformed), "conflict": bool(conflict), "timestamp": datetime.now(timezone.utc).isoformat()}
        self._samples.setdefault(provider_id, []).append(sample)
        if self.audit_log:
            self.audit_log.add_entry("provider_quality_sample_recorded", provider_id=provider_id, summary=f"Quality sample recorded for {provider_id}")
    def compute_quality(self, provider_id: str) -> ProviderQualityScore:
        samples = self._samples.get(provider_id, [])
        if not samples:
            score = ProviderQualityScore(providerId=provider_id, samplesCount=0, lastUpdatedAt=datetime.now(timezone.utc).isoformat(), warnings=["No quality samples yet"])
            self._scores[provider_id] = score
            return score
        n = len(samples)
        pass_count = sum(1 for s in samples if s["validation_status"] in ("valid", "degraded", "accepted", "success"))
        avg_conf = sum(s["confidence"] for s in samples) / n
        unsafe = sum(1 for s in samples if any("unsafe" in str(r).lower() or "secret" in str(r).lower() for r in s["risk_flags"])) / n
        empty = sum(1 for s in samples if s["empty"]) / n
        malformed = sum(1 for s in samples if s["malformed"]) / n
        conflict = sum(1 for s in samples if s["conflict"]) / n
        q = 0.30*(pass_count/n) + 0.20*avg_conf + 0.20*(1-unsafe) + 0.10*(1-empty) + 0.10*(1-malformed) + 0.10*(1-conflict)
        q = max(0.0, min(1.0, q))
        score = ProviderQualityScore(providerId=provider_id, qualityScore=round(q,4), validationPassRate=round(pass_count/n,4), averageConfidence=round(avg_conf,4), unsafeOutputRate=round(unsafe,4), emptyOutputRate=round(empty,4), malformedOutputRate=round(malformed,4), conflictRate=round(conflict,4), samplesCount=n, lastUpdatedAt=datetime.now(timezone.utc).isoformat())
        self._scores[provider_id] = score
        return score
    def list_quality_scores(self) -> List[ProviderQualityScore]:
        ids = set(self._samples) | set(self._scores)
        return [self.compute_quality(pid) for pid in sorted(ids)]
