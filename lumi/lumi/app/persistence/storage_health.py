from lumi.app.schemas.persistence import StorageHealth
class StorageHealthService:
    def __init__(self, storage_config): self.storage_config=storage_config
    def check_health(self, adapter, config, profile_id: str):
        h=adapter.health() if adapter else {'status':'not_initialized','readable':False,'writable':False}
        status=h.get('status','not_initialized')
        if status not in ['ready','not_initialized','degraded','failed','disabled']: status='degraded'
        return StorageHealth(status=status,backendType=config.backendType,activeProfileId=profile_id,storagePath=h.get('path') or self.storage_config.resolve_sqlite_path(profile_id,config),readable=bool(h.get('readable')),writable=bool(h.get('writable')),warnings=[] if status=='ready' else ['Storage is not fully ready'],errors=[] if status in ['ready','not_initialized'] else [h.get('error','Storage degraded')])
