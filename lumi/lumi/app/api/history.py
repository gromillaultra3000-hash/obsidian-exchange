import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.history import DecisionHistoryQuery
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/history", tags=["history"])


def _err(code, message, status=404):
    raise HTTPException(status_code=status, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, redacted=True).model_dump())


@router.get("/decisions")
async def list_decisions():
    records = runtime_instance.list_decision_history()
    return {"total": len(records), "records": records}


@router.get("/decisions/{decisionId}")
async def get_decision(decisionId: str):
    record = runtime_instance.get_decision_history(decisionId)
    if not record:
        _err("DECISION_NOT_FOUND", f"Decision {decisionId} not found in history")
    return record


@router.post("/decisions/query")
async def query_decisions(query: DecisionHistoryQuery):
    return runtime_instance.filter_decision_history(query)


@router.get("/decisions/{decisionId}/timeline")
async def get_decision_timeline(decisionId: str):
    record = runtime_instance.get_decision_history(decisionId)
    if not record:
        _err("DECISION_NOT_FOUND", f"Decision {decisionId} not found in history")
    return runtime_instance.build_decision_timeline(decisionId)
