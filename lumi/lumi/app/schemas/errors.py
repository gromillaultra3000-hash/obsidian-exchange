from typing import Dict, Any
from pydantic import BaseModel, Field


class ErrorEnvelope(BaseModel):
    errorId: str
    code: str
    message: str
    recoverable: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False
