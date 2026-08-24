from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

ConflictType = Literal[
    "NONE",
    "FACT_CONFLICT",
    "RISK_CONFLICT",
    "STRATEGY_CONFLICT",
    "POLICY_CONFLICT",
    "DATA_CONFLICT",
    "ACTION_CONFLICT",
    "CONFIDENCE_CONFLICT",
    "FORMAT_CONFLICT",
    "VALIDATION_CONFLICT",
]

ResolutionStatus = Literal["APPROVE", "REJECT", "WAIT", "ESCALATE", "SAFE_DEFAULT", "ASK_USER"]

class ProviderDecisionSignal(BaseModel):
    providerId: str
    role: Optional[str] = None
    suggestedStatus: Optional[str] = None
    confidence: float = 0.0
    validationStatus: Optional[str] = None
    riskFlags: List[str] = Field(default_factory=list)
    evidenceRefs: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    outputStatus: str = "unknown"

class ConflictFinding(BaseModel):
    conflictType: ConflictType
    severity: Literal["none", "low", "medium", "high", "critical"] = "none"
    reason: str = ""
    affectedProviders: List[str] = Field(default_factory=list)
    rule: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ConflictAnalysisReport(BaseModel):
    conflictReportId: str
    taskId: str
    generatedAt: str
    totalSignals: int = 0
    conflictDetected: bool = False
    primaryConflictType: ConflictType = "NONE"
    disagreementScore: float = 0.0
    confidenceSpread: float = 0.0
    statusSpread: List[str] = Field(default_factory=list)
    findings: List[ConflictFinding] = Field(default_factory=list)
    signals: List[ProviderDecisionSignal] = Field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DeterministicResolution(BaseModel):
    resolutionId: str
    taskId: str
    status: ResolutionStatus
    actionAllowed: bool = False
    confidence: float = 0.0
    riskLevel: Literal["low", "medium", "high", "unknown"] = "unknown"
    conflictDetected: bool = False
    conflictType: ConflictType = "NONE"
    winningRule: str = ""
    summary: str = ""
    requiredNextStep: Optional[str] = None
    userApprovalRequired: bool = False
    auditRequired: bool = True
    acceptedProviderIds: List[str] = Field(default_factory=list)
    rejectedProviderIds: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
