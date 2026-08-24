from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

ProviderScoreStatus = Literal["unknown", "healthy", "degraded", "poor", "blocked", "disabled"]
ProviderReviewMode = Literal["metadata_only", "mock_only", "live_if_allowed", "live_required"]
ProviderSelectionStrategy = Literal["highest_reliability", "lowest_latency", "balanced", "fallback_order", "manual"]
ProviderLimitStatus = Literal["ok", "warning", "exceeded", "blocked"]

class ProviderReliabilityScore(BaseModel):
    providerId: str
    status: ProviderScoreStatus = "unknown"
    reliabilityScore: float = 0.0
    successRate: float = 0.0
    failureRate: float = 0.0
    blockedRate: float = 0.0
    averageLatencyMs: Optional[float] = None
    callsTotal: int = 0
    callsSucceeded: int = 0
    callsFailed: int = 0
    callsBlocked: int = 0
    lastUpdatedAt: str = ""
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderQualityScore(BaseModel):
    providerId: str
    qualityScore: float = 0.0
    validationPassRate: float = 0.0
    averageConfidence: float = 0.0
    unsafeOutputRate: float = 0.0
    emptyOutputRate: float = 0.0
    malformedOutputRate: float = 0.0
    conflictRate: float = 0.0
    samplesCount: int = 0
    lastUpdatedAt: str = ""
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderBudgetLimits(BaseModel):
    providerId: str
    enabled: bool = True
    maxCallsPerSession: Optional[int] = 20
    maxCallsPerDay: Optional[int] = 200
    maxEstimatedTokensPerSession: Optional[int] = 50000
    maxEstimatedTokensPerDay: Optional[int] = 300000
    maxFailuresPerSession: Optional[int] = 5
    maxConsecutiveFailures: Optional[int] = 3
    maxAverageLatencyMs: Optional[int] = 60000
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderLimitCheckResult(BaseModel):
    providerId: str
    status: ProviderLimitStatus = "ok"
    allowed: bool = True
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    counters: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderFallbackChain(BaseModel):
    chainId: str = ""
    displayName: str = ""
    providerIds: List[str] = Field(default_factory=list)
    strategy: ProviderSelectionStrategy = "fallback_order"
    enabled: bool = True
    stopOnFirstSuccess: bool = True
    maxProvidersToTry: int = 3
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderSelectionRequest(BaseModel):
    taskType: Optional[str] = None
    requiredCapabilities: List[str] = Field(default_factory=list)
    strategy: ProviderSelectionStrategy = "balanced"
    candidateProviderIds: List[str] = Field(default_factory=list)
    excludeProviderIds: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderSelectionResult(BaseModel):
    selectedProviderIds: List[str] = Field(default_factory=list)
    orderedCandidates: List[Dict[str, Any]] = Field(default_factory=list)
    strategy: ProviderSelectionStrategy = "balanced"
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderOutputComparison(BaseModel):
    comparisonId: str
    providerIds: List[str] = Field(default_factory=list)
    summary: str = ""
    agreementLevel: Literal["none", "low", "medium", "high", "unknown"] = "unknown"
    commonClaims: List[str] = Field(default_factory=list)
    disagreements: List[str] = Field(default_factory=list)
    riskFlags: List[str] = Field(default_factory=list)
    recommendedProviderId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MultiProviderReviewRequest(BaseModel):
    reviewId: Optional[str] = None
    input: str
    providerIds: List[str] = Field(default_factory=list)
    mode: ProviderReviewMode = "metadata_only"
    strategy: ProviderSelectionStrategy = "balanced"
    maxProviders: int = 3
    requireConsensus: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class MultiProviderReviewResult(BaseModel):
    reviewId: str
    status: Literal["completed", "blocked", "partial", "failed"] = "blocked"
    mode: ProviderReviewMode = "metadata_only"
    providerResults: List[Dict[str, Any]] = Field(default_factory=list)
    comparison: Optional[ProviderOutputComparison] = None
    consensus: Optional[Dict[str, Any]] = None
    selectedProviderId: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderComparisonReport(BaseModel):
    reportId: str
    createdAt: str = ""
    providers: List[Dict[str, Any]] = Field(default_factory=list)
    reliabilityScores: List[ProviderReliabilityScore] = Field(default_factory=list)
    qualityScores: List[ProviderQualityScore] = Field(default_factory=list)
    usageSummaries: List[Dict[str, Any]] = Field(default_factory=list)
    fallbackChains: List[ProviderFallbackChain] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
