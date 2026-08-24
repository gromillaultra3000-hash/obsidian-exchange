import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional
from .errors import LumiClientError


class LumiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"message": raw}
            detail = payload.get("detail", payload)
            msg = detail.get("message") if isinstance(detail, dict) else str(detail)
            raise LumiClientError(msg or f"HTTP {exc.code}", exc.code, payload)
        except urllib.error.URLError as exc:
            raise LumiClientError(f"Connection error: {exc}")

    def health(self): return self._request("GET", "/health")
    def version(self): return self._request("GET", "/version")
    def runtime_status(self): return self._request("GET", "/runtime/status")
    def get_integration_contract(self): return self._request("GET", "/integration/contract")
    def get_sidecar_status(self): return self._request("GET", "/integration/sidecar/status")

    def handshake(self, manifest: dict):
        return self._request("POST", "/integration/handshake", {"hostAppId": manifest.get("hostAppId"), "manifest": manifest, "connectorMode": (manifest.get("allowedModes") or ["rest"])[0], "clientVersion": "0.7.0"})

    def register_provider(self, provider_profile: dict): return self._request("POST", "/providers", provider_profile)
    def register_action(self, action_definition: dict): return self._request("POST", "/actions/register", action_definition)

    def resolve(self, input_text: str, context: Optional[dict] = None, requirements: Optional[dict] = None, metadata: Optional[dict] = None):
        return self._request("POST", "/resolve", {"input": input_text, "context": context or {}, "requirements": requirements or {}, "metadata": metadata or {}})

    def create_dialog_session(self, title: Optional[str] = None, host_app_id: Optional[str] = None, user_id: Optional[str] = None, metadata: Optional[dict] = None):
        return self._request("POST", "/dialog/sessions", {"title": title, "hostAppId": host_app_id, "userId": user_id, "metadata": metadata or {}})

    def send_dialog_message(self, session_id: str, text: str, metadata: Optional[dict] = None):
        return self._request("POST", f"/dialog/sessions/{urllib.parse.quote(session_id)}/message", {"text": text, "metadata": metadata or {}})

    def list_decisions(self): return self._request("GET", "/history/decisions")
    def explain_decision(self, decision_id: str, mode: str = "human"): return self._request("GET", f"/explain/{urllib.parse.quote(decision_id)}?mode={urllib.parse.quote(mode)}")

    def propose_action(self, action_id: str, proposed_input: Optional[dict] = None, requested_mode: str = "proposal"):
        return self._request("POST", "/actions/propose", {"actionId": action_id, "proposedInput": proposed_input or {}, "requestedMode": requested_mode})

    def list_approvals(self): return self._request("GET", "/actions/approvals")
    def approve(self, prompt_id: str, user_id: Optional[str] = None, reason: Optional[str] = None): return self._approval(prompt_id, "approve", user_id, reason)
    def reject(self, prompt_id: str, user_id: Optional[str] = None, reason: Optional[str] = None): return self._approval(prompt_id, "reject", user_id, reason)
    def _approval(self, prompt_id: str, decision: str, user_id: Optional[str], reason: Optional[str]):
        return self._request("POST", f"/actions/approvals/{urllib.parse.quote(prompt_id)}/decision", {"promptId": prompt_id, "decision": decision, "userId": user_id, "reason": reason})

    def send_host_event(self, event: dict): return self._request("POST", "/integration/events", event)
