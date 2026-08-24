import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.integration import HostAppManifest, IntegrationHandshakeRequest, HostEvent, DecisionCallbackConfig, DecisionCallbackPayload
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/integration", tags=["integration"])


def _err(code: str, message: str, status_code: int = 400):
    raise HTTPException(status_code=status_code, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, recoverable=False, redacted=True).model_dump())


@router.get("/contract")
async def get_contract():
    return runtime_instance.get_connector_contract_info()


@router.get("/sidecar/status")
async def sidecar_status(host: str = "127.0.0.1", port: int = 8000):
    return runtime_instance.get_sidecar_status(host, port)


@router.get("/sidecar/instructions")
async def sidecar_instructions():
    return runtime_instance.get_sidecar_instructions()


@router.post("/hosts/register")
async def register_host(manifest: HostAppManifest):
    try:
        return runtime_instance.register_host_app(manifest)
    except Exception as exc:
        _err("HOST_REGISTRATION_ERROR", str(exc), 400)


@router.get("/hosts")
async def list_hosts():
    return runtime_instance.list_host_apps()


@router.get("/hosts/{hostAppId}")
async def get_host(hostAppId: str):
    host = runtime_instance.get_host_app(hostAppId)
    if not host:
        _err("HOST_NOT_FOUND", f"Host app {hostAppId} not found", 404)
    return host


@router.post("/hosts/{hostAppId}/enable")
async def enable_host(hostAppId: str):
    host = runtime_instance.enable_host_app(hostAppId)
    if not host:
        _err("HOST_NOT_FOUND", f"Host app {hostAppId} not found", 404)
    return host


@router.post("/hosts/{hostAppId}/disable")
async def disable_host(hostAppId: str):
    host = runtime_instance.disable_host_app(hostAppId)
    if not host:
        _err("HOST_NOT_FOUND", f"Host app {hostAppId} not found", 404)
    return host


@router.post("/handshake")
async def handshake(request: IntegrationHandshakeRequest):
    return runtime_instance.integration_handshake(request)


@router.post("/events")
async def process_event(event: HostEvent):
    return runtime_instance.process_host_event(event)


@router.post("/callbacks/register")
async def register_callback(config: DecisionCallbackConfig):
    try:
        return runtime_instance.register_decision_callback(config)
    except ValueError as exc:
        _err("CALLBACK_EXISTS", str(exc), 409)


@router.get("/callbacks")
async def list_callbacks(hostAppId: str | None = None):
    return runtime_instance.list_decision_callbacks(hostAppId)


@router.post("/callbacks/mock-deliver")
async def mock_deliver_callback(payload: DecisionCallbackPayload):
    return runtime_instance.deliver_decision_callback(payload, mode="mock")
