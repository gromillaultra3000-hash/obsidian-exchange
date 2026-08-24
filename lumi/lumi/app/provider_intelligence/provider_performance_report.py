import uuid
from datetime import datetime, timezone
from lumi.app.schemas.provider_intelligence import ProviderComparisonReport

class ProviderPerformanceReportBuilder:
    def __init__(self, reliability_scorer, quality_scorer, usage_tracker, fallback_service, budget_service):
        self.reliability_scorer=reliability_scorer; self.quality_scorer=quality_scorer; self.usage_tracker=usage_tracker; self.fallback_service=fallback_service; self.budget_service=budget_service
    def build_report(self, provider_ids=None):
        reliability=self.reliability_scorer.compute_all(provider_ids)
        ids=provider_ids or [r.providerId for r in reliability]
        quality=[self.quality_scorer.compute_quality(pid) for pid in ids]
        usage=[]
        for pid in ids:
            s=self.usage_tracker.get_provider_summary(pid)
            usage.append(s.model_dump() if hasattr(s,'model_dump') else s.dict())
        recommendations=[]
        for r in reliability:
            if r.callsTotal == 0: recommendations.append(f'Provider {r.providerId} has no usage data yet.')
            elif r.reliabilityScore < 0.5: recommendations.append(f'Provider {r.providerId} has low reliability; keep as fallback only.')
        return ProviderComparisonReport(reportId=str(uuid.uuid4()), createdAt=datetime.now(timezone.utc).isoformat(), reliabilityScores=reliability, qualityScores=quality, usageSummaries=usage, fallbackChains=self.fallback_service.list_chains(), recommendations=recommendations)
