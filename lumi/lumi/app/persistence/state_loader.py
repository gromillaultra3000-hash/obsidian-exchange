import uuid
from datetime import datetime, timezone
from lumi.app.schemas.persistence import PersistenceLoadResult
from lumi.app.providers.redaction import RedactionUtil

class RuntimeStateLoader:
    def __init__(self, redaction: RedactionUtil | None = None, audit_log=None): self.redaction=redaction or RedactionUtil(); self.audit_log=audit_log
    def _secret_like(self, record):
        s=str(record).lower()
        return any(x in s for x in ['sk-test-secret','api_key=','token=','password='])
    def load_runtime(self, runtime, state: dict, collections=None, safe_mode=True) -> PersistenceLoadResult:
        loaded=[]; counts={}; warnings=[]; errors=[]
        for col in (collections or list(state.keys())):
            recs=state.get(col,[])
            try:
                cnt=self._apply_collection(runtime,col,recs,safe_mode)
                if cnt or col in state:
                    loaded.append(col); counts[col]=cnt
            except Exception as e:
                if safe_mode: warnings.append(f"Skipped {col}: {e}")
                else: errors.append(f"Failed {col}: {e}")
        return PersistenceLoadResult(loadId=str(uuid.uuid4()),profileId="default",status="loaded" if not errors else "partial",loadedAt=datetime.now(timezone.utc).isoformat(),collectionsLoaded=loaded,recordsLoaded=counts,warnings=warnings,errors=errors)
    def _apply_collection(self, runtime, col, records, safe_mode):
        cnt=0
        for r in records:
            if self._secret_like(r):
                if safe_mode: continue
                raise ValueError('raw secret-like content detected')
            try:
                if col=='providers':
                    from lumi.app.schemas.provider import ProviderProfile
                    obj=ProviderProfile(**r)
                    if not any(p.providerId==obj.providerId for p in runtime.registry.list_providers()): runtime.registry.add_provider(obj); cnt+=1
                elif col=='actions':
                    from lumi.app.schemas.actions import ActionDefinition
                    obj=ActionDefinition(**r)
                    if not runtime.action_registry.get_action(obj.actionId): runtime.action_registry.register_action(obj); cnt+=1
                elif col=='projects':
                    from lumi.app.schemas.project_scanner import ProjectManifest, HostProjectProfile
                    if 'manifest' in r: obj=HostProjectProfile(**r); runtime.host_project_registry._projects[obj.projectId]=obj
                    else: obj=ProjectManifest(**r); runtime.host_project_registry.register_project(obj)
                    cnt+=1
                elif col=='file_snapshots':
                    from lumi.app.schemas.project_scanner import FileSnapshot
                    runtime.file_snapshot_store.add_snapshot(FileSnapshot(**r)); cnt+=1
                elif col=='host_apps':
                    from lumi.app.schemas.integration import HostAppManifest, HostAppProfile
                    if 'manifest' in r: obj=HostAppProfile(**r); runtime.host_app_registry._hosts[obj.hostAppId]=obj
                    else: obj=HostAppManifest(**r); runtime.host_app_registry.register_host(obj)
                    cnt+=1
                elif col=='decisions':
                    from lumi.app.schemas.history import DecisionHistoryRecord
                    obj=DecisionHistoryRecord(**r); runtime.decision_history._records[obj.decisionId]=obj; cnt+=1
                elif col=='dialog_sessions':
                    from lumi.app.schemas.dialog import DialogSession
                    obj=DialogSession(**r); runtime.dialog_sessions._sessions[obj.sessionId]=obj; cnt+=1
                elif col=='dialog_messages':
                    from lumi.app.schemas.dialog import DialogMessage
                    obj=DialogMessage(**r); runtime.dialog_messages._messages[obj.messageId]=obj; runtime.dialog_messages._by_session.setdefault(obj.sessionId,[]).append(obj.messageId); cnt+=1
                elif col=='approvals':
                    from lumi.app.schemas.actions import ApprovalPrompt
                    obj=ApprovalPrompt(**r); runtime.approval_manager._prompts[obj.promptId]=obj; cnt+=1
            except Exception:
                if not safe_mode: raise
                continue
        return cnt
