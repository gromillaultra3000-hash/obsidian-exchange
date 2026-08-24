from typing import Optional
from lumi.app.audit.audit_log import AuditLog
from lumi.app.schemas.history import TimelineEvent, DecisionTimeline


class TimelineBuilder:
    def __init__(self, audit_log: AuditLog, decision_history=None):
        self.audit_log = audit_log
        self.decision_history = decision_history

    def build_timeline(self, decision_id: Optional[str] = None, task_id: Optional[str] = None, session_id: Optional[str] = None) -> DecisionTimeline:
        if decision_id and not task_id and self.decision_history:
            record = self.decision_history.get_decision(decision_id)
            if record:
                task_id = record.taskId
                session_id = session_id or record.sessionId
        entries = self.audit_log.list_entries()
        if task_id:
            entries = [e for e in entries if e.taskId == task_id or e.decisionId == decision_id]
        elif decision_id:
            entries = [e for e in entries if e.decisionId == decision_id]
        entries = sorted(entries, key=lambda e: e.timestamp)
        events = [self._entry_to_event(e, session_id) for e in entries]
        primary_task = task_id or (entries[0].taskId if entries and entries[0].taskId else "unknown")
        summary = self._summary(events)
        if self.audit_log:
            self.audit_log.add_entry("decision_timeline_built", task_id=primary_task, decision_id=decision_id, summary=f"Timeline built with {len(events)} events")
        return DecisionTimeline(decisionId=decision_id or "unknown", taskId=primary_task, sessionId=session_id, events=events, summary=summary, metadata={"totalEvents": len(events)})

    def _entry_to_event(self, entry, session_id: Optional[str]) -> TimelineEvent:
        severity = "info"
        if entry.status == "error" or entry.eventType in {"error_recorded", "routing_failed", "action_blocked", "policy_blocked_action"}:
            severity = "error"
        if entry.eventType in {"provider_output_rejected", "conflict_detected", "policy_required_approval", "action_approval_required"}:
            severity = "warning"
        if "critical" in (entry.summary or "").lower():
            severity = "critical"
        return TimelineEvent(eventId=entry.auditId, timestamp=entry.timestamp, eventType=entry.eventType, taskId=entry.taskId, decisionId=entry.decisionId, sessionId=session_id, providerId=entry.providerId, title=entry.eventType.replace("_", " ").title(), summary=entry.summary, severity=severity, metadata={"status": entry.status})

    def _summary(self, events: list[TimelineEvent]) -> str:
        types = {e.eventType for e in events}
        parts = []
        for typ, label in [("task_received", "Task received"), ("route_plan_created", "Route planned"), ("validation_pipeline_completed", "Outputs validated"), ("conflict_analysis_completed", "Conflicts analyzed"), ("deterministic_resolution_completed", "Decision resolved"), ("policy_check_completed", "Policy checked"), ("decision_created", "Decision created")]:
            if typ in types:
                parts.append(label)
        return " -> ".join(parts) if parts else "Timeline"
