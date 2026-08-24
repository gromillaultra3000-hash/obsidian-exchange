from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from lumi.app.schemas.task import TaskRequest

DialogSessionStatus = Literal["active", "paused", "closed"]
DialogMessageRole = Literal["user", "lumi", "system"]
DialogCommandType = Literal[
    "general_message",
    "resolve_task",
    "explain_decision",
    "show_history",
    "show_status",
    "register_provider_help",
    "register_action_help",
    "approval_response",
    "project_scan",
    "show_project_summary",
    "show_improvement_plan",
    "patch_preview",
    "show_diff_preview",
    "show_test_plan",
    "show_rollback_plan",
    "create_sandbox",
    "sandbox_test",
    "apply_preview_to_sandbox",
    "prepare_apply_package",
    "show_apply_package",
    "unknown",
]


class DialogSession(BaseModel):
    sessionId: str
    hostAppId: Optional[str] = None
    userId: Optional[str] = None
    title: str = ""
    status: DialogSessionStatus = "active"
    createdAt: str = ""
    updatedAt: str = ""
    linkedDecisionIds: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DialogMessage(BaseModel):
    messageId: str
    sessionId: str
    role: DialogMessageRole = "user"
    createdAt: str = ""
    text: str = ""
    commandType: DialogCommandType = "general_message"
    linkedTaskId: Optional[str] = None
    linkedDecisionId: Optional[str] = None
    linkedApprovalPromptId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DialogCommand(BaseModel):
    commandId: str
    sessionId: str
    messageId: str
    commandType: DialogCommandType = "unknown"
    inputText: str = ""
    taskRequest: Optional[TaskRequest] = None
    targetDecisionId: Optional[str] = None
    targetApprovalPromptId: Optional[str] = None
    parsed: bool = False
    confidence: float = 0.5
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DialogResponse(BaseModel):
    responseId: str
    sessionId: str
    messageId: str
    commandType: DialogCommandType = "unknown"
    text: str = ""
    decisionId: Optional[str] = None
    taskId: Optional[str] = None
    status: Optional[str] = None
    shortAnswer: str = ""
    decisionSummary: Optional[str] = None
    routeSummary: Optional[str] = None
    validationSummary: Optional[str] = None
    conflictSummary: Optional[str] = None
    policySummary: Optional[str] = None
    actionSummary: Optional[str] = None
    approvalPrompt: Optional[Dict[str, Any]] = None
    requiredNextStep: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CreateDialogSessionRequest(BaseModel):
    hostAppId: Optional[str] = None
    userId: Optional[str] = None
    title: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SendDialogMessageRequest(BaseModel):
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
