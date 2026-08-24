import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.explainability import ExplanationRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/explain", tags=["explainability"])


def _err(code, message, status=404):
    raise HTTPException(status_code=status, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, redacted=True).model_dump())


@router.get("/{decisionId}")
async def explain_get(decisionId: str, mode: str = "human", includeTimeline: bool = False):
    result = runtime_instance.explain_decision(decisionId, mode, includeTimeline)
    if not result:
        _err("DECISION_NOT_FOUND", f"Decision {decisionId} not found for explanation")
    return result


@router.post("")
async def explain_post(request: ExplanationRequest):
    result = runtime_instance.explain_decision(request.decisionId, request.mode, request.includeAuditTimeline)
    if not result:
        _err("DECISION_NOT_FOUND", f"Decision {request.decisionId} not found for explanation")
    return result
