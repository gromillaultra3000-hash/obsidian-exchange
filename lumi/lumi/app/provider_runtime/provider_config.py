class ProviderRuntimeConfigService:
    def __init__(self,audit_log=None): self._configs={}; self.audit_log=audit_log
    def get_config(self, provider_id): return self._configs.get(provider_id)
    def set_config(self, config):
        config.liveCallsAllowed = bool(config.liveCallsAllowed) and config.runtimeType in ('mock','local')
        self._configs[config.providerId]=config
        if self.audit_log: self.audit_log.add_entry('provider_runtime_configured', summary=f'Provider runtime configured for {config.providerId}')
        return config
    def list_configs(self): return list(self._configs.values())
    def set_live_calls_allowed(self, provider_id, allowed):
        c=self._configs.get(provider_id)
        if c: c.liveCallsAllowed=bool(allowed)
        return c
