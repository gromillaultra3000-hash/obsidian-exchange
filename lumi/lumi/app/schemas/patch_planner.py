from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

PatchRequestSource = Literal["manual", "improvement_candidate", "improvement_plan", "dialog", "integration_event", "custom"]
PatchRiskLevel = Literal["low", "medium", "high", "critical", "unknown"]
PatchStatus = Literal["created", "planned", "preview_ready", "approval_required", "blocked", "failed"]
PatchChangeType = Literal["create_file", "update_file", "delete_file", "rename_file", "move_file", "config_change", "docs_change", "test_change", "refactor", "security_fix", "unknown"]
TestPlanStatus = Literal["created", "preview_ready", "blocked", "failed"]
RollbackStatus = Literal["created", "preview_ready", "not_available", "blocked"]

class PatchRequest(BaseModel):
    requestId: Optional[str] = None
    projectId: str
    source: PatchRequestSource = "manual"
    improvementCandidateId: Optional[str] = None
    improvementPlanId: Optional[str] = None
    title: str = ""
    summary: str = ""
    targetFiles: List[str] = Field(default_factory=list)
    requestedChanges: List[Dict[str, Any]] = Field(default_factory=list)
    riskLevel: PatchRiskLevel = "unknown"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PatchProposal(BaseModel):
    patchProposalId: str
    projectId: str
    requestId: str
    title: str = ""
    summary: str = ""
    status: PatchStatus = "created"
    riskLevel: PatchRiskLevel = "unknown"
    targetFiles: List[str] = Field(default_factory=list)
    proposedChanges: List[Dict[str, Any]] = Field(default_factory=list)
    diffPreviewId: Optional[str] = None
    testPlanId: Optional[str] = None
    rollbackMetadataId: Optional[str] = None
    actionGatewayResult: Optional[Dict[str, Any]] = None
    approvalPrompt: Optional[Dict[str, Any]] = None
    canApply: bool = False
    applyBlockedReason: str = "real_file_write_disabled_in_v0_9"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DiffPreviewLine(BaseModel):
    lineType: Literal["context", "add", "remove", "info"] = "context"
    oldLineNumber: Optional[int] = None
    newLineNumber: Optional[int] = None
    content: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

class FileDiffPreview(BaseModel):
    fileDiffId: str
    path: str
    changeType: PatchChangeType = "unknown"
    summary: str = ""
    lines: List[DiffPreviewLine] = Field(default_factory=list)
    isSynthetic: bool = True
    canApply: bool = False
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DiffPreview(BaseModel):
    diffPreviewId: str
    projectId: str
    patchProposalId: Optional[str] = None
    title: str = ""
    summary: str = ""
    fileDiffs: List[FileDiffPreview] = Field(default_factory=list)
    totalFilesChanged: int = 0
    totalAdditions: int = 0
    totalRemovals: int = 0
    canApply: bool = False
    applyBlockedReason: str = "real_file_write_disabled_in_v0_9"
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TestPlanStep(BaseModel):
    stepId: str
    title: str
    commandPreview: Optional[str] = None
    purpose: str = ""
    expectedResult: str = ""
    canExecute: bool = False
    executeBlockedReason: str = "real_test_execution_disabled_in_v0_9"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TestPlan(BaseModel):
    testPlanId: str
    projectId: str
    patchProposalId: Optional[str] = None
    title: str = ""
    summary: str = ""
    status: TestPlanStatus = "created"
    steps: List[TestPlanStep] = Field(default_factory=list)
    canExecute: bool = False
    executeBlockedReason: str = "real_test_execution_disabled_in_v0_9"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TestRunPreview(BaseModel):
    testRunPreviewId: str
    projectId: str
    patchProposalId: Optional[str] = None
    testPlanId: str
    status: TestPlanStatus = "created"
    plannedSteps: List[TestPlanStep] = Field(default_factory=list)
    simulatedResult: str = "No tests executed. This is a dry-run preview only."
    canExecute: bool = False
    executeBlockedReason: str = "real_test_execution_disabled_in_v0_9"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RollbackStep(BaseModel):
    stepId: str
    title: str
    targetFiles: List[str] = Field(default_factory=list)
    description: str = ""
    canExecute: bool = False
    executeBlockedReason: str = "real_rollback_execution_disabled_in_v0_9"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RollbackMetadata(BaseModel):
    rollbackMetadataId: str
    projectId: str
    patchProposalId: Optional[str] = None
    status: RollbackStatus = "created"
    summary: str = ""
    affectedFiles: List[str] = Field(default_factory=list)
    rollbackSteps: List[RollbackStep] = Field(default_factory=list)
    snapshotReferences: List[str] = Field(default_factory=list)
    canRollback: bool = False
    rollbackBlockedReason: str = "real_rollback_execution_disabled_in_v0_9"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PatchPlanResult(BaseModel):
    resultId: str
    projectId: str
    status: PatchStatus = "created"
    patchProposal: Optional[PatchProposal] = None
    diffPreview: Optional[DiffPreview] = None
    testPlan: Optional[TestPlan] = None
    testRunPreview: Optional[TestRunPreview] = None
    rollbackMetadata: Optional[RollbackMetadata] = None
    decisionId: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
