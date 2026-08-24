import re
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.routing import TaskClassification


class TaskClassifier:
    def __init__(self):
        self.known_task_types = {
            "general_question", "analysis", "code_review", "document_review", "planning",
            "decision_request", "validation_request", "risk_review", "formatting_request",
            "project_improvement", "patch_planning", "test_failure_analysis", "fallback_request",
        }
        self.signal_patterns = {
            "code_related": re.compile(r"(code|function|class|bug|refactor|syntax|module|import|variable|method|api|endpoint)", re.I),
            "risk_related": re.compile(r"(risk|threat|security|safety|danger|vulnerability|exposure|policy)", re.I),
            "decision_related": re.compile(r"(approve|reject|should|proceed|decide|allow|deny|decision)", re.I),
            "error_related": re.compile(r"(error|failure|bug|issue|crash|exception|stack trace)", re.I),
            "test_related": re.compile(r"(test|coverage|assert|mock|unit test|integration test)", re.I),
            "project_related": re.compile(r"(project|architecture|design|system|component|module|improvement)", re.I),
            "patch_related": re.compile(r"(patch|fix|hotfix|update|deploy|release|upgrade)", re.I),
            "document_related": re.compile(r"(document|readme|manual|guide|specification|report)", re.I),
            "validation_related": re.compile(r"(validate|verify|check|ensure|confirm|compliance)", re.I),
            "planning_related": re.compile(r"(plan|strategy|roadmap|milestone|schedule|timeline)", re.I),
            "analysis_related": re.compile(r"(analyze|analysis|data|statistics|trends|patterns)", re.I),
            "formatting_related": re.compile(r"(format|structure|style|layout|template|convert)", re.I),
            "fallback_related": re.compile(r"(fallback|backup|default|alternative)", re.I),
        }

    def classify(self, task_request: TaskRequest) -> TaskClassification:
        detected: list[str] = []
        explicit = (task_request.taskType or "").strip().lower()
        if explicit in self.known_task_types:
            return TaskClassification(
                taskClass=explicit,
                confidence=0.95,
                detectedSignals=["explicit_task_type"],
                normalizedTaskType=explicit,
                riskLevel=self._risk_level_for(explicit, task_request),
                requiresMultipleProviders=explicit in {"project_improvement", "decision_request"},
                reason=f"Explicit taskType: {explicit}",
            )

        text = " ".join([
            task_request.input or "",
            task_request.expectedOutput or "",
            " ".join(str(v) for v in (task_request.requirements or {}).values()),
            " ".join(str(v) for v in (task_request.metadata or {}).values()),
        ])
        for name, pattern in self.signal_patterns.items():
            if pattern.search(text):
                detected.append(name)

        task_class = "general_question"
        confidence = 0.4
        reason = "No specific signals detected, defaulting to general_question"
        requires_multiple = False

        if "test_related" in detected and ("error_related" in detected or "code_related" in detected):
            task_class, confidence, reason = "test_failure_analysis", 0.78, "Test failure signals detected"
        elif "code_related" in detected:
            task_class, confidence, reason = "code_review", 0.72, "Code-related signals detected"
        elif "patch_related" in detected:
            task_class, confidence, reason = "patch_planning", 0.72, "Patch-related signals detected"
        elif "risk_related" in detected:
            task_class, confidence, reason = "risk_review", 0.82, "Risk-related signals detected"
        elif "decision_related" in detected:
            task_class, confidence, reason = "decision_request", 0.75, "Decision-related signals detected"
            requires_multiple = True
        elif "project_related" in detected:
            task_class, confidence, reason = "project_improvement", 0.70, "Project-related signals detected"
            requires_multiple = True
        elif "document_related" in detected:
            task_class, confidence, reason = "document_review", 0.68, "Document-related signals detected"
        elif "validation_related" in detected:
            task_class, confidence, reason = "validation_request", 0.70, "Validation-related signals detected"
        elif "planning_related" in detected:
            task_class, confidence, reason = "planning", 0.68, "Planning-related signals detected"
        elif "analysis_related" in detected:
            task_class, confidence, reason = "analysis", 0.65, "Analysis-related signals detected"
        elif "formatting_related" in detected:
            task_class, confidence, reason = "formatting_request", 0.65, "Formatting-related signals detected"
        elif "fallback_related" in detected:
            task_class, confidence, reason = "fallback_request", 0.65, "Fallback-related signals detected"

        return TaskClassification(
            taskClass=task_class,
            confidence=confidence,
            detectedSignals=detected,
            normalizedTaskType=explicit or None,
            riskLevel=self._risk_level_for(task_class, task_request),
            requiresMultipleProviders=requires_multiple,
            reason=reason,
        )

    def _risk_level_for(self, task_class: str, task_request: TaskRequest) -> str:
        req_risk = (task_request.requirements or {}).get("riskLevel")
        if req_risk in {"low", "medium", "high", "unknown"}:
            return req_risk
        if task_class in {"risk_review", "decision_request"}:
            return "high"
        if task_class in {"project_improvement", "patch_planning", "test_failure_analysis"}:
            return "medium"
        return "low" if task_class != "general_question" else "unknown"
