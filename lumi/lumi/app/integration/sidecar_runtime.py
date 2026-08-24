from lumi.app.schemas.integration import SidecarStatus


class SidecarRuntimeInfo:
    def get_sidecar_status(self, runtime_status, host: str = "127.0.0.1", port: int = 8000) -> SidecarStatus:
        data = runtime_status.model_dump() if hasattr(runtime_status, "model_dump") else runtime_status.dict() if hasattr(runtime_status, "dict") else {}
        return SidecarStatus(mode="local", host=host, port=port, baseUrl=f"http://{host}:{port}", running=bool(data.get("initialized", True)), runtimeStatus=data, warnings=[])

    def get_launch_instructions(self) -> dict:
        return {
            "command": "python run_lumi.py",
            "baseUrl": "http://127.0.0.1:8000",
            "steps": ["Start Lumi", "Call /health", "Call /integration/handshake", "Use /resolve or /dialog endpoints"],
        }

    def get_embed_instructions(self) -> dict:
        return {
            "rest": "Call Lumi at http://127.0.0.1:8000",
            "pythonSdk": "from lumi_client import LumiClient; client = LumiClient()",
            "javascriptSdk": "const { LumiClient } = require('./sdk/javascript/src/client');",
            "note": "No host action is executed directly; use Action Gateway and Approval Prompts.",
        }
