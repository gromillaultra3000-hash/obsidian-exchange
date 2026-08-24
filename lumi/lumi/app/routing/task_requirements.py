from lumi.app.schemas.routing import TaskClassification, TaskRequirements


class TaskRequirementsBuilder:
    def __init__(self):
        self.requirements_map = {
            "general_question": dict(requiredCapabilities=["text_reasoning"], optionalCapabilities=["summarization", "structured_output"], requiredRoles=["reviewer"], optionalRoles=[], minProviders=1, maxProviders=1, requireValidation=False, expectedDecisionStatuses=["APPROVE", "WAIT"]),
            "analysis": dict(requiredCapabilities=["data_analysis", "text_reasoning"], optionalCapabilities=["structured_output"], requiredRoles=["data_analyst", "reviewer"], optionalRoles=[], minProviders=1, maxProviders=2, requireValidation=True, expectedDecisionStatuses=["APPROVE", "WAIT"]),
            "code_review": dict(requiredCapabilities=["code_analysis", "critique", "validation"], optionalCapabilities=["error_analysis"], requiredRoles=["code_reviewer", "validator"], optionalRoles=["critic"], minProviders=1, maxProviders=2, requireValidation=True, expectedDecisionStatuses=["APPROVE", "REJECT", "WAIT"]),
            "document_review": dict(requiredCapabilities=["document_review", "text_reasoning"], optionalCapabilities=["summarization", "critique"], requiredRoles=["document_reviewer"], optionalRoles=["reviewer", "critic"], minProviders=1, maxProviders=2, requireValidation=False, expectedDecisionStatuses=["APPROVE", "WAIT"]),
            "planning": dict(requiredCapabilities=["planning", "text_reasoning"], optionalCapabilities=["decision_support"], requiredRoles=["planner"], optionalRoles=["reviewer"], minProviders=1, maxProviders=2, requireValidation=True, expectedDecisionStatuses=["APPROVE", "WAIT"]),
            "decision_request": dict(requiredCapabilities=["decision_support", "risk_review"], optionalCapabilities=["policy_checking"], requiredRoles=["planner", "risk_checker"], optionalRoles=["final_resolver"], minProviders=2, maxProviders=3, requireValidation=True, expectedDecisionStatuses=["APPROVE", "REJECT", "WAIT"]),
            "validation_request": dict(requiredCapabilities=["validation", "format_checking"], optionalCapabilities=["critique"], requiredRoles=["validator"], optionalRoles=["critic"], minProviders=1, maxProviders=2, requireValidation=True, expectedDecisionStatuses=["APPROVE", "REJECT"]),
            "risk_review": dict(requiredCapabilities=["risk_review", "policy_checking"], optionalCapabilities=["decision_support"], requiredRoles=["risk_checker", "policy_checker"], optionalRoles=[], minProviders=1, maxProviders=2, requireValidation=True, expectedDecisionStatuses=["APPROVE", "WAIT", "REJECT"]),
            "formatting_request": dict(requiredCapabilities=["format_checking", "structured_output"], optionalCapabilities=["summarization"], requiredRoles=["formatter"], optionalRoles=[], minProviders=1, maxProviders=1, requireValidation=False, expectedDecisionStatuses=["APPROVE"]),
            "project_improvement": dict(requiredCapabilities=["project_review", "planning", "error_analysis"], optionalCapabilities=["code_analysis", "critique"], requiredRoles=["project_reviewer", "planner", "critic"], optionalRoles=["code_reviewer"], minProviders=2, maxProviders=3, requireValidation=True, expectedDecisionStatuses=["APPROVE", "WAIT"]),
            "patch_planning": dict(requiredCapabilities=["patch_planning", "code_analysis", "error_analysis"], optionalCapabilities=["planning"], requiredRoles=["patch_planner", "code_reviewer"], optionalRoles=["critic"], minProviders=1, maxProviders=2, requireValidation=True, expectedDecisionStatuses=["APPROVE", "WAIT"]),
            "test_failure_analysis": dict(requiredCapabilities=["test_analysis", "error_analysis", "code_analysis"], optionalCapabilities=["critique"], requiredRoles=["test_checker", "code_reviewer"], optionalRoles=["critic"], minProviders=1, maxProviders=2, requireValidation=True, expectedDecisionStatuses=["APPROVE", "WAIT"]),
            "fallback_request": dict(requiredCapabilities=["fallback_use", "text_reasoning"], optionalCapabilities=["fast_response", "low_cost_processing"], requiredRoles=["fallback_provider"], optionalRoles=[], minProviders=1, maxProviders=1, requireValidation=False, expectedDecisionStatuses=["WAIT", "SAFE_DEFAULT"]),
        }

    def build(self, classification: TaskClassification) -> TaskRequirements:
        task_class = classification.taskClass
        defaults = self.requirements_map.get(task_class, self.requirements_map["general_question"])
        return TaskRequirements(
            taskClass=task_class,
            requiredCapabilities=list(defaults["requiredCapabilities"]),
            optionalCapabilities=list(defaults["optionalCapabilities"]),
            requiredRoles=list(defaults["requiredRoles"]),
            optionalRoles=list(defaults["optionalRoles"]),
            minProviders=int(defaults["minProviders"]),
            maxProviders=int(defaults["maxProviders"]),
            riskLevel=classification.riskLevel,
            allowFallback=task_class not in {"risk_review"},
            requireValidation=bool(defaults["requireValidation"]),
            expectedDecisionStatuses=list(defaults["expectedDecisionStatuses"]),
        )
