import uuid
from datetime import datetime, timezone
from typing import Optional, List
from lumi.app.schemas.history import DecisionHistoryRecord, DecisionHistoryQuery, DecisionHistoryResult
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.schemas.task import TaskRequest
from lumi.app.providers.redaction import RedactionUtil


class DecisionHistoryStore:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._records: dict[str, DecisionHistoryRecord] = {}
        self._by_task_id: dict[str, list[str]] = {}
        self._by_session_id: dict[str, list[str]] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def add_decision(self, decision: StructuredDecision, task_request: Optional[TaskRequest] = None, session_id: Optional[str] = None) -> DecisionHistoryRecord:
        if decision.decisionId in self._records:
            record = self._records[decision.decisionId]
            if session_id and not record.sessionId:
                self.link_decision_to_session(decision.decisionId, session_id)
            return self._records[decision.decisionId]

        metadata = decision.metadata or {}
        task_classification = metadata.get("taskClassification", {}) if isinstance(metadata.get("taskClassification"), dict) else {}
        route_plan = metadata.get("routePlan", {}) if isinstance(metadata.get("routePlan"), dict) else {}
        validation_pipeline = metadata.get("validationPipeline", {}) if isinstance(metadata.get("validationPipeline"), dict) else {}
        conflict_report = metadata.get("conflictReport", {}) if isinstance(metadata.get("conflictReport"), dict) else {}
        deterministic = metadata.get("deterministicResolution", {}) if isinstance(metadata.get("deterministicResolution"), dict) else {}
        action_result = metadata.get("actionGatewayResult", {}) if isinstance(metadata.get("actionGatewayResult"), dict) else {}
        approval_prompt = metadata.get("approvalPrompt", {}) if isinstance(metadata.get("approvalPrompt"), dict) else {}

        conflict_type = decision.conflictType or conflict_report.get("primaryConflictType") or conflict_report.get("conflictType")
        conflict_detected = bool(decision.conflictDetected or conflict_report.get("conflictDetected", False))
        action_status = action_result.get("status")
        selected = list(route_plan.get("selectedProviders", [])) if isinstance(route_plan.get("selectedProviders", []), list) else []

        safe_metadata = self.redaction.redact_dict({
            "winningRule": decision.winningRule,
            "routeStatus": route_plan.get("routeStatus"),
            "strategy": route_plan.get("strategy"),
            "validationStatus": validation_pipeline.get("overallValidationStatus") or validation_pipeline.get("status"),
            "conflictDetected": conflict_detected,
            "conflictType": conflict_type,
            "deterministicStatus": deterministic.get("status"),
            "deterministicRule": deterministic.get("winningRule") or deterministic.get("rule"),
            "actionGatewayStatus": action_status,
        })

        record = DecisionHistoryRecord(
            recordId=str(uuid.uuid4()),
            decisionId=decision.decisionId,
            taskId=decision.taskId,
            sessionId=session_id,
            createdAt=datetime.now(timezone.utc).isoformat(),
            status=decision.status,
            actionAllowed=decision.actionAllowed,
            confidence=decision.confidence,
            riskLevel=decision.riskLevel,
            taskClass=task_classification.get("taskClass"),
            routeStatus=route_plan.get("routeStatus") or metadata.get("routeStatus"),
            validationStatus=validation_pipeline.get("overallValidationStatus") or validation_pipeline.get("status"),
            conflictDetected=conflict_detected,
            conflictType=None if conflict_type in ("NONE", "none") else conflict_type,
            deterministicStatus=deterministic.get("status"),
            actionGatewayStatus=action_status,
            approvalPromptId=approval_prompt.get("promptId"),
            summary=self.redaction.redact_secret_like(decision.summary or ""),
            requiredNextStep=decision.requiredNextStep,
            providerIds=selected,
            acceptedProviderIds=list(metadata.get("acceptedProviderIds", [])),
            rejectedProviderIds=list(metadata.get("rejectedProviderIds", [])),
            metadata=safe_metadata,
        )
        self._records[decision.decisionId] = record
        self._by_task_id.setdefault(decision.taskId, []).append(decision.decisionId)
        if session_id:
            self._by_session_id.setdefault(session_id, []).append(decision.decisionId)
        if self.audit_log:
            self.audit_log.add_entry("decision_history_recorded", task_id=decision.taskId, decision_id=decision.decisionId, summary=f"Decision {decision.decisionId} recorded in history")
        return record

    def get_decision(self, decision_id: str) -> Optional[DecisionHistoryRecord]:
        record = self._records.get(decision_id)
        if self.audit_log:
            self.audit_log.add_entry("decision_history_lookup", decision_id=decision_id, summary=f"Decision history lookup: {decision_id}", status="ok" if record else "not_found")
        return record

    def list_decisions(self) -> List[DecisionHistoryRecord]:
        return list(self._records.values())

    def filter_decisions(self, query: DecisionHistoryQuery | None = None) -> DecisionHistoryResult:
        query = query or DecisionHistoryQuery()
        records = list(self._records.values())
        if query.status:
            records = [r for r in records if r.status == query.status]
        if query.taskId:
            records = [r for r in records if r.taskId == query.taskId]
        if query.sessionId:
            records = [r for r in records if r.sessionId == query.sessionId or r.decisionId in self._by_session_id.get(query.sessionId, [])]
        if query.taskClass:
            records = [r for r in records if r.taskClass == query.taskClass]
        if query.providerId:
            records = [r for r in records if query.providerId in r.providerIds or query.providerId in r.acceptedProviderIds or query.providerId in r.rejectedProviderIds]
        if query.conflictType:
            records = [r for r in records if r.conflictType == query.conflictType]
        if query.actionGatewayStatus:
            records = [r for r in records if r.actionGatewayStatus == query.actionGatewayStatus]
        total = len(records)
        offset = max(0, query.offset)
        limit = max(1, min(100, query.limit))
        result = DecisionHistoryResult(total=total, limit=limit, offset=offset, records=records[offset:offset + limit])
        if self.audit_log:
            self.audit_log.add_entry("decision_history_query", summary=f"Decision history query returned {len(result.records)} of {total}", details={"total": total, "limit": limit, "offset": offset})
        return result

    def link_decision_to_session(self, decision_id: str, session_id: str):
        record = self._records.get(decision_id)
        if not record:
            return None
        record.sessionId = session_id
        self._by_session_id.setdefault(session_id, [])
        if decision_id not in self._by_session_id[session_id]:
            self._by_session_id[session_id].append(decision_id)
        return record

    def clear_for_tests(self):
        self._records.clear()
        self._by_task_id.clear()
        self._by_session_id.clear()
