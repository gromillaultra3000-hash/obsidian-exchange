from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class TaskRequest(BaseModel):
    taskId: Optional[str] = None
    taskType: Optional[str] = None
    input: str
    context: Dict[str, Any] = Field(default_factory=dict)
    requirements: Dict[str, Any] = Field(default_factory=dict)
    expectedOutput: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
