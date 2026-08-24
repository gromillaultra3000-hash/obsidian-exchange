import uuid
from datetime import datetime, timezone
from lumi.app.schemas.provider_runtime import ProviderUsageRecord, ProviderUsageSummary
class ProviderUsageTracker:
    def __init__(self,audit_log=None): self._records={}; self.audit_log=audit_log
    def record_usage(self, provider_id, request_type, input_chars, output_chars, estimated_tokens, latency_ms, status):
        r=ProviderUsageRecord(usageId=str(uuid.uuid4()), providerId=provider_id, createdAt=datetime.now(timezone.utc).isoformat(), requestType=request_type, inputChars=input_chars, outputChars=output_chars, estimatedTokens=estimated_tokens, latencyMs=latency_ms, status=status); self._records[r.usageId]=r; return r
    def get_provider_summary(self, provider_id):
        rs=[r for r in self._records.values() if r.providerId==provider_id]
        return ProviderUsageSummary(providerId=provider_id,callsTotal=len(rs),callsSucceeded=sum(r.status=='completed' for r in rs),callsFailed=sum(r.status=='failed' for r in rs),callsBlocked=sum(r.status=='blocked' for r in rs),inputCharsTotal=sum(r.inputChars for r in rs),outputCharsTotal=sum(r.outputChars for r in rs),estimatedTokensTotal=sum(r.estimatedTokens for r in rs),lastCallAt=rs[-1].createdAt if rs else None)
    def list_usage(self, provider_id=None, limit=100):
        rs=list(self._records.values())
        if provider_id: rs=[r for r in rs if r.providerId==provider_id]
        return rs[:limit]
