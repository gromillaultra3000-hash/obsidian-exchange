import uuid, json, os
from datetime import datetime, timezone
from lumi.app.schemas.launcher import LaunchReport
class LaunchReportService:
    def build_report(self, diagnostics): return LaunchReport(reportId=str(uuid.uuid4()), createdAt=datetime.now(timezone.utc).isoformat(), status=diagnostics.status, dashboardUrl='http://127.0.0.1:8000/ui', backendHost='127.0.0.1', backendPort=8000, logPath='logs/runtime.log', diagnostics=diagnostics)
    def write_report(self, report, path='logs/last_launch_report.json'):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path,'w',encoding='utf-8') as f: json.dump(report.model_dump() if hasattr(report,'model_dump') else report.dict(), f, ensure_ascii=False, indent=2)
