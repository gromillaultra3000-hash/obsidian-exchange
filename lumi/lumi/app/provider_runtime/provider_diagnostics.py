from lumi.app.schemas.provider_runtime import ProviderDiagnostics
class ProviderDiagnosticsService:
    def __init__(self, config_service, usage_tracker, audit_log=None): self.config_service=config_service; self.usage_tracker=usage_tracker; self.audit_log=audit_log
    def get_diagnostics(self, provider_id):
        c=self.config_service.get_config(provider_id); usage=self.usage_tracker.get_provider_summary(provider_id); warnings=[]
        if not c: return ProviderDiagnostics(providerId=provider_id,status='not_configured',warnings=['Provider runtime not configured'])
        if not c.enabled: warnings.append('Provider is disabled')
        if not c.liveCallsAllowed: warnings.append('Live calls are not allowed')
        if c.authType!='none' and not c.secretRef: warnings.append('Missing secret reference')
        return ProviderDiagnostics(providerId=provider_id,status='configured',configured=True,enabled=c.enabled,liveCallsAllowed=c.liveCallsAllowed,hasSecretRef=bool(c.secretRef),secretStatus=c.secretStatus,baseUrl=c.baseUrl,model=c.model,usage=usage,warnings=warnings)
    def list_diagnostics(self): return [self.get_diagnostics(c.providerId) for c in self.config_service.list_configs()]
