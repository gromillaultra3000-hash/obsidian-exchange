import uuid
from datetime import datetime, timezone
from typing import Optional, List
from lumi.app.schemas.dialog import DialogMessage
from lumi.app.providers.redaction import RedactionUtil


class DialogMessageStore:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._messages: dict[str, DialogMessage] = {}
        self._by_session: dict[str, list[str]] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def add_message(self, session_id: str, role: str, text: str, command_type: str = "general_message", linked_task_id: Optional[str] = None, linked_decision_id: Optional[str] = None, linked_approval_prompt_id: Optional[str] = None, metadata: Optional[dict] = None) -> DialogMessage:
        message_id = str(uuid.uuid4())
        safe_text = self.redaction.redact_secret_like(text or "")
        safe_metadata = self.redaction.redact_dict(metadata or {})
        message = DialogMessage(messageId=message_id, sessionId=session_id, role=role, createdAt=datetime.now(timezone.utc).isoformat(), text=safe_text, commandType=command_type, linkedTaskId=linked_task_id, linkedDecisionId=linked_decision_id, linkedApprovalPromptId=linked_approval_prompt_id, metadata=safe_metadata)
        self._messages[message_id] = message
        self._by_session.setdefault(session_id, []).append(message_id)
        if self.audit_log:
            self.audit_log.add_entry("dialog_message_received", summary=f"Dialog message stored for session {session_id}", details={"role": role, "commandType": command_type, "messageId": message_id})
        return message

    def list_messages(self, session_id: str) -> List[DialogMessage]:
        return [self._messages[mid] for mid in self._by_session.get(session_id, []) if mid in self._messages]

    def get_message(self, message_id: str) -> Optional[DialogMessage]:
        return self._messages.get(message_id)

    def list_all(self) -> List[DialogMessage]:
        return list(self._messages.values())

    def clear_for_tests(self):
        self._messages.clear()
        self._by_session.clear()
