from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, field_validator


class ProviderProfile(BaseModel):
    providerId: str
    displayName: str
    providerType: str
    apiFormat: str
    baseUrl: Optional[str] = None
    model: Optional[str] = None
    enabled: bool = True
    roles: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)
    costProfile: Dict[str, Any] = Field(default_factory=dict)
    latencyProfile: Dict[str, Any] = Field(default_factory=dict)
    reliabilityScore: float = 0.0
    notes: Optional[str] = None
    secretRef: Optional[str] = None

    @field_validator("providerId", "displayName", "providerType", "apiFormat")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("field must not be empty")
        return value.strip()

    @field_validator("reliabilityScore")
    @classmethod
    def score_range(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError("reliabilityScore must be between 0 and 1")
        return value


class ProviderOutput(BaseModel):
    providerId: str
    role: Optional[str] = None
    status: Literal["success", "error", "timeout", "invalid"] = "success"
    answer: Optional[str] = None
    confidence: float = 0.0
    suggestedStatus: Optional[str] = None
    riskFlags: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    evidenceRefs: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    rawOutputRedacted: Optional[Dict[str, Any]] = None

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if value < 0:
            return 0.0
        if value > 1:
            return 1.0
        return value
