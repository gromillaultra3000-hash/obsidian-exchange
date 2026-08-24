
from __future__ import annotations
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

ApplyMode = Literal["disabled", "dry_run", "controlled"]
ApplyOperation = Literal["create", "update", "delete", "rename", "unknown"]
WorkspaceStatus = Literal["registered", "disabled", "blocked", "missing", "invalid"]
ApplyGateStatus = Literal["allowed", "blocked", "warning", "unknown"]
ApplyExecutionStatus = Literal["not_started", "blocked", "prepared", "applied", "partial", "failed", "rolled_back"]
RollbackStatus = Literal["available", "not_available", "prepared", "rolled_back", "failed", "blocked"]

class RealApplyConfig(BaseModel):
    mode: ApplyMode = "disabled"
    requireApproval: bool = True
    requireSandboxPass: bool = True
    requireBackup: bool = True
    allowDelete: bool = False
    allowRename: bool = False
    allowCreate: bool = True
    allowUpdate: bool = True
    maxFilesPerApply: int = 20
    maxFileSizeBytes: int = 512000
    maxTotalChangedBytes: int = 2000000
    allowedExtensions: List[str] = Field(default_factory=lambda: [".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".txt", ".css", ".html", ".yml", ".yaml", ".toml", ".ini"])
    blockedExtensions: List[str] = Field(default_factory=lambda: [".env", ".pem", ".key", ".p12", ".pfx", ".crt", ".cer", ".sqlite", ".db", ".zip", ".exe", ".dll", ".so", ".dylib", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf"])
    blockedPathFragments: List[str] = Field(default_factory=lambda: [".git/", ".venv/", "venv/", "node_modules/", "__pycache__/", ".pytest_cache/", "secrets/", "credentials/", "private/", "keys/"])
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SafeWorkspace(BaseModel):
    workspaceId: str
    displayName: str
    rootPath: str
    normalizedRootPath: str
    status: WorkspaceStatus = "registered"
    allowApply: bool = False
    createdAt: str = ""
    updatedAt: str = ""
    allowedPathPrefixes: List[str] = Field(default_factory=list)
    blockedPathPrefixes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RegisterWorkspaceRequest(BaseModel):
    displayName: str
    rootPath: str
    allowApply: bool = False
    allowedPathPrefixes: List[str] = Field(default_factory=list)
    blockedPathPrefixes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RegisterWorkspaceResult(BaseModel):
    workspace: SafeWorkspace
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PathGuardResult(BaseModel):
    path: str
    normalizedPath: str
    relativePath: str
    allowed: bool
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class FileClassification(BaseModel):
    path: str
    operation: ApplyOperation
    isText: bool = False
    isBinary: bool = False
    isSecretLike: bool = False
    extension: str = ""
    sizeBytes: int = 0
    allowed: bool = False
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApplyFileChange(BaseModel):
    path: str
    operation: ApplyOperation
    beforeContent: Optional[str] = None
    afterContent: Optional[str] = None
    diffPreview: Optional[str] = None
    sizeBytes: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApplyGateRequest(BaseModel):
    workspaceId: str
    applyPackageId: Optional[str] = None
    diffPreviewId: Optional[str] = None
    testRunResultId: Optional[str] = None
    approvalPromptId: Optional[str] = None
    fileChanges: List[ApplyFileChange] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApplyGateResult(BaseModel):
    gateId: str
    status: ApplyGateStatus
    allowed: bool
    workspaceId: str
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    pathResults: List[PathGuardResult] = Field(default_factory=list)
    fileClassifications: List[FileClassification] = Field(default_factory=list)
    requiresApproval: bool = False
    requiresSandboxPass: bool = False
    requiresBackup: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class BackupRecord(BaseModel):
    backupId: str
    workspaceId: str
    createdAt: str
    files: List[Dict[str, Any]] = Field(default_factory=list)
    backupRoot: str
    redacted: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class BackupPlan(BaseModel):
    backupPlanId: str
    workspaceId: str
    filesToBackup: List[str] = Field(default_factory=list)
    estimatedBytes: int = 0
    warnings: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class BackupPlanRequest(BaseModel):
    workspaceId: str
    fileChanges: List[ApplyFileChange] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApplyExecutionRequest(BaseModel):
    workspaceId: str
    gateId: Optional[str] = None
    approvalPromptId: Optional[str] = None
    backupPlanId: Optional[str] = None
    applyPackageId: Optional[str] = None
    testRunResultId: Optional[str] = None
    fileChanges: List[ApplyFileChange] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ApplyExecutionResult(BaseModel):
    applyId: str
    workspaceId: str
    status: ApplyExecutionStatus
    appliedFiles: List[str] = Field(default_factory=list)
    skippedFiles: List[str] = Field(default_factory=list)
    failedFiles: List[Dict[str, Any]] = Field(default_factory=list)
    backupId: Optional[str] = None
    rollbackPackageId: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RollbackPackage(BaseModel):
    rollbackPackageId: str
    applyId: str
    workspaceId: str
    createdAt: str
    status: RollbackStatus
    files: List[Dict[str, Any]] = Field(default_factory=list)
    canRollback: bool
    backupId: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RollbackPreview(BaseModel):
    rollbackPackageId: str
    workspaceId: str
    canRollback: bool
    filesToRestore: List[str] = Field(default_factory=list)
    filesToDelete: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RollbackRequest(BaseModel):
    rollbackPackageId: str
    approvalPromptId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RollbackResult(BaseModel):
    rollbackId: str
    rollbackPackageId: str
    workspaceId: str
    status: RollbackStatus
    restoredFiles: List[str] = Field(default_factory=list)
    deletedFiles: List[str] = Field(default_factory=list)
    failedFiles: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
