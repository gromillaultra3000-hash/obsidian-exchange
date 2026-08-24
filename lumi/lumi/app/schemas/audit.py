from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class AuditEntry(BaseModel):
    auditId: str
    timestamp: str
    eventType: str
    taskId: Optional[str] = None
    providerId: Optional[str] = None
    decisionId: Optional[str] = None
    status: str = "ok"
    summary: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)
