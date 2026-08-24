import uuid
from lumi.app.schemas.provider_intelligence import MultiProviderReviewRequest, MultiProviderReviewResult, ProviderSelectionRequest
from lumi.app.schemas.provider_runtime import ProviderLiveCallRequest
from lumi.app.providers.mock_adapter import MockProviderAdapter

class MultiProviderReviewRuntime:
    def __init__(self, runtime, selection_policy, budget_limits, comparator, consensus_builder, reliability_scorer, quality_scorer, latency_tracker, error_tracker, audit_log, redaction):
        self.runtime=runtime; self.selection_policy=selection_policy; self.budget_limits=budget_limits; self.comparator=comparator; self.consensus_builder=consensus_builder; self.reliability_scorer=reliability_scorer; self.quality_scorer=quality_scorer; self.latency_tracker=latency_tracker; self.error_tracker=error_tracker; self.audit_log=audit_log; self.redaction=redaction
    def run_review(self, request: MultiProviderReviewRequest):
        review_id=request.reviewId or str(uuid.uuid4())
        if self.audit_log: self.audit_log.add_entry('multi_provider_review_requested', summary=f'Review {review_id} requested', details={'mode':request.mode})
        sel=self.selection_policy.select_providers(ProviderSelectionRequest(candidateProviderIds=request.providerIds, strategy=request.strategy, metadata={'reviewId':review_id}))
        selected=sel.selectedProviderIds[:max(1, min(request.maxProviders, 8))]
        if not selected:
            return MultiProviderReviewResult(reviewId=review_id, status='blocked', mode=request.mode, errors=['No providers available'], warnings=sel.warnings)
        results=[]
        outputs=[]
        for pid in selected:
            if request.mode == 'metadata_only':
                rel=self.reliability_scorer.compute_score(pid); qual=self.quality_scorer.compute_quality(pid); budget=self.budget_limits.check_limits(pid)
                results.append({'providerId':pid,'status':'metadata_only','reliabilityScore':rel.reliabilityScore,'qualityScore':qual.qualityScore,'budgetStatus':budget.status})
            elif request.mode == 'mock_only':
                try:
                    profile=self.runtime.registry.get_provider(pid)
                    out=MockProviderAdapter(self.redaction).invoke(type('Task', (), {'input': request.input, 'taskType': 'review', 'requirements': {}, 'metadata': {}})(), profile)
                    od=out.model_dump() if hasattr(out,'model_dump') else out.dict()
                    results.append({'providerId':pid,'status':od.get('status','success'),'output':od})
                    outputs.append(od)
                except Exception as e:
                    msg=self.redaction.redact_value('error', str(e))
                    results.append({'providerId':pid,'status':'failed','errors':[msg]})
            elif request.mode in ('live_if_allowed','live_required'):
                config=self.runtime.provider_runtime_config_service.get_config(pid)
                budget=self.budget_limits.check_limits(pid, planned_input_chars=len(request.input or ''), planned_tokens=max(1,len(request.input or '')//4))
                if not budget.allowed:
                    results.append({'providerId':pid,'status':'blocked','errors':budget.blockers}); continue
                if not config or not config.liveCallsAllowed:
                    results.append({'providerId':pid,'status':'blocked' if request.mode=='live_required' else 'skipped','errors':['Live calls not allowed']}); continue
                live=self.runtime.call_provider_live(ProviderLiveCallRequest(providerId=pid, input=request.input, taskType='multi_provider_review', metadata={'reviewId':review_id}))
                nd=live.normalizedOutput or {}
                results.append({'providerId':pid,'status':live.status,'output':nd,'errors':live.errors})
                if nd: outputs.append(nd)
        comparison=self.comparator.compare_outputs(outputs) if outputs else None
        consensus=self.consensus_builder.build_consensus(comparison, results)
        if any(r.get('status') in ('completed','success','metadata_only') for r in results): status='completed'
        elif any(r.get('status') in ('blocked','skipped') for r in results): status='blocked'
        else: status='failed'
        if any(r.get('status') in ('blocked','failed','skipped') for r in results) and any(r.get('status') in ('completed','success','metadata_only') for r in results): status='partial'
        if self.audit_log: self.audit_log.add_entry('multi_provider_review_completed', summary=f'Review {review_id} completed', details={'status':status})
        return MultiProviderReviewResult(reviewId=review_id, status=status, mode=request.mode, providerResults=self.redaction.redact_value('providerResults', results) if hasattr(self.redaction,'redact_value') else results, comparison=comparison, consensus=consensus, selectedProviderId=(comparison.recommendedProviderId if comparison else (selected[0] if selected else None)))
