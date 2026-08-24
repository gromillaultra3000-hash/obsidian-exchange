from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


class DecisionHistoryRecord(BaseModel):
    recordId: str
    decisionId: str
    taskId: str
    sessionId: Optional[str] = None
    createdAt: str
    status: str
    actionAllowed: bool = False
    confidence: float = 0.0
    riskLevel: str = "unknown"
    taskClass: Optional[str] = None
    routeStatus: Optional[str] = None
    validationStatus: Optional[str] = None
    conflictDetected: bool = False
    conflictType: Optional[str] = None
    deterministicStatus: Optional[str] = None
    actionGatewayStatus: Optional[str] = None
    approvalPromptId: Optional[str] = None
    summary: str = ""
    requiredNextStep: Optional[str] = None
    providerIds: List[str] = Field(default_factory=list)
    acceptedProviderIds: List[str] = Field(default_factory=list)
    rejectedProviderIds: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionHistoryQuery(BaseModel):
    status: Optional[str] = None
    taskId: Optional[str] = None
    sessionId: Optional[str] = None
    taskClass: Optional[str] = None
    providerId: Optional[str] = None
    conflictType: Optional[str] = None
    actionGatewayStatus: Optional[str] = None
    limit: int = 50
    offset: int = 0


class DecisionHistoryResult(BaseModel):
    total: int = 0
    limit: int = 50
    offset: int = 0
    records: List[DecisionHistoryRecord] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    eventId: str
    timestamp: str
    eventType: str
    taskId: Optional[str] = None
    decisionId: Optional[str] = None
    sessionId: Optional[str] = None
    providerId: Optional[str] = None
    title: str
    summary: str
    severity: Literal["info", "warning", "error", "critical"] = "info"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionTimeline(BaseModel):
    decisionId: str
    taskId: str
    sessionId: Optional[str] = None
    events: List[TimelineEvent] = Field(default_factory=list)
    summary: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
