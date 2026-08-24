class ProviderConsensusBuilder:
    def build_consensus(self, comparison, provider_results):
        if not provider_results:
            return {"consensusStatus":"no_consensus","recommendedStatus":"SAFE_DEFAULT","confidence":0.0,"notes":["No provider results"],"dissentingProviders":[]}
        statuses=[str(r.get('status','')).lower() for r in provider_results]
        if all(s in ('blocked','failed','error') for s in statuses):
            return {"consensusStatus":"no_consensus","recommendedStatus":"SAFE_DEFAULT","confidence":0.0,"notes":["All providers blocked or failed"],"dissentingProviders":[r.get('providerId') for r in provider_results]}
        high_risk = bool(comparison and comparison.riskFlags)
        if high_risk:
            return {"consensusStatus":"partial","recommendedStatus":"ASK_USER","confidence":0.35,"notes":["Risk flags differ across providers"],"dissentingProviders":[]}
        if comparison and comparison.agreementLevel == 'high':
            return {"consensusStatus":"consensus","recommendedStatus":"WAIT","confidence":0.75,"notes":["Provider outputs agree"],"dissentingProviders":[]}
        return {"consensusStatus":"partial","recommendedStatus":"WAIT","confidence":0.5,"notes":["Consensus is partial or unknown"],"dissentingProviders":[]}
