from lumi.app.schemas.launcher import LauncherDiagnostics
class LauncherDiagnosticsService:
    def __init__(self, config_service, port_checker, startup_checker): self.config_service=config_service; self.port_checker=port_checker; self.startup_checker=startup_checker
    def run_diagnostics(self):
        cfg=self.config_service.get_default_config(); checks=self.startup_checker.check_all(); port=self.port_checker.check_port(cfg['host'], cfg['port'])
        warnings=[c.message for c in checks if c.status=='warning'] + ([] if port.available else [port.message])
        errors=[c.message for c in checks if c.status=='failed' and c.required]
        status='failed' if errors else 'warning' if warnings else 'ready'
        return LauncherDiagnostics(status=status, pythonAvailable=any(c.title=='Python Version' and c.status in ('ready','warning') for c in checks), fastapiAvailable=any(c.title=='FastAPI Available' and c.status=='ready' for c in checks), portCheck=port, dataDirReady=any(c.title=='Data Directory' and c.status=='ready' for c in checks), logsDirReady=any(c.title=='Logs Directory' and c.status=='ready' for c in checks), uiAssetsReady=any(c.title=='UI Assets' and c.status=='ready' for c in checks), startupChecks=checks, warnings=warnings, errors=errors)
