import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.security import SetupPasswordRequest, UnlockRequest, SecretCreateRequest, SecretUpdateRequest, SecretResolveRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/security", tags=["security"])

def _err(code, message, status=400):
    raise HTTPException(status_code=status, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, redacted=True).model_dump())

@router.get("/status")
async def security_status(): return runtime_instance.get_security_state()

@router.post("/setup")
async def setup_password(request: SetupPasswordRequest):
    result=runtime_instance.setup_security_password(request)
    if not result.configured: _err("SETUP_ERROR", result.message)
    return result

@router.post("/unlock")
async def unlock(request: UnlockRequest):
    result=runtime_instance.unlock_security(request)
    if not result.unlocked: _err("UNLOCK_FAILED", "Unlock failed", 401)
    return result

@router.post("/lock")
async def lock(): return runtime_instance.lock_security()

@router.get("/sessions")
async def list_sessions(): return runtime_instance.token_manager.list_active_sessions()

@router.post("/sessions/revoke-all")
async def revoke_all_sessions():
    runtime_instance.token_manager.revoke_all(); return {"revoked": True, "message": "All sessions revoked"}

@router.get("/vault/secrets")
async def list_secrets(): return runtime_instance.list_secrets()

@router.post("/vault/secrets")
async def create_secret(request: SecretCreateRequest):
    try: return runtime_instance.create_secret(request)
    except Exception as e: _err("VAULT_ERROR", str(e))

@router.get("/vault/secrets/{secretId}")
async def get_secret(secretId: str):
    secret=runtime_instance.get_secret(secretId)
    if not secret: _err("SECRET_NOT_FOUND", f"Secret {secretId} not found", 404)
    return secret

@router.post("/vault/secrets/{secretId}")
async def update_secret(secretId: str, request: SecretUpdateRequest):
    secret=runtime_instance.update_secret(secretId, request)
    if not secret: _err("SECRET_NOT_FOUND", f"Secret {secretId} not found", 404)
    return secret

@router.delete("/vault/secrets/{secretId}")
async def delete_secret(secretId: str):
    secret=runtime_instance.delete_secret(secretId)
    if not secret: _err("SECRET_NOT_FOUND", f"Secret {secretId} not found", 404)
    return secret

@router.post("/vault/resolve")
async def resolve_secret(request: SecretResolveRequest): return runtime_instance.resolve_secret(request)

@router.get("/audit-summary")
async def security_audit_summary():
    entries=runtime_instance.audit_log.list_entries(); events=[e for e in entries if e.eventType.startswith(("security_","secret_","encryption_","protected_"))]
    return {"totalSecurityEvents": len(events), "recentEvents": [{"eventType": e.eventType, "timestamp": e.timestamp, "summary": e.summary} for e in events[-20:]]}
