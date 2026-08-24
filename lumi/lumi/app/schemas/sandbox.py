from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

SandboxStatus = Literal["created", "ready", "patched", "tested", "blocked", "failed", "discarded"]
SandboxSource = Literal["project_snapshots", "patch_plan", "manual", "integration_event", "dialog"]
SandboxCommandStatus = Literal["allowed", "blocked", "executed", "failed", "skipped"]
SandboxTestStatus = Literal["created", "running", "completed", "blocked", "failed"]
ApplyPreparationStatus = Literal["created", "approval_required", "blocked", "ready_for_review", "failed"]

class SandboxWorkspaceRequest(BaseModel):
    requestId: Optional[str] = None
    projectId: str
    source: SandboxSource = "project_snapshots"
    patchPlanResultId: Optional[str] = None
    diffPreviewId: Optional[str] = None
    includeSnapshots: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SandboxFile(BaseModel):
    path: str
    contentPreview: Optional[str] = None
    contentHash: Optional[str] = None
    sizeBytes: int = 0
    isBinary: bool = False
    isGenerated: bool = False
    isSynthetic: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SandboxWorkspace(BaseModel):
    workspaceId: str
    projectId: str
    source: SandboxSource = "project_snapshots"
    status: SandboxStatus = "created"
    createdAt: str = ""
    files: List[SandboxFile] = Field(default_factory=list)
    patchPlanResultId: Optional[str] = None
    diffPreviewId: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SandboxPatchApplyPreview(BaseModel):
    applyPreviewId: str
    workspaceId: str
    projectId: str
    diffPreviewId: str
    status: SandboxStatus = "patched"
    filesAffected: List[str] = Field(default_factory=list)
    appliedSyntheticChanges: List[Dict[str, Any]] = Field(default_factory=list)
    canAffectHost: bool = False
    hostWriteBlockedReason: str = "host_project_write_disabled_in_v1_0"
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class CommandPreview(BaseModel):
    commandId: str
    commandPreview: str
    purpose: str = ""
    allowlisted: bool = False
    blockedReason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SandboxTestRunRequest(BaseModel):
    requestId: Optional[str] = None
    projectId: str
    workspaceId: Optional[str] = None
    testPlanId: Optional[str] = None
    commands: List[str] = Field(default_factory=list)
    mode: Literal["preview_only", "controlled_sandbox"] = "preview_only"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SandboxCommandResult(BaseModel):
    commandId: str
    commandPreview: str
    status: SandboxCommandStatus = "allowed"
    exitCode: Optional[int] = None
    stdoutPreview: Optional[str] = None
    stderrPreview: Optional[str] = None
    blockedReason: Optional[str] = None
    durationMs: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SandboxTestRunResult(BaseModel):
    testRunResultId: str
    projectId: str
    workspaceId: Optional[str] = None
    testPlanId: Optional[str] = None
    status: SandboxTestStatus = "created"
    mode: str = "preview_only"
    commands: List[SandboxCommandResult] = Field(default_factory=list)
    summary: str = ""
    passed: bool = False
    canAffectHost: bool = False
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApplyPreparationRequest(BaseModel):
    requestId: Optional[str] = None
    projectId: str
    patchPlanResultId: Optional[str] = None
    patchProposalId: Optional[str] = None
    diffPreviewId: Optional[str] = None
    testRunResultId: Optional[str] = None
    rollbackMetadataId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApplyPreparationPackage(BaseModel):
    applyPackageId: str
    projectId: str
    status: ApplyPreparationStatus = "created"
    patchPlanResultId: Optional[str] = None
    patchProposalId: Optional[str] = None
    diffPreviewId: Optional[str] = None
    testRunResultId: Optional[str] = None
    rollbackMetadataId: Optional[str] = None
    summary: str = ""
    filesAffected: List[str] = Field(default_factory=list)
    riskLevel: str = "unknown"
    approvalRequired: bool = True
    actionGatewayResult: Optional[Dict[str, Any]] = None
    approvalPrompt: Optional[Dict[str, Any]] = None
    canApplyToHost: bool = False
    applyBlockedReason: str = "host_project_apply_disabled_in_v1_0"
    rollbackAvailable: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SandboxOperationResult(BaseModel):
    resultId: str
    projectId: str
    workspace: Optional[SandboxWorkspace] = None
    patchApplyPreview: Optional[SandboxPatchApplyPreview] = None
    testRunResult: Optional[SandboxTestRunResult] = None
    applyPreparationPackage: Optional[ApplyPreparationPackage] = None
    status: str = ""
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
