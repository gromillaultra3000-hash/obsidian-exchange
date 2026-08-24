class TechnicalSummaryBuilder:
    def build_technical_summary(self, record, timeline=None) -> dict:
        return {
            "decision": {"decisionId": record.decisionId, "taskId": record.taskId, "status": record.status, "confidence": record.confidence, "riskLevel": record.riskLevel},
            "routing": {"routeStatus": record.routeStatus, "providerIds": record.providerIds},
            "validation": {"validationStatus": record.validationStatus, "acceptedProviderIds": record.acceptedProviderIds, "rejectedProviderIds": record.rejectedProviderIds},
            "conflict": {"conflictDetected": record.conflictDetected, "conflictType": record.conflictType},
            "resolution": {"deterministicStatus": record.deterministicStatus},
            "policyAndAction": {"actionGatewayStatus": record.actionGatewayStatus, "approvalPromptId": record.approvalPromptId},
            "audit": {"timelineEventCount": len(timeline.events) if timeline else 0},
            "metadata": record.metadata,
        }
