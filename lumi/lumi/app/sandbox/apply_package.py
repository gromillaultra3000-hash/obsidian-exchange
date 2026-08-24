from lumi.app.schemas.sandbox import ApplyPreparationPackage
from lumi.app.providers.redaction import RedactionUtil

class ApplyPackageService:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()
    def summarize_package(self, package: ApplyPreparationPackage) -> dict:
        return {"applyPackageId": package.applyPackageId, "projectId": package.projectId, "status": package.status, "filesAffected": package.filesAffected[:20], "totalFilesAffected": len(package.filesAffected), "riskLevel": package.riskLevel, "approvalRequired": package.approvalRequired, "canApplyToHost": package.canApplyToHost, "rollbackAvailable": package.rollbackAvailable, "testPassed": package.metadata.get("testPassed", False)}
    def validate_package(self, package: ApplyPreparationPackage) -> dict:
        errors=[]; warnings=[]
        if not package.filesAffected: errors.append("No files affected")
        if package.canApplyToHost: errors.append("canApplyToHost must be false in v1.0")
        if package.riskLevel == "critical" and not package.approvalRequired: warnings.append("Critical package should require approval")
        return {"valid": len(errors)==0, "errors": errors, "warnings": warnings}
    def build_review_payload(self, package: ApplyPreparationPackage) -> dict:
        summary = self.summarize_package(package)
        summary["filesAffected"] = [self.redaction.redact_value("file", f) for f in package.filesAffected[:10]]
        summary["reviewNote"] = "This is an approval-gated preparation package. No changes have been applied to the host project."
        summary["nextStep"] = "Review through Action Gateway; host apply is disabled in v1.0."
        return summary
