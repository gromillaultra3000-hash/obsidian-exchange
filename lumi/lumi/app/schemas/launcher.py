from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

LauncherStatus = Literal["ready", "warning", "failed", "unknown"]

class PortCheckResult(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    available: bool = False
    message: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

class StartupCheckResult(BaseModel):
    checkId: str
    title: str
    status: LauncherStatus = "unknown"
    message: str = ""
    required: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LauncherDiagnostics(BaseModel):
    status: LauncherStatus = "unknown"
    pythonAvailable: bool = False
    fastapiAvailable: bool = False
    portCheck: PortCheckResult = Field(default_factory=PortCheckResult)
    dataDirReady: bool = False
    logsDirReady: bool = False
    uiAssetsReady: bool = False
    startupChecks: List[StartupCheckResult] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LaunchReport(BaseModel):
    reportId: str
    createdAt: str = ""
    status: LauncherStatus = "unknown"
    dashboardUrl: str = "http://127.0.0.1:8000/ui"
    backendHost: str = "127.0.0.1"
    backendPort: int = 8000
    logPath: Optional[str] = None
    diagnostics: LauncherDiagnostics = Field(default_factory=LauncherDiagnostics)
    metadata: Dict[str, Any] = Field(default_factory=dict)
