import os
import secrets
import uuid
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from lumi.app.api import health, version, runtime, providers, resolve, audit, capabilities, roles, routing, validation, conflict, policy, actions, history, explainability, dialog, integration, project_scanner, patch_planner, sandbox, ui, persistence, security, provider_runtime, provider_intelligence, localization, launcher, real_apply
from lumi.app.core.errors import LumiError
from lumi.app.schemas.errors import ErrorEnvelope
from lumi.app.providers.redaction import RedactionUtil
from lumi.app.core.runtime import runtime_instance

app = FastAPI(title="Lumi", version="1.7.0")

_KAIROS_SERVICE_PATHS = frozenset({"/conflict/resolve", "/integration/hosts/register"})


def _production_lock_required() -> bool:
    return (os.getenv("LUMI_PROTECTED_RUNTIME_REQUIRED") or "").strip().lower() in {"1", "true", "yes"}


def _kairos_service_allowed(path: str, method: str, authorization: str) -> bool:
    if method != "POST" or path not in _KAIROS_SERVICE_PATHS:
        return False
    configured = (os.getenv("LUMI_KAIROS_TOKEN") or "").strip()
    if len(configured) < 32:
        return False
    supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
    return bool(supplied and secrets.compare_digest(supplied, configured))

def _error_response(code: str, message: str, status_code: int = 400, recoverable: bool = False, details: dict | None = None):
    redactor = RedactionUtil()
    payload = ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, recoverable=recoverable, details=redactor.redact_dict(details or {}), redacted=True).model_dump()
    return JSONResponse(status_code=status_code, content=payload)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    auth_header = request.headers.get("Authorization", "")
    if _kairos_service_allowed(request.url.path, request.method, auth_header):
        return await call_next(request)
    if _production_lock_required():
        # Security mode persisted by the desktop UI must never silently reopen
        # the production sidecar after restart or state import.
        runtime_instance.security_config_service.enable_protected_mode()
    token = auth_header[7:] if auth_header.startswith("Bearer ") else None
    result = runtime_instance.auth_guard.is_request_allowed(request.url.path, request.method, token)
    if not result.get("allowed"):
        return _error_response("UNAUTHORIZED", result.get("reason", "Authentication required"), 401, True, {"status":"locked"})
    return await call_next(request)

@app.exception_handler(LumiError)
async def lumi_error_handler(request: Request, exc: LumiError):
    status = 404 if exc.code.endswith("NOT_FOUND") else 409 if exc.code.endswith("DUPLICATE") else 400
    return _error_response(exc.code, exc.message, status, exc.recoverable, exc.details)

for router in [health.router, version.router, runtime.router, providers.router, resolve.router, audit.router, capabilities.router, roles.router, routing.router, validation.router, conflict.router, policy.router, actions.router, history.router, explainability.router, dialog.router, integration.router, project_scanner.router, patch_planner.router, sandbox.router, ui.router, persistence.router, security.router, provider_runtime.router, provider_intelligence.router, localization.router, launcher.router, real_apply.router]:
    app.include_router(router)
