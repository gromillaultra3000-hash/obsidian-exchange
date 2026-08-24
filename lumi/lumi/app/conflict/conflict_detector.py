from __future__ import annotations
from datetime import datetime, timezone
from uuid import uuid4
from typing import Iterable
from lumi.app.schemas.provider import ProviderOutput
from lumi.app.schemas.validation import ValidationPipelineResult
from lumi.app.schemas.conflict import ProviderDecisionSignal, ConflictFinding, ConflictAnalysisReport

HIGH_RISK_MARKERS = {"critical", "high", "unsafe", "forbidden", "secret", "bypass", "timeout", "error"}

class ConflictDetector:
    def build_signals(self, outputs: Iterable[ProviderOutput], validation_result: ValidationPipelineResult | None = None) -> list[ProviderDecisionSignal]:
        validation_by_provider = {}
        if validation_result:
            validation_by_provider = {r.providerId: r.validationStatus for r in validation_result.results}
        signals = []
        for output in outputs:
            signals.append(ProviderDecisionSignal(
                providerId=output.providerId,
                role=output.role,
                suggestedStatus=output.suggestedStatus or "WAIT",
                confidence=float(output.confidence or 0.0),
                validationStatus=validation_by_provider.get(output.providerId),
                riskFlags=list(output.riskFlags or []),
                evidenceRefs=list(output.evidenceRefs or []),
                assumptions=list(output.assumptions or []),
                outputStatus=output.status,
            ))
        return signals

    def analyze(self, task_id: str, outputs: Iterable[ProviderOutput], validation_result: ValidationPipelineResult | None = None) -> ConflictAnalysisReport:
        signals = self.build_signals(outputs, validation_result)
        findings: list[ConflictFinding] = []
        statuses = sorted({s.suggestedStatus or "WAIT" for s in signals})
        confidences = [s.confidence for s in signals]
        confidence_spread = round((max(confidences) - min(confidences)), 4) if confidences else 0.0

        if "APPROVE" in statuses and "REJECT" in statuses:
            findings.append(ConflictFinding(conflictType="ACTION_CONFLICT", severity="high", reason="Provider outputs contain both APPROVE and REJECT suggestions", affectedProviders=[s.providerId for s in signals if s.suggestedStatus in {"APPROVE", "REJECT"}], rule="approve_reject_disagreement_requires_wait"))
        elif len(statuses) > 1 and any(s in statuses for s in ["APPROVE", "REJECT", "SAFE_DEFAULT"]):
            findings.append(ConflictFinding(conflictType="STRATEGY_CONFLICT", severity="medium", reason="Provider outputs suggest different decision statuses", affectedProviders=[s.providerId for s in signals], rule="mixed_statuses_lower_confidence"))

        risk_providers = []
        for s in signals:
            joined = " ".join(s.riskFlags).lower()
            if any(marker in joined for marker in HIGH_RISK_MARKERS):
                risk_providers.append(s.providerId)
        if risk_providers:
            findings.append(ConflictFinding(conflictType="RISK_CONFLICT", severity="high", reason="At least one provider output contains high-risk flags", affectedProviders=risk_providers, rule="risk_flag_forces_conservative_status"))

        if confidence_spread > 0.35 and len(signals) > 1:
            findings.append(ConflictFinding(conflictType="CONFIDENCE_CONFLICT", severity="medium", reason="Provider confidence scores diverge beyond threshold", affectedProviders=[s.providerId for s in signals], rule="confidence_spread_requires_wait", metadata={"confidenceSpread": confidence_spread}))

        if validation_result and validation_result.rejectedOutputs > 0 and validation_result.acceptedProviderIds:
            findings.append(ConflictFinding(conflictType="VALIDATION_CONFLICT", severity="medium", reason="Some provider outputs were rejected by validation while others were accepted", affectedProviders=list(validation_result.rejectedProviderIds), rule="validation_rejection_lowers_confidence"))

        if any(s.suggestedStatus == "APPROVE" and not s.evidenceRefs and not s.assumptions for s in signals):
            findings.append(ConflictFinding(conflictType="DATA_CONFLICT", severity="medium", reason="At least one approval signal lacks evidence or assumptions", affectedProviders=[s.providerId for s in signals if s.suggestedStatus == "APPROVE" and not s.evidenceRefs and not s.assumptions], rule="approval_without_evidence_requires_wait"))

        severity_weight = {"none": 0.0, "low": 0.15, "medium": 0.35, "high": 0.65, "critical": 1.0}
        disagreement_score = round(min(1.0, sum(severity_weight.get(f.severity, 0.0) for f in findings) / max(1, len(findings)) + min(0.25, confidence_spread * 0.25)), 4) if findings else 0.0
        primary = "NONE"
        if findings:
            ordered = sorted(findings, key=lambda f: severity_weight.get(f.severity, 0.0), reverse=True)
            primary = ordered[0].conflictType
        return ConflictAnalysisReport(
            conflictReportId=f"conf-{uuid4().hex[:12]}",
            taskId=task_id,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            totalSignals=len(signals),
            conflictDetected=bool(findings),
            primaryConflictType=primary,
            disagreementScore=disagreement_score,
            confidenceSpread=confidence_spread,
            statusSpread=statuses,
            findings=findings,
            signals=signals,
            summary="No conflict detected" if not findings else f"Detected {len(findings)} conflict finding(s); primary={primary}",
        )
