from typing import Optional, List, Any, Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.schemas.errors import ErrorEnvelope
from lumi.app.validation.output_normalizer import OutputNormalizer
from lumi.app.validation.output_validator import OutputValidator
from lumi.app.providers.redaction import RedactionUtil
import uuid

router = APIRouter(prefix="/validation", tags=["validation"])
redactor = RedactionUtil()


class NormalizeRequest(BaseModel):
    providerId: str
    rawOutput: Any
    task: Optional[dict] = None


class ValidateRequest(BaseModel):
    providerId: str
    rawOutput: Any
    task: Optional[dict] = None


class ValidateBatchRequest(BaseModel):
    task: Optional[dict] = None
    outputs: List[Dict[str, Any]] = Field(default_factory=list)


def _err(code: str, message: str, details: dict | None = None):
    return ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, recoverable=False, details=redactor.redact_dict(details or {}), redacted=True).model_dump()


def _profile(provider_id: str) -> ProviderProfile:
    try:
        return runtime_instance.get_provider(provider_id)
    except Exception:
        return ProviderProfile(providerId=provider_id, displayName=f"Provider {provider_id}", providerType="mock", apiFormat="json", enabled=True, roles=[], capabilities=[], costProfile={}, latencyProfile={}, reliabilityScore=0.0)


@router.post("/normalize")
async def normalize_output(request: NormalizeRequest):
    try:
        normalizer = OutputNormalizer(runtime_instance.redaction)
        task_request = TaskRequest(**request.task) if request.task else None
        return normalizer.normalize_provider_output(request.rawOutput, _profile(request.providerId), task_request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_err("NORMALIZATION_ERROR", str(exc), {"providerId": request.providerId}))


@router.post("/validate-output")
async def validate_output(request: ValidateRequest):
    try:
        normalizer = OutputNormalizer(runtime_instance.redaction)
        validator = OutputValidator()
        task_request = TaskRequest(**request.task) if request.task else None
        normalized = normalizer.normalize_provider_output(request.rawOutput, _profile(request.providerId), task_request)
        return validator.validate(normalized, task_request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_err("VALIDATION_ERROR", str(exc), {"providerId": request.providerId}))


@router.post("/validate-batch")
async def validate_batch(request: ValidateBatchRequest):
    try:
        task_request = TaskRequest(**request.task) if request.task else TaskRequest(input="batch", context={}, requirements={})
        provider_profiles = [_profile(item.get("providerId") or f"unknown-{idx}") for idx, item in enumerate(request.outputs)]
        raw_outputs = []
        for idx, item in enumerate(request.outputs):
            raw = item.get("rawOutput")
            if isinstance(raw, dict) and "providerId" not in raw:
                raw = {**raw, "providerId": provider_profiles[idx].providerId}
            raw_outputs.append(raw)
        return runtime_instance.validation_pipeline.validate_outputs(raw_outputs, task_request, provider_profiles)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=_err("BATCH_VALIDATION_ERROR", str(exc)))
