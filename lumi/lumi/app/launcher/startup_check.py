import os, sys, uuid
from lumi.app.schemas.launcher import StartupCheckResult
class StartupChecker:
    def check_all(self):
        checks=[]; py_ok=sys.version_info>=(3,10)
        checks.append(StartupCheckResult(checkId=str(uuid.uuid4()), title='Python Version', status='ready' if py_ok else 'warning', message=f'Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}', required=True))
        try:
            import fastapi; checks.append(StartupCheckResult(checkId=str(uuid.uuid4()), title='FastAPI Available', status='ready', message=f'FastAPI {getattr(fastapi,"__version__","")}', required=True))
        except Exception: checks.append(StartupCheckResult(checkId=str(uuid.uuid4()), title='FastAPI Available', status='failed', message='FastAPI not found', required=True))
        try:
            import uvicorn; checks.append(StartupCheckResult(checkId=str(uuid.uuid4()), title='Uvicorn Available', status='ready', message='Uvicorn available', required=True))
        except Exception: checks.append(StartupCheckResult(checkId=str(uuid.uuid4()), title='Uvicorn Available', status='failed', message='Uvicorn not found', required=True))
        for d,title in [('data','Data Directory'),('logs','Logs Directory')]:
            os.makedirs(d, exist_ok=True); ok=os.path.isdir(d) and os.access(d, os.W_OK); checks.append(StartupCheckResult(checkId=str(uuid.uuid4()), title=title, status='ready' if ok else 'warning', message=f'{d} writable' if ok else f'{d} missing/not writable', required=False))
        ui=os.path.exists(os.path.join('lumi','app','static','index.html'))
        checks.append(StartupCheckResult(checkId=str(uuid.uuid4()), title='UI Assets', status='ready' if ui else 'warning', message='UI assets found' if ui else 'UI assets missing', required=False))
        return checks
