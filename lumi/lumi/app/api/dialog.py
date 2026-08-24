import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.dialog import CreateDialogSessionRequest, SendDialogMessageRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/dialog", tags=["dialog"])


def _err(code, message, status=404):
    raise HTTPException(status_code=status, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, redacted=True).model_dump())


@router.post("/sessions")
async def create_session(request: CreateDialogSessionRequest):
    return runtime_instance.create_dialog_session(request.hostAppId, request.userId, request.title, request.metadata)


@router.get("/sessions")
async def list_sessions():
    return runtime_instance.list_dialog_sessions()


@router.get("/sessions/{sessionId}")
async def get_session(sessionId: str):
    session = runtime_instance.get_dialog_session(sessionId)
    if not session:
        _err("SESSION_NOT_FOUND", f"Session {sessionId} not found")
    return session


@router.post("/sessions/{sessionId}/close")
async def close_session(sessionId: str):
    session = runtime_instance.close_dialog_session(sessionId)
    if not session:
        _err("SESSION_NOT_FOUND", f"Session {sessionId} not found")
    return session


@router.post("/sessions/{sessionId}/message")
async def send_message(sessionId: str, request: SendDialogMessageRequest):
    session = runtime_instance.get_dialog_session(sessionId)
    if not session:
        _err("SESSION_NOT_FOUND", f"Session {sessionId} not found")
    return runtime_instance.send_dialog_message(sessionId, request.text, request.metadata)


@router.get("/sessions/{sessionId}/messages")
async def list_messages(sessionId: str):
    session = runtime_instance.get_dialog_session(sessionId)
    if not session:
        _err("SESSION_NOT_FOUND", f"Session {sessionId} not found")
    return runtime_instance.list_dialog_messages(sessionId)
