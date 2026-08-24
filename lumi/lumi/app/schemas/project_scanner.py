from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

ProjectType = Literal["python", "javascript", "typescript", "mixed", "mobile", "web", "backend", "desktop", "unknown"]
ProjectStatus = Literal["registered", "active", "paused", "disabled", "unknown"]
ScanMode = Literal["manifest_only", "snapshot", "static_inspection", "improvement_plan"]
ScanStatus = Literal["created", "running", "completed", "blocked", "failed"]
IssueSeverity = Literal["info", "warning", "error", "critical"]
IssueCategory = Literal["structure", "quality", "security", "configuration", "testing", "documentation", "dependencies", "performance", "maintainability", "unknown"]
ImprovementPriority = Literal["low", "medium", "high", "critical"]

class ProjectManifest(BaseModel):
    projectId: str
    hostAppId: Optional[str] = None
    displayName: str
    projectType: ProjectType = "unknown"
    version: Optional[str] = None
    rootLabel: Optional[str] = None
    description: Optional[str] = None
    declaredEntryPoints: List[str] = Field(default_factory=list)
    declaredTestPaths: List[str] = Field(default_factory=list)
    declaredConfigFiles: List[str] = Field(default_factory=list)
    declaredDocs: List[str] = Field(default_factory=list)
    allowedScanModes: List[ScanMode] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class HostProjectProfile(BaseModel):
    projectId: str
    hostAppId: Optional[str] = None
    displayName: str
    projectType: ProjectType = "unknown"
    status: ProjectStatus = "registered"
    manifest: ProjectManifest
    registeredAt: str = ""
    lastScanAt: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class FileSnapshot(BaseModel):
    snapshotId: str
    projectId: str
    path: str
    fileName: str
    extension: Optional[str] = None
    sizeBytes: int = 0
    contentPreview: Optional[str] = None
    contentHash: Optional[str] = None
    isBinary: bool = False
    isGenerated: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProjectInventory(BaseModel):
    inventoryId: str
    projectId: str
    createdAt: str = ""
    filesCount: int = 0
    directoriesCount: int = 0
    extensions: Dict[str, int] = Field(default_factory=dict)
    largestFiles: List[Dict[str, Any]] = Field(default_factory=list)
    suspectedEntryPoints: List[str] = Field(default_factory=list)
    suspectedTestFiles: List[str] = Field(default_factory=list)
    suspectedConfigFiles: List[str] = Field(default_factory=list)
    suspectedDocs: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProjectIssue(BaseModel):
    issueId: str
    projectId: str
    filePath: Optional[str] = None
    category: IssueCategory = "unknown"
    severity: IssueSeverity = "info"
    title: str = ""
    description: str = ""
    evidence: List[str] = Field(default_factory=list)
    suggestedFix: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ImprovementCandidate(BaseModel):
    candidateId: str
    projectId: str
    relatedIssueIds: List[str] = Field(default_factory=list)
    title: str = ""
    summary: str = ""
    priority: ImprovementPriority = "medium"
    expectedImpact: str = ""
    riskLevel: str = "low"
    requiresApproval: bool = True
    proposedActionId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ImprovementPlan(BaseModel):
    planId: str
    projectId: str
    scanId: str
    title: str = ""
    summary: str = ""
    candidates: List[ImprovementCandidate] = Field(default_factory=list)
    totalIssues: int = 0
    criticalIssues: int = 0
    highPriorityCandidates: int = 0
    recommendedNextStep: str = ""
    actionGatewayResult: Optional[Dict[str, Any]] = None
    approvalPrompt: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PatchPlanPreview(BaseModel):
    patchPlanId: str
    projectId: str
    improvementCandidateId: Optional[str] = None
    title: str = ""
    summary: str = ""
    targetFiles: List[str] = Field(default_factory=list)
    proposedChanges: List[Dict[str, Any]] = Field(default_factory=list)
    riskLevel: str = "low"
    requiresApproval: bool = True
    canApply: bool = False
    applyBlockedReason: str = "real_file_write_disabled_in_v0_8"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProjectScanRequest(BaseModel):
    projectId: str
    scanMode: ScanMode = "static_inspection"
    includeImprovementPlan: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProjectScanResult(BaseModel):
    scanId: str
    projectId: str
    status: ScanStatus = "created"
    scanMode: ScanMode = "static_inspection"
    inventory: Optional[ProjectInventory] = None
    issues: List[ProjectIssue] = Field(default_factory=list)
    improvementPlan: Optional[ImprovementPlan] = None
    patchPlanPreviews: List[PatchPlanPreview] = Field(default_factory=list)
    decisionId: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
