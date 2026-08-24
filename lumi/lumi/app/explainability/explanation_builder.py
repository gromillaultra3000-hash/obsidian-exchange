import uuid
from lumi.app.schemas.explainability import DecisionExplanation, ExplanationResult
from lumi.app.explainability.human_summary import HumanSummaryBuilder
from lumi.app.explainability.technical_summary import TechnicalSummaryBuilder


class ExplanationBuilder:
    def __init__(self, history_store, timeline_builder, audit_log=None, redaction=None):
        self.history_store = history_store
        self.timeline_builder = timeline_builder
        self.audit_log = audit_log
        self.redaction = redaction
        self.human = HumanSummaryBuilder()
        self.technical = TechnicalSummaryBuilder()

    def build_explanation_response(self, decision_id: str, mode: str = "human", include_timeline: bool = False):
        record = self.history_store.get_decision(decision_id)
        if not record:
            return None
        timeline = self.timeline_builder.build_timeline(decision_id=decision_id, task_id=record.taskId, session_id=record.sessionId) if include_timeline else None
        explanation = self.build_explanation(record, mode, timeline)
        if self.audit_log:
            self.audit_log.add_entry("decision_explanation_created", task_id=record.taskId, decision_id=record.decisionId, summary=f"Decision explanation created in {mode} mode")
        return ExplanationResult(explanation=explanation, timeline=timeline, metadata={"mode": mode})

    def build_explanation(self, record, mode: str = "human", timeline=None) -> DecisionExplanation:
        human = self.human.build_human_summary(record)
        technical = self.technical.build_technical_summary(record, timeline)
        if mode == "technical":
            title = f"Technical Explanation: {record.status}"
            short = f"Decision {record.decisionId}: {record.status}"
            user = record.summary
        elif mode == "compact":
            title = record.status
            short = human["shortAnswer"]
            user = human["userFacingSummary"]
            technical = {}
        else:
            title = human["title"]
            short = human["shortAnswer"]
            user = human["userFacingSummary"]
        return DecisionExplanation(
            explanationId=str(uuid.uuid4()),
            decisionId=record.decisionId,
            taskId=record.taskId,
            mode=mode,
            title=title,
            shortAnswer=short,
            statusExplanation=human["statusExplanation"],
            confidenceExplanation=human["confidenceExplanation"],
            routeExplanation=human.get("routeExplanation"),
            validationExplanation=human.get("validationExplanation"),
            conflictExplanation=human.get("conflictExplanation"),
            policyExplanation=human.get("policyExplanation"),
            actionExplanation=human.get("actionExplanation"),
            requiredNextStep=record.requiredNextStep,
            userFacingSummary=user,
            technicalDetails=technical,
            warnings=[],
            metadata={"historyRecordId": record.recordId},
        )
