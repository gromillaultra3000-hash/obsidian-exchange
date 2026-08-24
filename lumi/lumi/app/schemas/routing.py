from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

TaskClassLiteral = Literal[
    "general_question", "analysis", "code_review", "document_review", "planning",
    "decision_request", "validation_request", "risk_review", "formatting_request",
    "project_improvement", "patch_planning", "test_failure_analysis", "fallback_request",
]
RouteStatusLiteral = Literal["READY", "PARTIAL", "FALLBACK", "NO_ROUTE", "BLOCKED"]
StrategyLiteral = Literal["single_provider", "multi_provider_parallel", "fallback_only", "no_route"]
RiskLevelLiteral = Literal["low", "medium", "high", "unknown"]


class TaskClassification(BaseModel):
    taskClass: TaskClassLiteral = "general_question"
    confidence: float = 0.5
    detectedSignals: List[str] = Field(default_factory=list)
    normalizedTaskType: Optional[str] = None
    riskLevel: RiskLevelLiteral = "unknown"
    requiresMultipleProviders: bool = False
    reason: str = ""


class TaskRequirements(BaseModel):
    taskClass: TaskClassLiteral = "general_question"
    requiredCapabilities: List[str] = Field(default_factory=list)
    optionalCapabilities: List[str] = Field(default_factory=list)
    requiredRoles: List[str] = Field(default_factory=list)
    optionalRoles: List[str] = Field(default_factory=list)
    minProviders: int = 1
    maxProviders: int = 3
    riskLevel: RiskLevelLiteral = "unknown"
    allowFallback: bool = True
    requireValidation: bool = False
    expectedDecisionStatuses: List[str] = Field(default_factory=list)


class RoutePlan(BaseModel):
    routeId: str
    taskId: str
    taskClass: TaskClassLiteral = "general_question"
    selectedProviders: List[str] = Field(default_factory=list)
    selectedProviderRoles: Dict[str, List[str]] = Field(default_factory=dict)
    requiredCapabilities: List[str] = Field(default_factory=list)
    missingCapabilities: List[str] = Field(default_factory=list)
    requiredRoles: List[str] = Field(default_factory=list)
    missingRoles: List[str] = Field(default_factory=list)
    strategy: StrategyLiteral = "no_route"
    minProviders: int = 1
    fallbackUsed: bool = False
    routeStatus: RouteStatusLiteral = "NO_ROUTE"
    reason: str = ""
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
