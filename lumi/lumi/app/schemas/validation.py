from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from lumi.app.schemas.provider import ProviderOutput

ValidationSeverity = Literal["info", "warning", "error", "critical"]
ValidationStatus = Literal["valid", "degraded", "rejected"]
OverallValidationStatus = Literal["valid", "degraded", "rejected"]


class ValidationIssue(BaseModel):
    issueId: str
    code: str
    severity: ValidationSeverity
    message: str
    field: Optional[str] = None
    recoverable: bool = True
    details: Dict[str, Any] = Field(default_factory=dict)


class ProviderOutputValidationResult(BaseModel):
    providerId: str
    taskId: Optional[str] = None
    validationStatus: ValidationStatus
    validationScore: float = 0.0
    issues: List[ValidationIssue] = Field(default_factory=list)
    normalizedOutput: Optional[ProviderOutput] = None
    rejected: bool = False
    rejectionReason: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NormalizedOutputEnvelope(BaseModel):
    providerId: str
    taskId: Optional[str] = None
    originalStatus: Optional[str] = None
    normalizedStatus: str = "success"
    output: ProviderOutput
    normalizationWarnings: List[str] = Field(default_factory=list)
    rawOutputRedacted: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ValidationPipelineResult(BaseModel):
    taskId: str
    totalOutputs: int = 0
    validOutputs: int = 0
    degradedOutputs: int = 0
    rejectedOutputs: int = 0
    results: List[ProviderOutputValidationResult] = Field(default_factory=list)
    acceptedProviderIds: List[str] = Field(default_factory=list)
    rejectedProviderIds: List[str] = Field(default_factory=list)
    overallValidationStatus: OverallValidationStatus = "rejected"
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
