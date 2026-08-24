from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

PolicyScope = Literal["runtime", "host", "user", "domain", "action"]
PolicyDecisionStatus = Literal["ALLOW", "BLOCK", "REQUIRE_APPROVAL", "DRY_RUN_ONLY", "UNKNOWN"]
LimitType = Literal["count", "cost", "risk", "time", "scope", "custom"]
RiskLevel = Literal["low", "medium", "high", "critical", "unknown"]
RequestedMode = Literal["proposal", "dry_run", "execute"]


class PolicyRule(BaseModel):
    ruleId: str
    scope: PolicyScope = "action"
    title: str
    description: str
    enabled: bool = True
    priority: int = 50
    conditionType: str = "default"
    condition: Dict[str, Any] = Field(default_factory=dict)
    effect: PolicyDecisionStatus = "UNKNOWN"
    reason: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LimitDefinition(BaseModel):
    limitId: str
    title: str
    description: str
    limitType: LimitType = "custom"
    value: Any = None
    unit: Optional[str] = None
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PolicyCheckRequest(BaseModel):
    taskId: Optional[str] = None
    decisionId: Optional[str] = None
    actionId: Optional[str] = None
    hostAppId: Optional[str] = None
    riskLevel: RiskLevel = "unknown"
    requestedMode: RequestedMode = "proposal"
    context: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PolicyCheckResult(BaseModel):
    policyCheckId: str
    status: PolicyDecisionStatus = "UNKNOWN"
    actionAllowed: bool = False
    approvalRequired: bool = False
    dryRunOnly: bool = False
    riskLevel: RiskLevel = "unknown"
    matchedRules: List[str] = Field(default_factory=list)
    blockedBy: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    requiredNextStep: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PolicySummary(BaseModel):
    totalRules: int = 0
    enabledRules: int = 0
    totalLimits: int = 0
    enabledLimits: int = 0
    status: str = "ok"
    warnings: List[str] = Field(default_factory=list)
