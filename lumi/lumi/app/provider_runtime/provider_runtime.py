import uuid
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.schemas.provider_runtime import ProviderConnectionTestResult, ProviderLiveCallResult, ModelDiscoveryResult

class ProviderRuntime:
    def __init__(self, runtime, preset_registry, config_service, usage_tracker, audit_log=None, redaction=None):
        self.runtime=runtime; self.preset_registry=preset_registry; self.config_service=config_service; self.usage_tracker=usage_tracker; self.audit_log=audit_log; self.redaction=redaction
    def create_provider_from_preset(self, provider_id, preset_id, display_name=None):
        p=self.preset_registry.get_preset(preset_id)
        if not p: raise ValueError(f'Unknown preset: {preset_id}')
        profile=ProviderProfile(providerId=provider_id, displayName=display_name or p.displayName, providerType=p.runtimeType, apiFormat='json', enabled=False, capabilities=['text_reasoning'], reliabilityScore=0.9, baseUrl=p.defaultBaseUrl, model=p.defaultModel, secretRef=None)
        profile.costProfile={}; profile.latencyProfile={}; profile.roles=[]; profile.notes=None
        try: self.runtime.registry.add_provider(profile)
        except Exception: pass
        if self.audit_log: self.audit_log.add_entry('provider_preset_loaded', summary=f'Provider created from preset {preset_id}: {provider_id}')
        return profile
    def configure_provider(self, config):
        if config.presetId:
            preset=self.preset_registry.get_preset(config.presetId)
            if preset and self.preset_registry.block_console_url(config.baseUrl or ''): raise ValueError(f'Console URL detected. Use API URL: {preset.defaultBaseUrl}')
        return self.config_service.set_config(config)
    def bind_provider_secret(self, provider_id, secret_ref):
        if not secret_ref.startswith('vault://secret/'): raise ValueError('Invalid secret reference format')
        return {'providerId':provider_id,'secretRef':secret_ref,'secretStatus':'configured'}
    def create_and_bind_secret(self, provider_id, request):
        from lumi.app.schemas.security import SecretCreateRequest
        s=self.runtime.secret_vault.create_secret(SecretCreateRequest(name=request.name, value=request.value, kind=request.kind, providerId=provider_id))
        return {'secretId':s.secretId,'secretRef':s.secretRef,'maskedValue':s.maskedValue}
    def test_provider_connection(self, request):
        c=self.config_service.get_config(request.providerId)
        return ProviderConnectionTestResult(testId=str(uuid.uuid4()), providerId=request.providerId, status='configured' if c else 'not_configured', mode=request.mode, connected=bool(c) or request.mode=='metadata_only', message='Configuration validated (no external call made)' if request.mode=='metadata_only' else 'No live test in foundation layer', baseUrl=getattr(c,'baseUrl',None), model=getattr(c,'model',None), warnings=['No live external call performed'])
    def discover_models(self, request):
        c=self.config_service.get_config(request.providerId)
        return ModelDiscoveryResult(providerId=request.providerId, supported=bool(c), status='completed' if c else 'blocked', models=[c.model] if c and c.model else [], warnings=['Model discovery foundation only'])
    def call_provider_live(self, request):
        planned_tokens=max(1, len(request.input or '')//4)
        if hasattr(self.runtime, 'provider_budget_limit_service'):
            budget=self.runtime.provider_budget_limit_service.check_limits(request.providerId, planned_input_chars=len(request.input or ''), planned_tokens=planned_tokens)
            if not budget.allowed:
                if hasattr(self.runtime, 'provider_error_tracker'):
                    self.runtime.provider_error_tracker.record_error(request.providerId, 'budget_blocked', '; '.join(budget.blockers))
                self.usage_tracker.record_usage(request.providerId,'live_call',len(request.input or ''),0,0,None,'blocked')
                return ProviderLiveCallResult(callId=str(uuid.uuid4()), providerId=request.providerId, status='blocked', errors=budget.blockers)
        c=self.config_service.get_config(request.providerId)
        errors=[]
        if not c: errors.append('Provider runtime not configured')
        elif not c.enabled: errors.append('Provider is disabled')
        elif not c.liveCallsAllowed: errors.append('Live calls are not allowed for this provider')
        if errors:
            self.usage_tracker.record_usage(request.providerId,'live_call',len(request.input or ''),0,0,None,'blocked')
            if hasattr(self.runtime, 'provider_budget_limit_service'):
                self.runtime.provider_budget_limit_service.record_call(request.providerId, 0, 'blocked')
            if hasattr(self.runtime, 'provider_error_tracker'):
                self.runtime.provider_error_tracker.record_error(request.providerId, 'live_gate_blocked', '; '.join(errors))
            return ProviderLiveCallResult(callId=str(uuid.uuid4()), providerId=request.providerId, status='blocked', errors=errors)
        # v1.6 keeps real network execution gated. A future layer may enable actual HTTP calls.
        result=ProviderLiveCallResult(callId=str(uuid.uuid4()), providerId=request.providerId, status='blocked', errors=['Real external provider calls remain gated in v1.6 foundation'])
        self.usage_tracker.record_usage(request.providerId,'live_call',len(request.input or ''),0,planned_tokens,None,result.status)
        if hasattr(self.runtime, 'provider_budget_limit_service'):
            self.runtime.provider_budget_limit_service.record_call(request.providerId, planned_tokens, result.status)
        if hasattr(self.runtime, 'provider_error_tracker'):
            self.runtime.provider_error_tracker.record_error(request.providerId, 'live_call_gated', '; '.join(result.errors))
        return result
    def get_diagnostics(self, provider_id): return None
