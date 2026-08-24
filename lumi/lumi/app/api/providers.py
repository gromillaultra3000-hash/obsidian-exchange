from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.core.errors import LumiError, ProviderNotFoundError, ProviderDuplicateError
from lumi.app.schemas.errors import ErrorEnvelope
from lumi.app.providers.redaction import RedactionUtil
from lumi.app.roles.role_assignment import RoleAssignment
import uuid

router = APIRouter(prefix="/providers", tags=["providers"])
redactor = RedactionUtil()
role_assignment = RoleAssignment()


def _envelope(exc: LumiError):
    return ErrorEnvelope(errorId=str(uuid.uuid4()), code=exc.code, message=exc.message, recoverable=exc.recoverable, details=redactor.redact_dict(exc.details), redacted=True).model_dump()


@router.get("")
async def list_providers():
    return [redactor.redact_model(p) for p in runtime_instance.list_providers()]


@router.post("")
async def register_provider(profile: ProviderProfile):
    try:
        return redactor.redact_model(runtime_instance.register_provider(profile))
    except ProviderDuplicateError as exc:
        raise HTTPException(status_code=409, detail=_envelope(exc))
    except LumiError as exc:
        raise HTTPException(status_code=400, detail=_envelope(exc))


@router.get("/{providerId}")
async def get_provider(providerId: str):
    try:
        return redactor.redact_model(runtime_instance.get_provider(providerId))
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_envelope(exc))


@router.post("/{providerId}/enable")
async def enable_provider(providerId: str):
    try:
        return redactor.redact_model(runtime_instance.enable_provider(providerId))
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_envelope(exc))


@router.post("/{providerId}/disable")
async def disable_provider(providerId: str):
    try:
        return redactor.redact_model(runtime_instance.disable_provider(providerId))
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_envelope(exc))


@router.get("/{providerId}/health")
async def health_check_provider(providerId: str):
    try:
        return redactor.redact_dict(runtime_instance.health_check_provider(providerId))
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_envelope(exc))


@router.post("/{providerId}/suggest-roles")
async def suggest_roles(providerId: str):
    try:
        profile = runtime_instance.get_provider(providerId)
        result = role_assignment.suggest_roles(profile)
        runtime_instance.audit_log.add_entry("roles_suggested", provider_id=providerId, summary=f"Roles suggested for {providerId}: {result.get('suggestedRoles', [])}", details=result)
        return redactor.redact_dict(result)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_envelope(exc))


@router.get("/{providerId}/role-fit")
async def role_fit(providerId: str):
    try:
        profile = runtime_instance.get_provider(providerId)
        result = role_assignment.check_role_fit(profile)
        runtime_instance.audit_log.add_entry("role_fit_checked", provider_id=providerId, summary=f"Role fit checked for {providerId}", details=result)
        return redactor.redact_dict(result)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_envelope(exc))
