import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.provider_intelligence import ProviderBudgetLimits, ProviderFallbackChain, ProviderSelectionRequest, MultiProviderReviewRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix='/provider-intelligence', tags=['provider_intelligence'])
def _err(code, msg): return ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=msg, recoverable=True, details={}, redacted=True).model_dump()
@router.get('/reliability')
async def list_reliability(): return runtime_instance.list_provider_reliability()
@router.get('/reliability/{providerId}')
async def get_reliability(providerId: str): return runtime_instance.compute_provider_reliability(providerId)
@router.get('/quality')
async def list_quality(): return runtime_instance.list_provider_quality()
@router.get('/quality/{providerId}')
async def get_quality(providerId: str): return runtime_instance.compute_provider_quality(providerId)
@router.get('/budget-limits')
async def list_budget_limits(): return runtime_instance.provider_budget_limit_service.list_limits()
@router.get('/budget-limits/{providerId}')
async def get_budget_limits(providerId: str): return runtime_instance.get_provider_budget_limits(providerId)
@router.post('/budget-limits')
async def set_budget_limits(limits: ProviderBudgetLimits): return runtime_instance.set_provider_budget_limits(limits)
@router.get('/fallback-chains')
async def list_fallback_chains(): return runtime_instance.list_provider_fallback_chains()
@router.post('/fallback-chains')
async def create_fallback_chain(chain: ProviderFallbackChain): return runtime_instance.create_provider_fallback_chain(chain)
@router.get('/fallback-chains/{chainId}')
async def get_fallback_chain(chainId: str):
    chain = runtime_instance.provider_fallback_chain_service.get_chain(chainId)
    if not chain: raise HTTPException(status_code=404, detail=_err('CHAIN_NOT_FOUND', f'Chain {chainId} not found'))
    return chain
@router.delete('/fallback-chains/{chainId}')
async def delete_fallback_chain(chainId: str):
    removed = runtime_instance.provider_fallback_chain_service.delete_chain(chainId)
    return {'deleted': bool(removed)}
@router.post('/select')
async def select_providers(request: ProviderSelectionRequest): return runtime_instance.select_providers(request)
@router.post('/review')
async def run_review(request: MultiProviderReviewRequest): return runtime_instance.run_multi_provider_review(request)
@router.post('/report')
async def build_report(providerIds: list[str] | None = None): return runtime_instance.build_provider_comparison_report(providerIds)
@router.get('/latency/{providerId}')
async def get_latency(providerId: str): return runtime_instance.get_provider_latency(providerId)
@router.get('/errors/{providerId}')
async def get_errors(providerId: str): return runtime_instance.get_provider_errors(providerId)
