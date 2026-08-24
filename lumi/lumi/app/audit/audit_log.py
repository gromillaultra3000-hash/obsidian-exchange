import uuid
from datetime import datetime, timezone
from typing import List, Optional
from lumi.app.schemas.audit import AuditEntry
from lumi.app.core.errors import AuditNotFoundError
from lumi.app.providers.redaction import RedactionUtil


class AuditLog:
    def __init__(self, redaction: RedactionUtil | None = None):
        self._entries: list[AuditEntry] = []
        self.redaction = redaction or RedactionUtil()

    def add_entry(self, event_type: str, task_id: Optional[str] = None, provider_id: Optional[str] = None,
                  decision_id: Optional[str] = None, status: str = "ok", summary: str = "",
                  details: dict | None = None) -> AuditEntry:
        safe_details = self.redaction.redact_dict(details or {})
        entry = AuditEntry(
            auditId=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            eventType=event_type,
            taskId=task_id,
            providerId=provider_id,
            decisionId=decision_id,
            status=status,
            summary=summary,
            details=safe_details,
        )
        self._entries.append(entry)
        return entry

    def list_entries(self) -> List[AuditEntry]:
        return list(self._entries)

    def get_entry(self, audit_id: str) -> AuditEntry:
        for entry in self._entries:
            if entry.auditId == audit_id:
                return entry
        raise AuditNotFoundError(audit_id)

    def filter_by_task(self, task_id: str) -> List[AuditEntry]:
        return [e for e in self._entries if e.taskId == task_id]

    def clear_for_tests(self):
        self._entries.clear()
