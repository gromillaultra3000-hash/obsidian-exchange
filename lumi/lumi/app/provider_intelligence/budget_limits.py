from lumi.app.schemas.provider_intelligence import ProviderBudgetLimits, ProviderLimitCheckResult

class ProviderBudgetLimitService:
    def __init__(self, audit_log=None):
        self._limits = {}
        self._counters = {}
        self.audit_log = audit_log
    def default_limits(self, provider_id: str):
        return ProviderBudgetLimits(providerId=provider_id)
    def set_limits(self, limits: ProviderBudgetLimits):
        self._limits[limits.providerId] = limits
        if self.audit_log: self.audit_log.add_entry("provider_budget_limits_set", provider_id=limits.providerId, summary=f"Budget limits set for {limits.providerId}")
        return limits
    def get_limits(self, provider_id: str):
        return self._limits.get(provider_id) or self.default_limits(provider_id)
    def list_limits(self):
        return list(self._limits.values())
    def _counter(self, provider_id):
        return self._counters.setdefault(provider_id, {"calls_session":0,"calls_day":0,"tokens_session":0,"tokens_day":0,"failures_session":0,"consecutive_failures":0})
    def check_limits(self, provider_id: str, planned_input_chars: int = 0, planned_tokens: int = 0):
        limits = self.get_limits(provider_id)
        if not limits.enabled:
            return ProviderLimitCheckResult(providerId=provider_id, status="blocked", allowed=False, blockers=["Provider budget limits disabled provider"], counters=self._counter(provider_id))
        c = dict(self._counter(provider_id)); blockers=[]; warnings=[]
        if limits.maxCallsPerSession is not None and c["calls_session"] + 1 > limits.maxCallsPerSession: blockers.append(f"Session call limit exceeded ({limits.maxCallsPerSession})")
        if limits.maxCallsPerDay is not None and c["calls_day"] + 1 > limits.maxCallsPerDay: blockers.append(f"Daily call limit exceeded ({limits.maxCallsPerDay})")
        if limits.maxEstimatedTokensPerSession is not None and c["tokens_session"] + planned_tokens > limits.maxEstimatedTokensPerSession: blockers.append("Session token limit would be exceeded")
        if limits.maxEstimatedTokensPerDay is not None and c["tokens_day"] + planned_tokens > limits.maxEstimatedTokensPerDay: blockers.append("Daily token limit would be exceeded")
        if limits.maxFailuresPerSession is not None and c["failures_session"] >= limits.maxFailuresPerSession: blockers.append("Session failure limit reached")
        if limits.maxConsecutiveFailures is not None and c["consecutive_failures"] >= limits.maxConsecutiveFailures: blockers.append("Consecutive failure limit reached")
        if blockers and self.audit_log: self.audit_log.add_entry("provider_budget_limit_blocked", provider_id=provider_id, summary=f"Budget limit blocked {provider_id}", details={"blockers": blockers})
        return ProviderLimitCheckResult(providerId=provider_id, status="blocked" if blockers else "ok", allowed=not blockers, blockers=blockers, warnings=warnings, counters=c)
    def record_call(self, provider_id: str, estimated_tokens: int = 0, status: str = "completed"):
        c = self._counter(provider_id)
        c["calls_session"] += 1; c["calls_day"] += 1; c["tokens_session"] += int(estimated_tokens or 0); c["tokens_day"] += int(estimated_tokens or 0)
        if status in ("failed","error","blocked"):
            c["failures_session"] += 1; c["consecutive_failures"] += 1
        else:
            c["consecutive_failures"] = 0
    def reset_session_counters(self, provider_id: str | None = None):
        if provider_id: self._counters.pop(provider_id, None)
        else: self._counters.clear()
