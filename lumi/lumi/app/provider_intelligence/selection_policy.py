from lumi.app.schemas.provider_intelligence import ProviderSelectionRequest, ProviderSelectionResult

class ProviderSelectionPolicy:
    def __init__(self, provider_registry, config_service, reliability_scorer, quality_scorer, budget_limit_service):
        self.provider_registry=provider_registry; self.config_service=config_service; self.reliability_scorer=reliability_scorer; self.quality_scorer=quality_scorer; self.budget_limit_service=budget_limit_service
    def select_providers(self, request: ProviderSelectionRequest):
        try: all_ids=[p.providerId for p in self.provider_registry.list_providers() if getattr(p,'enabled',False)]
        except Exception: all_ids=[]
        candidates = request.candidateProviderIds or all_ids
        exclude=set(request.excludeProviderIds or [])
        ordered=[]; warnings=[]
        for pid in candidates:
            if pid in exclude: continue
            try: profile=self.provider_registry.get_provider(pid)
            except Exception: continue
            if not getattr(profile, 'enabled', False): continue
            config=self.config_service.get_config(pid)
            if config is not None and not config.enabled: continue
            budget=self.budget_limit_service.check_limits(pid)
            if not budget.allowed: continue
            rel=self.reliability_scorer.compute_score(pid); qual=self.quality_scorer.compute_quality(pid)
            latency=rel.averageLatencyMs if rel.averageLatencyMs is not None else 60000
            latency_score=max(0.0, 1.0-min(latency/60000,1.0))
            capability_score=1.0
            if request.requiredCapabilities:
                caps=set(getattr(profile,'capabilities',[]) or [])
                capability_score=len(set(request.requiredCapabilities)&caps)/max(1,len(request.requiredCapabilities))
            budget_score=1.0 if budget.allowed else 0.0
            balanced=0.35*rel.reliabilityScore+0.35*qual.qualityScore+0.15*latency_score+0.10*budget_score+0.05*capability_score
            ordered.append({"providerId":pid,"score":round(balanced,4),"reliability":rel.reliabilityScore,"quality":qual.qualityScore,"latencyScore":round(latency_score,4),"budgetStatus":budget.status})
        if request.strategy == 'highest_reliability': ordered.sort(key=lambda x:x['reliability'], reverse=True)
        elif request.strategy == 'lowest_latency': ordered.sort(key=lambda x:x['latencyScore'], reverse=True)
        elif request.strategy == 'manual': pass
        else: ordered.sort(key=lambda x:x['score'], reverse=True)
        if not ordered: warnings.append('No selectable providers')
        return ProviderSelectionResult(selectedProviderIds=[x['providerId'] for x in ordered], orderedCandidates=ordered, strategy=request.strategy, warnings=warnings)
