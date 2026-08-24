from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.core.errors import AuditNotFoundError
from lumi.app.schemas.errors import ErrorEnvelope
from lumi.app.providers.redaction import RedactionUtil
import uuid

router = APIRouter(prefix="/audit", tags=["audit"])
redactor = RedactionUtil()


@router.get("")
async def list_audit():
    return [redactor.redact_model(entry) for entry in runtime_instance.get_audit_entries()]


@router.get("/{auditId}")
async def get_audit(auditId: str):
    try:
        return redactor.redact_model(runtime_instance.get_audit_entry(auditId))
    except AuditNotFoundError as exc:
        raise HTTPException(status_code=404, detail=ErrorEnvelope(
            errorId=str(uuid.uuid4()),
            code=exc.code,
            message=exc.message,
            recoverable=exc.recoverable,
            details=redactor.redact_dict(exc.details),
            redacted=True,
        ).model_dump())
