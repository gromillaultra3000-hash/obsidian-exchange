import uuid
from datetime import datetime, timezone
from typing import Optional, List
from lumi.app.schemas.dialog import DialogSession


class DialogSessionStore:
    def __init__(self, audit_log=None, redaction=None):
        self._sessions: dict[str, DialogSession] = {}
        self.audit_log = audit_log
        self.redaction = redaction

    def create_session(self, host_app_id: Optional[str] = None, user_id: Optional[str] = None, title: Optional[str] = None, metadata: Optional[dict] = None) -> DialogSession:
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        safe_metadata = self.redaction.redact_dict(metadata or {}) if self.redaction else (metadata or {})
        session = DialogSession(sessionId=session_id, hostAppId=host_app_id, userId=user_id, title=title or f"Session {session_id[:8]}", status="active", createdAt=now, updatedAt=now, metadata=safe_metadata)
        self._sessions[session_id] = session
        if self.audit_log:
            self.audit_log.add_entry("dialog_session_created", summary=f"Dialog session {session_id} created", details={"sessionId": session_id, "hostAppId": host_app_id})
        return session

    def get_session(self, session_id: str) -> Optional[DialogSession]:
        return self._sessions.get(session_id)

    def list_sessions(self) -> List[DialogSession]:
        return list(self._sessions.values())

    def close_session(self, session_id: str) -> Optional[DialogSession]:
        session = self._sessions.get(session_id)
        if session:
            session.status = "closed"
            session.updatedAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("dialog_session_closed", summary=f"Dialog session {session_id} closed")
        return session

    def pause_session(self, session_id: str) -> Optional[DialogSession]:
        session = self._sessions.get(session_id)
        if session:
            session.status = "paused"
            session.updatedAt = datetime.now(timezone.utc).isoformat()
        return session

    def activate_session(self, session_id: str) -> Optional[DialogSession]:
        session = self._sessions.get(session_id)
        if session:
            session.status = "active"
            session.updatedAt = datetime.now(timezone.utc).isoformat()
        return session

    def link_decision(self, session_id: str, decision_id: str):
        session = self._sessions.get(session_id)
        if session and decision_id not in session.linkedDecisionIds:
            session.linkedDecisionIds.append(decision_id)
            session.updatedAt = datetime.now(timezone.utc).isoformat()
            if self.audit_log:
                self.audit_log.add_entry("dialog_decision_linked", decision_id=decision_id, summary=f"Decision {decision_id} linked to dialog session {session_id}")
        return session

    def session_exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    def clear_for_tests(self):
        self._sessions.clear()
