from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from lumi.app.schemas.policy import PolicyCheckResult

ActionRiskLevel = Literal["low", "medium", "high", "critical", "unknown"]
ActionMode = Literal["proposal", "dry_run", "execute"]
ActionStatus = Literal[
    "registered", "disabled", "proposal_created", "blocked",
    "approval_required", "approved", "rejected", "dry_run_ready",
    "executed_mock", "failed"
]
ApprovalPromptStatus = Literal["pending", "approved", "rejected", "expired", "cancelled"]
ApprovalDecisionType = Literal["approve", "reject", "cancel"]


class ActionDefinition(BaseModel):
    actionId: str
    title: str
    description: str
    hostAppId: Optional[str] = None
    category: str = "general"
    enabled: bool = True
    riskLevel: ActionRiskLevel = "low"
    requiresApproval: bool = True
    supportsDryRun: bool = False
    supportsRollback: bool = False
    inputSchema: Dict[str, Any] = Field(default_factory=dict)
    outputSchema: Dict[str, Any] = Field(default_factory=dict)
    allowedModes: List[ActionMode] = Field(default_factory=lambda: ["proposal"])
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ActionProposal(BaseModel):
    proposalId: str
    actionId: str
    taskId: Optional[str] = None
    decisionId: Optional[str] = None
    hostAppId: Optional[str] = None
    title: str
    summary: str
    proposedInput: Dict[str, Any] = Field(default_factory=dict)
    riskLevel: ActionRiskLevel = "unknown"
    requestedMode: ActionMode = "proposal"
    policyCheck: Optional[PolicyCheckResult] = None
    status: ActionStatus = "proposal_created"
    approvalRequired: bool = False
    actionAllowed: bool = False
    blockedReasons: List[str] = Field(default_factory=list)
    requiredNextStep: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalPrompt(BaseModel):
    promptId: str
    proposalId: str
    actionId: str
    decisionId: Optional[str] = None
    taskId: Optional[str] = None
    title: str
    message: str
    riskLevel: ActionRiskLevel = "unknown"
    buttons: List[str] = Field(default_factory=lambda: ["approve", "reject", "details"])
    defaultButton: str = "reject"
    requiresExplicitApproval: bool = True
    expiresAt: Optional[str] = None
    status: ApprovalPromptStatus = "pending"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    promptId: str
    decision: ApprovalDecisionType
    userId: Optional[str] = None
    reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ActionGatewayResult(BaseModel):
    gatewayResultId: str
    proposalId: Optional[str] = None
    actionId: str
    status: ActionStatus = "proposal_created"
    actionAllowed: bool = False
    approvalRequired: bool = False
    approvalPrompt: Optional[ApprovalPrompt] = None
    policyCheck: PolicyCheckResult
    result: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
