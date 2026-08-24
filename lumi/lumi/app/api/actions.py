import uuid
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.actions import ActionDefinition, ApprovalDecision
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/actions", tags=["actions"])


class ProposeActionRequest(BaseModel):
    actionId: str
    taskId: Optional[str] = None
    proposedInput: Dict[str, Any] = Field(default_factory=dict)
    requestedMode: str = "proposal"


class PolicyCheckActionRequest(BaseModel):
    actionId: str
    taskId: Optional[str] = None
    proposedInput: Dict[str, Any] = Field(default_factory=dict)
    requestedMode: str = "proposal"


def _err(code: str, message: str, status: int = 400):
    raise HTTPException(status_code=status, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, redacted=True).model_dump())


@router.get("")
async def list_actions():
    return runtime_instance.list_actions()


@router.post("/register")
async def register_action(action_def: ActionDefinition):
    try:
        return runtime_instance.register_action(action_def)
    except ValueError as exc:
        _err("ACTION_EXISTS", str(exc), 409)


@router.post("/propose")
async def propose_action(request: ProposeActionRequest):
    task_request = TaskRequest(taskId=request.taskId, input="action_proposal", context={}, requirements={}) if request.taskId else None
    return runtime_instance.propose_action(request.actionId, task_request=task_request, proposed_input=request.proposedInput, requested_mode=request.requestedMode)


@router.post("/policy-check")
async def check_action_policy(request: PolicyCheckActionRequest):
    task_request = TaskRequest(taskId=request.taskId, input="policy_check", context={}, requirements={}) if request.taskId else None
    return runtime_instance.check_action_policy(request.actionId, task_request=task_request, proposed_input=request.proposedInput, requested_mode=request.requestedMode)


@router.get("/approvals")
async def list_approvals():
    return runtime_instance.list_approvals()


@router.get("/approvals/{promptId}")
async def get_approval(promptId: str):
    approval = runtime_instance.get_approval(promptId)
    if not approval:
        _err("APPROVAL_NOT_FOUND", f"Approval prompt {promptId} not found", 404)
    return approval


@router.post("/approvals/{promptId}/decision")
async def record_approval_decision(promptId: str, decision: ApprovalDecision):
    result = runtime_instance.record_approval_decision(promptId, decision.decision, decision.userId, decision.reason, decision.metadata)
    if not result:
        _err("APPROVAL_NOT_FOUND", f"Approval prompt {promptId} not found", 404)
    return result


@router.get("/{actionId}")
async def get_action(actionId: str):
    action = runtime_instance.get_action(actionId)
    if not action:
        _err("ACTION_NOT_FOUND", f"Action {actionId} not found", 404)
    return action


@router.post("/{actionId}/enable")
async def enable_action(actionId: str):
    try:
        return runtime_instance.enable_action(actionId)
    except ValueError as exc:
        _err("ACTION_NOT_FOUND", str(exc), 404)


@router.post("/{actionId}/disable")
async def disable_action(actionId: str):
    try:
        return runtime_instance.disable_action(actionId)
    except ValueError as exc:
        _err("ACTION_NOT_FOUND", str(exc), 404)
