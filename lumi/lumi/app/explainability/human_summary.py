from lumi.app.explainability.explanation_templates import get_template


class HumanSummaryBuilder:
    def build_human_summary(self, record) -> dict:
        template = get_template(record.status)
        confidence = f"Confidence: {record.confidence:.0%}"
        risk = f"Risk level: {record.riskLevel}"
        route = f"Route: {record.routeStatus}" if record.routeStatus else None
        validation = f"Validation: {record.validationStatus}. Accepted providers: {len(record.acceptedProviderIds)}, rejected providers: {len(record.rejectedProviderIds)}" if record.validationStatus else None
        conflict = f"Conflict detected: {record.conflictType}" if record.conflictDetected else "No conflict detected"
        action = None
        if record.actionGatewayStatus:
            action = f"Action gateway: {record.actionGatewayStatus}"
            if record.approvalPromptId:
                action += f". Approval prompt: {record.approvalPromptId}"
        return {
            "title": template["title"],
            "shortAnswer": template["shortAnswer"],
            "statusExplanation": template["statusExplanation"],
            "confidenceExplanation": confidence,
            "riskExplanation": risk,
            "routeExplanation": route,
            "validationExplanation": validation,
            "conflictExplanation": conflict,
            "policyExplanation": None,
            "actionExplanation": action,
            "requiredNextStep": record.requiredNextStep,
            "userFacingSummary": template["userFacingSummary"],
        }
