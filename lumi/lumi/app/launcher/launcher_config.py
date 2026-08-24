class LauncherConfigService:
    def __init__(self):
        self.host='127.0.0.1'; self.port=8000; self.dashboard_path='/ui'; self.logs_dir='logs'; self.data_dir='data'; self.safe_mode=False; self.language='ru'
    def get_default_config(self): return {'host':self.host,'port':self.port,'dashboardPath':self.dashboard_path,'logsDir':self.logs_dir,'dataDir':self.data_dir,'safeMode':self.safe_mode,'language':self.language}
    def dashboard_url(self): return f'http://{self.host}:{self.port}{self.dashboard_path}'
    def logs_path(self): return self.logs_dir
    def data_path(self): return self.data_dir
