from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


DecisionStatus = Literal["APPROVE", "REJECT", "WAIT", "ESCALATE", "SAFE_DEFAULT", "ASK_USER"]
RiskLevel = Literal["low", "medium", "high", "unknown"]


class StructuredDecision(BaseModel):
    decisionId: str
    taskId: str
    status: DecisionStatus
    actionAllowed: bool = False
    confidence: float = 0.0
    riskLevel: RiskLevel = "unknown"
    conflictDetected: bool = False
    conflictType: Optional[str] = None
    winningRule: str = ""
    summary: str = ""
    requiredNextStep: Optional[str] = None
    userApprovalRequired: bool = False
    auditRequired: bool = True
    providerOutputsCount: int = 0
    validProviderOutputsCount: int = 0
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
