from typing import List, Dict
from pydantic import BaseModel, Field


class RoleDefinition(BaseModel):
    roleId: str
    title: str
    description: str
    requiredCapabilities: List[str] = Field(default_factory=list)
    optionalCapabilities: List[str] = Field(default_factory=list)
    defaultPriority: int = 5
    canApprove: bool = False
    canReject: bool = False
    canVeto: bool = False
    canFallback: bool = False
    riskWeight: float = 0.5


class RoleAssignmentResult(BaseModel):
    providerId: str
    assignedRoles: List[str] = Field(default_factory=list)
    suggestedRoles: List[str] = Field(default_factory=list)
    rejectedRoles: List[str] = Field(default_factory=list)
    missingCapabilitiesByRole: Dict[str, List[str]] = Field(default_factory=dict)
    scoreByRole: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
