from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

UiPanelStatus = Literal["ready", "loading", "error", "disabled"]

class UiDashboardSummary(BaseModel):
    version: str = ""
    runtimeStatus: Dict[str, Any] = Field(default_factory=dict)
    health: Dict[str, Any] = Field(default_factory=dict)
    counts: Dict[str, int] = Field(default_factory=dict)
    safetyLabels: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class UiPanelConfig(BaseModel):
    panelId: str
    title: str
    status: UiPanelStatus = "ready"
    enabled: bool = True
    description: str = ""
    requiredEndpoints: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class UiSafetyLabel(BaseModel):
    labelId: str
    title: str
    level: Literal["info", "warning", "critical"] = "info"
    description: str = ""
    active: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class UiActionButton(BaseModel):
    buttonId: str
    label: str
    actionType: str
    enabled: bool
    requiresConfirmation: bool = False
    safetyNote: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class UiWizardStep(BaseModel):
    stepId: str
    title: str
    description: str = ""
    status: Literal["pending", "active", "completed", "blocked"] = "pending"
    required: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class UiWizardState(BaseModel):
    wizardId: str
    title: str = ""
    steps: List[UiWizardStep] = Field(default_factory=list)
    currentStepId: Optional[str] = None
    completed: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
