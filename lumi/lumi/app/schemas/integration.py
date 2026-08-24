from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

HostAppType = Literal["desktop", "mobile", "web", "backend", "cli", "service", "unknown"]
HostAppStatus = Literal["registered", "active", "paused", "disabled", "unknown"]
ConnectorMode = Literal["rest", "sdk", "sidecar", "embedded", "webhook"]


class HostAppManifest(BaseModel):
    hostAppId: str
    displayName: str
    appType: HostAppType = "unknown"
    version: Optional[str] = None
    description: Optional[str] = None
    allowedOrigins: List[str] = Field(default_factory=list)
    allowedModes: List[ConnectorMode] = Field(default_factory=list)
    capabilitiesRequested: List[str] = Field(default_factory=list)
    actionsAllowed: List[str] = Field(default_factory=list)
    eventsSupported: List[str] = Field(default_factory=list)
    callbacks: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HostAppProfile(BaseModel):
    hostAppId: str
    displayName: str
    appType: HostAppType = "unknown"
    status: HostAppStatus = "registered"
    manifest: HostAppManifest
    registeredAt: str = ""
    lastSeenAt: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IntegrationHandshakeRequest(BaseModel):
    hostAppId: str
    manifest: HostAppManifest
    connectorMode: ConnectorMode = "rest"
    clientVersion: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IntegrationHandshakeResult(BaseModel):
    handshakeId: str
    hostAppId: str
    accepted: bool = False
    status: str = "rejected"
    connectorMode: ConnectorMode = "rest"
    runtimeVersion: str = "0.7.0"
    supportedCapabilities: List[str] = Field(default_factory=list)
    requiredNextStep: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


HostEventType = Literal[
    "user_message", "file_uploaded", "error_log", "status_change", "action_requested", "approval_response", "custom"
]


class HostEvent(BaseModel):
    eventId: str
    hostAppId: str
    sessionId: Optional[str] = None
    eventType: HostEventType = "custom"
    payload: Dict[str, Any] = Field(default_factory=dict)
    createdAt: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HostEventResult(BaseModel):
    eventResultId: str
    eventId: str
    accepted: bool = False
    taskId: Optional[str] = None
    decisionId: Optional[str] = None
    dialogResponse: Optional[Dict[str, Any]] = None
    status: str = "rejected"
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionCallbackConfig(BaseModel):
    callbackId: str
    hostAppId: str
    url: Optional[str] = None
    enabled: bool = True
    eventTypes: List[str] = Field(default_factory=list)
    mode: Literal["none", "mock", "http"] = "mock"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionCallbackPayload(BaseModel):
    callbackId: str
    hostAppId: str
    decisionId: str
    taskId: str
    status: str
    summary: str
    actionGatewayStatus: Optional[str] = None
    approvalPromptId: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionCallbackResult(BaseModel):
    callbackResultId: str
    callbackId: str
    delivered: bool = False
    mode: str = "mock"
    status: str = "unknown"
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SidecarStatus(BaseModel):
    mode: str = "local"
    host: str = "127.0.0.1"
    port: int = 8000
    baseUrl: str = "http://127.0.0.1:8000"
    running: bool = False
    runtimeStatus: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
