import json
from pathlib import Path
from typing import Optional, Any
from fastapi.responses import Response
from lumi.app.providers.redaction import RedactionUtil

class UiHelpers:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()
        self.base_dir = Path(__file__).resolve().parents[1] / "static"

    def read_static_file(self, path: str) -> Optional[str]:
        if ".." in path or path.startswith("/"):
            return None
        file_path = (self.base_dir / path).resolve()
        if not str(file_path).startswith(str(self.base_dir.resolve())):
            return None
        if not file_path.exists() or not file_path.is_file():
            return None
        return file_path.read_text(encoding="utf-8")

    def safe_json_preview(self, data: Any, max_chars: int = 12000) -> str:
        try:
            obj = json.loads(data) if isinstance(data, str) else data
            if isinstance(obj, dict):
                obj = self.redaction.redact_dict(obj)
            text = json.dumps(obj, indent=2, ensure_ascii=False)
        except Exception:
            text = self.redaction.redact_value("uiPreview", str(data))
        return text[:max_chars] + ("\n... [truncated]" if len(text) > max_chars else "")

    def redact_ui_payload(self, data: dict) -> dict:
        return self.redaction.redact_dict(data)

    def build_ui_error(self, message: str, code: str = "UI_ERROR") -> dict:
        return {"error": True, "code": code, "message": self.redaction.redact_value("message", message)}

def asset_response(content: str, media_type: str):
    return Response(content=content, media_type=media_type)
