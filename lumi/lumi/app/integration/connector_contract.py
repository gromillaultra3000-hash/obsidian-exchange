class ConnectorContract:
    def __init__(self):
        self.rest_contract = {
            "baseUrl": "http://127.0.0.1:8000",
            "protocol": "HTTP REST JSON",
            "errorFormat": "ErrorEnvelope",
            "authentication": "not_required_in_v0_7",
            "requiredEndpoints": [
                {"method": "GET", "path": "/health", "description": "Health check"},
                {"method": "GET", "path": "/version", "description": "Version metadata"},
                {"method": "GET", "path": "/runtime/status", "description": "Runtime status"},
                {"method": "POST", "path": "/integration/handshake", "description": "Host app handshake"},
                {"method": "POST", "path": "/integration/events", "description": "Host event input"},
                {"method": "POST", "path": "/resolve", "description": "Task resolve"},
                {"method": "POST", "path": "/dialog/sessions", "description": "Create dialog session"},
                {"method": "POST", "path": "/dialog/sessions/{id}/message", "description": "Send dialog message"},
                {"method": "POST", "path": "/actions/register", "description": "Register host action"},
                {"method": "POST", "path": "/actions/propose", "description": "Propose action"},
                {"method": "GET", "path": "/actions/approvals", "description": "List approval prompts"},
                {"method": "POST", "path": "/actions/approvals/{id}/decision", "description": "Record approval decision"},
                {"method": "GET", "path": "/history/decisions", "description": "Decision history"},
                {"method": "GET", "path": "/explain/{decisionId}", "description": "Decision explanation"},
            ],
        }
        self.sdk_contract = {
            "python": "sdk/python/lumi_client",
            "javascript": "sdk/javascript",
            "methods": ["health", "version", "runtime_status", "handshake", "resolve", "create_dialog_session", "send_dialog_message", "register_action", "propose_action", "approve", "reject"],
        }
        self.sidecar_contract = {"mode": "local", "host": "127.0.0.1", "port": 8000, "baseUrl": "http://127.0.0.1:8000"}

    def get_rest_contract(self) -> dict:
        return self.rest_contract

    def get_sdk_contract(self) -> dict:
        return self.sdk_contract

    def get_sidecar_contract(self) -> dict:
        return self.sidecar_contract

    def get_connector_summary(self) -> dict:
        return {"modes": ["rest", "sdk", "sidecar"], "rest": self.rest_contract, "sdk": self.sdk_contract, "sidecar": self.sidecar_contract}
