class ProviderIntelligenceRuntime:
    def __init__(self, reliability_scorer, quality_scorer, latency_tracker, error_tracker, budget_limits, fallback_chain, selection_policy, comparator, consensus_builder, multi_review, report_builder, audit_log):
        self.reliability_scorer=reliability_scorer; self.quality_scorer=quality_scorer; self.latency_tracker=latency_tracker; self.error_tracker=error_tracker; self.budget_limits=budget_limits; self.fallback_chain=fallback_chain; self.selection_policy=selection_policy; self.comparator=comparator; self.consensus_builder=consensus_builder; self.multi_review=multi_review; self.report_builder=report_builder; self.audit_log=audit_log
    def compute_reliability(self, provider_id): return self.reliability_scorer.compute_score(provider_id)
    def list_reliability(self): return self.reliability_scorer.compute_all()
    def record_quality_sample(self,*a,**k): return self.quality_scorer.record_sample(*a,**k)
    def compute_quality(self, provider_id): return self.quality_scorer.compute_quality(provider_id)
    def list_quality(self): return self.quality_scorer.list_quality_scores()
    def set_budget_limits(self, limits): return self.budget_limits.set_limits(limits)
    def get_budget_limits(self, provider_id): return self.budget_limits.get_limits(provider_id)
    def check_budget_limits(self, provider_id, planned_input_chars=0, planned_tokens=0): return self.budget_limits.check_limits(provider_id, planned_input_chars, planned_tokens)
    def create_fallback_chain(self, chain): return self.fallback_chain.create_chain(chain)
    def list_fallback_chains(self): return self.fallback_chain.list_chains()
    def select_providers(self, request): return self.selection_policy.select_providers(request)
    def run_multi_provider_review(self, request): return self.multi_review.run_review(request)
    def build_provider_report(self, provider_ids=None): return self.report_builder.build_report(provider_ids)
