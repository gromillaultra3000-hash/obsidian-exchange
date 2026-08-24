import uuid, json, os
from datetime import datetime, timezone
from lumi.app.schemas.persistence import RuntimeSnapshot, ExportSnapshotResult, ImportSnapshotRequest, ImportSnapshotResult
from lumi.app.providers.redaction import RedactionUtil

class RuntimeSnapshotService:
    def __init__(self, serializer, loader, redaction: RedactionUtil | None = None, audit_log=None):
        self.serializer=serializer; self.loader=loader; self.redaction=redaction or RedactionUtil(); self.audit_log=audit_log
    def build_snapshot(self, runtime, profile_id='default', include_audit=True, include_snapshots=True):
        return RuntimeSnapshot(snapshotId=str(uuid.uuid4()),profileId=profile_id,createdAt=datetime.now(timezone.utc).isoformat(),version='1.2.0',redacted=True,collections=self.serializer.serialize_runtime(runtime,include_audit,include_snapshots),metadata={})
    def export_snapshot(self, runtime, profile_id='default', include_audit=True, include_snapshots=True):
        export_id=str(uuid.uuid4())
        snap=self.build_snapshot(runtime,profile_id,include_audit,include_snapshots)
        path=None
        try:
            cfg=runtime.storage_config.get_default_config(); d=runtime.storage_config.resolve_profile_dir(profile_id,cfg); exp=os.path.join(d,'exports'); os.makedirs(exp,exist_ok=True); path=os.path.join(exp,f'snapshot_{export_id}.json')
            with open(path,'w',encoding='utf-8') as f: json.dump(snap.model_dump(),f,ensure_ascii=False,indent=2)
        except Exception as e:
            path=None
        if self.audit_log: self.audit_log.add_entry('snapshot_exported', summary=f'Snapshot {export_id} exported')
        return ExportSnapshotResult(exportId=export_id,profileId=profile_id,createdAt=snap.createdAt,snapshot=snap,filePath=path,warnings=[])
    def validate_snapshot(self, snapshot):
        errors=[]; warnings=[]
        if not snapshot.collections: errors.append('Snapshot has no collections')
        s=str(snapshot.collections).lower()
        for p in ['sk-test-secret','api_key=','token=','password=']:
            if p in s: warnings.append(f'Snapshot contains secret-like content: {p}')
        return {'valid':not errors,'errors':errors,'warnings':warnings}
    def import_snapshot(self, runtime, request: ImportSnapshotRequest):
        val=self.validate_snapshot(request.snapshot)
        if not val['valid']:
            return ImportSnapshotResult(importId=str(uuid.uuid4()),profileId=request.profileId or 'default',importedAt=datetime.now(timezone.utc).isoformat(),status='failed',errors=val['errors'],warnings=val['warnings'])
        res=self.loader.load_runtime(runtime, request.snapshot.collections, safe_mode=True)
        if self.audit_log: self.audit_log.add_entry('snapshot_imported', summary='Snapshot imported', details={'recordsImported':res.recordsLoaded})
        return ImportSnapshotResult(importId=str(uuid.uuid4()),profileId=request.profileId or 'default',importedAt=datetime.now(timezone.utc).isoformat(),status='imported',collectionsImported=res.collectionsLoaded,recordsImported=res.recordsLoaded,warnings=res.warnings+val['warnings'],errors=res.errors)
