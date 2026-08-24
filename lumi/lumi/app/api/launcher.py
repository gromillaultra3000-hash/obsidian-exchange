from fastapi import APIRouter
from lumi.app.core.runtime import runtime_instance
router=APIRouter(prefix='/launcher', tags=['launcher'])
@router.get('/status')
async def launcher_status(): return {'status':'ready','dashboardUrl':'http://127.0.0.1:8000/ui'}
@router.get('/diagnostics')
async def launcher_diagnostics(): return runtime_instance.get_launcher_diagnostics()
@router.get('/port-check')
async def port_check(host: str='127.0.0.1', port: int=8000): return runtime_instance.get_launcher_port_check(host, port)
@router.get('/report')
async def launcher_report(): return runtime_instance.get_launcher_report()
