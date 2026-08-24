from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field
from lumi.app.schemas.history import DecisionTimeline

ExplanationMode = Literal["human", "technical", "compact", "dialog"]


class DecisionExplanation(BaseModel):
    explanationId: str
    decisionId: str
    taskId: str
    mode: ExplanationMode = "human"
    title: str = ""
    shortAnswer: str = ""
    statusExplanation: str = ""
    confidenceExplanation: str = ""
    routeExplanation: Optional[str] = None
    validationExplanation: Optional[str] = None
    conflictExplanation: Optional[str] = None
    policyExplanation: Optional[str] = None
    actionExplanation: Optional[str] = None
    requiredNextStep: Optional[str] = None
    userFacingSummary: str = ""
    technicalDetails: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExplanationRequest(BaseModel):
    decisionId: str
    mode: ExplanationMode = "human"
    includeTechnicalDetails: bool = False
    includeAuditTimeline: bool = False


class ExplanationResult(BaseModel):
    explanation: DecisionExplanation
    timeline: Optional[DecisionTimeline] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
