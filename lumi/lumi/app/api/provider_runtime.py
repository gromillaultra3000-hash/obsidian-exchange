import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.provider_runtime import ProviderRuntimeConfig, CreateProviderFromPresetRequest, ProviderConnectionTestRequest, ProviderLiveCallRequest, ModelDiscoveryRequest, BindProviderSecretRequest, CreateProviderSecretRequest
from lumi.app.schemas.errors import ErrorEnvelope
router=APIRouter(prefix='/provider-runtime', tags=['provider_runtime'])
def _err(code,msg): return ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=msg, recoverable=True, details={}, redacted=True).model_dump()
@router.get('/presets')
async def list_presets(): return runtime_instance.list_provider_presets()
@router.get('/presets/{presetId}')
async def get_preset(presetId: str):
    p=runtime_instance.get_provider_preset(presetId)
    if not p: raise HTTPException(status_code=404, detail=_err('PRESET_NOT_FOUND', f'Preset {presetId} not found'))
    return p
@router.post('/providers/from-preset')
async def create_from_preset(request: CreateProviderFromPresetRequest):
    try: return runtime_instance.create_provider_from_preset(request.providerId, request.presetId, request.displayName)
    except ValueError as e: raise HTTPException(status_code=400, detail=_err('PRESET_ERROR', str(e)))
@router.post('/providers/{providerId}/configure')
async def configure_provider(providerId: str, config: ProviderRuntimeConfig):
    config.providerId=providerId
    try: return runtime_instance.configure_provider_runtime(config)
    except ValueError as e: raise HTTPException(status_code=400, detail=_err('CONFIG_ERROR', str(e)))
@router.get('/providers/{providerId}/config')
async def get_provider_config(providerId: str):
    c=runtime_instance.get_provider_runtime_config(providerId)
    if not c: raise HTTPException(status_code=404, detail=_err('CONFIG_NOT_FOUND', 'Runtime config not found'))
    return c
@router.post('/providers/{providerId}/bind-secret')
async def bind_secret(providerId: str, request: BindProviderSecretRequest): return runtime_instance.bind_provider_secret(providerId, request.secretRef)
@router.post('/providers/{providerId}/create-secret')
async def create_secret(providerId: str, request: CreateProviderSecretRequest): return runtime_instance.create_and_bind_provider_secret(providerId, request)
@router.post('/providers/{providerId}/allow-live')
async def allow_live_calls(providerId: str):
    c=runtime_instance.provider_runtime_config_service.set_live_calls_allowed(providerId, True)
    if not c: raise HTTPException(status_code=404, detail=_err('CONFIG_NOT_FOUND','Runtime config not found'))
    return c
@router.post('/providers/{providerId}/disable-live')
async def disable_live_calls(providerId: str):
    c=runtime_instance.provider_runtime_config_service.set_live_calls_allowed(providerId, False)
    if not c: raise HTTPException(status_code=404, detail=_err('CONFIG_NOT_FOUND','Runtime config not found'))
    return c
@router.post('/test-connection')
async def test_connection(request: ProviderConnectionTestRequest): return runtime_instance.test_provider_connection(request)
@router.post('/discover-models')
async def discover_models(request: ModelDiscoveryRequest): return runtime_instance.discover_provider_models(request)
@router.post('/live-call')
async def live_call(request: ProviderLiveCallRequest): return runtime_instance.call_provider_live(request)
@router.get('/providers/{providerId}/diagnostics')
async def get_diagnostics(providerId: str): return runtime_instance.get_provider_diagnostics(providerId)
@router.get('/diagnostics')
async def list_diagnostics(): return runtime_instance.list_provider_diagnostics()
@router.get('/providers/{providerId}/usage')
async def get_usage(providerId: str): return runtime_instance.get_provider_usage(providerId)
@router.get('/usage')
async def list_usage(providerId: str|None=None): return runtime_instance.list_provider_usage(providerId)
