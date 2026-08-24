TEMPLATES = {
    "APPROVE": {"title": "Decision: Approved", "shortAnswer": "The request can proceed to the next controlled step.", "statusExplanation": "The resolver selected APPROVE based on validated provider outputs and deterministic rules.", "userFacingSummary": "Approved for the next controlled step. Any host action still passes policy and approval gates."},
    "WAIT": {"title": "Decision: Wait", "shortAnswer": "More information or review is needed before proceeding.", "statusExplanation": "The resolver selected WAIT because confidence, routing, validation, conflict, or policy conditions are not sufficient for approval.", "userFacingSummary": "Wait. Review the next step and provide more context or approvals if needed."},
    "SAFE_DEFAULT": {"title": "Decision: Safe Default", "shortAnswer": "The safe default was selected.", "statusExplanation": "The resolver selected SAFE_DEFAULT because outputs were rejected, unsafe content appeared, or safe completion was not possible.", "userFacingSummary": "Blocked for safety. Review the issues before retrying."},
    "ASK_USER": {"title": "Decision: User Input Required", "shortAnswer": "A user decision is required.", "statusExplanation": "The resolver requires explicit user input before continuing.", "userFacingSummary": "Review the prompt and approve, reject, or request details."},
    "REJECT": {"title": "Decision: Rejected", "shortAnswer": "The request was rejected.", "statusExplanation": "The resolver rejected the request based on validation, conflict, or policy conditions.", "userFacingSummary": "Rejected. Address the identified issues before resubmitting."},
    "ESCALATE": {"title": "Decision: Escalate", "shortAnswer": "Escalation is required.", "statusExplanation": "The resolver cannot safely complete this request without escalation.", "userFacingSummary": "Escalate to the appropriate reviewer or owner."},
}


def get_template(status: str) -> dict:
    return TEMPLATES.get(status, TEMPLATES["WAIT"])
