import uuid
from typing import List
from lumi.app.schemas.provider_intelligence import ProviderFallbackChain

class ProviderFallbackChainService:
    def __init__(self, audit_log=None):
        self._chains = {}
        self.audit_log = audit_log
    def create_chain(self, chain: ProviderFallbackChain):
        if not chain.chainId: chain.chainId = str(uuid.uuid4())
        self._chains[chain.chainId] = chain
        if self.audit_log: self.audit_log.add_entry("provider_fallback_chain_created", summary=f"Fallback chain {chain.chainId} created")
        return chain
    def get_chain(self, chain_id: str): return self._chains.get(chain_id)
    def list_chains(self) -> List[ProviderFallbackChain]: return list(self._chains.values())
    def update_chain(self, chain_id: str, chain: ProviderFallbackChain):
        chain.chainId = chain_id; self._chains[chain_id] = chain; return chain
    def delete_chain(self, chain_id: str):
        removed = self._chains.pop(chain_id, None)
        if removed and self.audit_log: self.audit_log.add_entry("provider_fallback_chain_deleted", summary=f"Fallback chain {chain_id} deleted")
        return removed
    def build_default_chain(self, provider_ids, strategy="balanced"):
        return self.create_chain(ProviderFallbackChain(chainId=str(uuid.uuid4()), displayName="Default fallback chain", providerIds=list(provider_ids), strategy=strategy))
    def resolve_chain(self, chain_id: str, provider_registry=None, config_service=None):
        chain = self._chains.get(chain_id)
        if not chain or not chain.enabled: return []
        result=[]
        for pid in chain.providerIds:
            include=True
            if provider_registry is not None:
                try: include = bool(provider_registry.get_provider(pid).enabled)
                except Exception: include=False
            if include: result.append(pid)
        return result[:max(1, chain.maxProvidersToTry)]
