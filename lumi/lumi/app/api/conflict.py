from typing import Any, List, Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.schemas.errors import ErrorEnvelope
from lumi.app.conflict.conflict_detector import ConflictDetector
from lumi.app.conflict.deterministic_resolver import DeterministicResolver
import uuid

router = APIRouter(prefix="/conflict", tags=["conflict"])

class ConflictAnalyzeRequest(BaseModel):
    task: dict = Field(default_factory=lambda: {"input": "analyze", "context": {}, "requirements": {}})
    outputs: List[Dict[str, Any]] = Field(default_factory=list)

@router.post("/analyze")
async def analyze_conflict(request: ConflictAnalyzeRequest):
    try:
        task = TaskRequest(**request.task)
        profiles = []
        raw_outputs = []
        for item in request.outputs:
            provider_id = item.get("providerId") or item.get("rawOutput", {}).get("providerId") or f"provider-{len(profiles)+1}"
            try:
                profile = runtime_instance.get_provider(provider_id)
            except Exception:
                profile = ProviderProfile(providerId=provider_id, displayName=provider_id, providerType="mock", apiFormat="json", enabled=True, roles=[], capabilities=[], costProfile={}, latencyProfile={}, reliabilityScore=0.0)
            profiles.append(profile)
            raw_outputs.append(item.get("rawOutput", item))
        validation_result = runtime_instance.validation_pipeline.validate_outputs(raw_outputs, task, profiles)
        accepted = [r.normalizedOutput for r in validation_result.results if not r.rejected and r.normalizedOutput is not None]
        report = ConflictDetector().analyze(task.taskId or "adhoc", accepted, validation_result)
        return report
    except Exception as exc:
        raise HTTPException(status_code=400, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="CONFLICT_ANALYSIS_ERROR", message=str(exc), recoverable=True, details={}).model_dump())

@router.post("/resolve")
async def resolve_conflict(request: ConflictAnalyzeRequest):
    try:
        task = TaskRequest(**request.task)
        profiles = []
        raw_outputs = []
        for item in request.outputs:
            provider_id = item.get("providerId") or item.get("rawOutput", {}).get("providerId") or f"provider-{len(profiles)+1}"
            try:
                profile = runtime_instance.get_provider(provider_id)
            except Exception:
                profile = ProviderProfile(providerId=provider_id, displayName=provider_id, providerType="mock", apiFormat="json", enabled=True, roles=[], capabilities=[], costProfile={}, latencyProfile={}, reliabilityScore=0.0)
            profiles.append(profile)
            raw_outputs.append(item.get("rawOutput", item))
        validation_result = runtime_instance.validation_pipeline.validate_outputs(raw_outputs, task, profiles)
        accepted = [r.normalizedOutput for r in validation_result.results if not r.rejected and r.normalizedOutput is not None]
        report = ConflictDetector().analyze(task.taskId or "adhoc", accepted, validation_result)
        resolution = DeterministicResolver().resolve(task.taskId or "adhoc", accepted, validation_result, report)
        return {"conflictReport": report, "resolution": resolution, "validationPipeline": validation_result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="DETERMINISTIC_RESOLUTION_ERROR", message=str(exc), recoverable=True, details={}).model_dump())
