from typing import List
from pydantic import BaseModel, Field


class CapabilityDefinition(BaseModel):
    id: str
    title: str
    description: str
    category: str
    defaultWeight: float = 0.5
    riskLevel: str = "low"


class CapabilityMatchResult(BaseModel):
    providerId: str
    requiredCapabilities: List[str] = Field(default_factory=list)
    matchedCapabilities: List[str] = Field(default_factory=list)
    missingCapabilities: List[str] = Field(default_factory=list)
    unknownCapabilities: List[str] = Field(default_factory=list)
    score: float = 0.0
    eligible: bool = False
    reason: str = ""
