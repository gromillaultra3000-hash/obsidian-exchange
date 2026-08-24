import uuid
from lumi.app.schemas.integration import IntegrationHandshakeRequest, IntegrationHandshakeResult
from lumi.app.version.metadata import VERSION, CAPABILITIES


class IntegrationHandshakeService:
    def __init__(self, host_registry, manifest_validator, audit_log=None, redaction=None):
        self.host_registry = host_registry
        self.manifest_validator = manifest_validator
        self.audit_log = audit_log
        self.redaction = redaction

    def handshake(self, request: IntegrationHandshakeRequest) -> IntegrationHandshakeResult:
        handshake_id = str(uuid.uuid4())
        if self.audit_log:
            self.audit_log.add_entry("integration_handshake_started", summary=f"Handshake started for {request.hostAppId}", details={"connectorMode": request.connectorMode})
        validation = self.manifest_validator.validate_manifest(request.manifest)
        if not validation["valid"]:
            if self.audit_log:
                self.audit_log.add_entry("integration_handshake_rejected", summary=f"Handshake rejected for {request.hostAppId}", details={"errors": validation["errors"], "warnings": validation["warnings"]})
            return IntegrationHandshakeResult(
                handshakeId=handshake_id,
                hostAppId=request.hostAppId,
                accepted=False,
                status="rejected",
                connectorMode=request.connectorMode,
                runtimeVersion=VERSION,
                supportedCapabilities=CAPABILITIES,
                requiredNextStep="fix_manifest_errors",
                warnings=validation["warnings"] + validation["errors"],
                metadata={"validationErrors": validation["errors"]},
            )
        profile = self.host_registry.register_host(request.manifest)
        if self.audit_log:
            self.audit_log.add_entry("integration_handshake_completed", summary=f"Handshake completed for {request.hostAppId}")
        return IntegrationHandshakeResult(
            handshakeId=handshake_id,
            hostAppId=request.hostAppId,
            accepted=True,
            status=profile.status,
            connectorMode=request.connectorMode,
            runtimeVersion=VERSION,
            supportedCapabilities=CAPABILITIES,
            warnings=validation["warnings"],
            metadata={"hostStatus": profile.status, "clientVersion": request.clientVersion},
        )
