import uuid
from lumi.app.providers.redaction import RedactionUtil

def _dump(obj):
    if hasattr(obj, 'model_dump'): return obj.model_dump()
    if hasattr(obj, 'dict'): return obj.dict()
    if isinstance(obj, dict): return dict(obj)
    return {}

class RuntimeStateSerializer:
    def __init__(self, redaction: RedactionUtil | None = None): self.redaction=redaction or RedactionUtil()
    def _serialize_list(self, items): return [self.redaction.redact_dict(_dump(i)) for i in (items or [])]
    def serialize_runtime(self, runtime, include_audit=True, include_snapshots=True) -> dict:
        state={}
        state['providers']=self._serialize_list(runtime.registry.list_providers())
        state['actions']=self._serialize_list(runtime.action_registry.list_actions())
        state['policy_rules']=self._serialize_list(runtime.policy_registry.list_rules())
        state['policy_limits']=self._serialize_list(runtime.policy_registry.list_limits())
        state['host_apps']=self._serialize_list(runtime.host_app_registry.list_hosts())
        state['projects']=self._serialize_list(runtime.host_project_registry.list_projects())
        if include_snapshots: state['file_snapshots']=self._serialize_list(runtime.file_snapshot_store.list_all_snapshots())
        state['decisions']=self._serialize_list(runtime.decision_history.list_decisions())
        state['dialog_sessions']=self._serialize_list(runtime.dialog_sessions.list_sessions())
        state['dialog_messages']=self._serialize_list(runtime.dialog_messages.list_all())
        state['approvals']=self._serialize_list(runtime.approval_manager.list_all())
        if hasattr(runtime,'patch_runtime'):
            state['patch_plans']=self._serialize_list(runtime.patch_runtime.list_patch_plans())
            state['diff_previews']=self._serialize_list(runtime.patch_runtime._diff_previews.values())
            state['test_plans']=self._serialize_list(runtime.patch_runtime._test_plans.values())
            state['rollback_metadata']=self._serialize_list(runtime.patch_runtime._rollback_metadata.values())
        if hasattr(runtime,'sandbox_store'): state['sandbox_workspaces']=self._serialize_list(runtime.sandbox_store.list_workspaces())
        if hasattr(runtime,'sandbox_result_store'):
            state['sandbox_test_results']=self._serialize_list(runtime.sandbox_result_store.list_test_results())
            state['apply_packages']=self._serialize_list(runtime.sandbox_result_store.list_apply_packages())
        if hasattr(runtime,'provider_reliability_scorer'): state['provider_reliability_scores']=self._serialize_list(runtime.provider_reliability_scorer.compute_all())
        if hasattr(runtime,'provider_quality_scorer'): state['provider_quality_scores']=self._serialize_list(runtime.provider_quality_scorer.list_quality_scores())
        if hasattr(runtime,'provider_budget_limit_service'): state['provider_budget_limits']=self._serialize_list(runtime.provider_budget_limit_service.list_limits())
        if hasattr(runtime,'provider_fallback_chain_service'): state['provider_fallback_chains']=self._serialize_list(runtime.provider_fallback_chain_service.list_chains())
        if hasattr(runtime,'provider_latency_tracker'): state['provider_latency_records']=self.redaction.redact_value('provider_latency_records', runtime.provider_latency_tracker.get_latency_records())
        if hasattr(runtime,'provider_error_tracker'): state['provider_error_records']=self.redaction.redact_value('provider_error_records', runtime.provider_error_tracker.list_errors())

        if hasattr(runtime,'real_apply_config_service'): state['real_apply_config']=[self.redaction.redact_dict(_dump(runtime.real_apply_config_service.get_config()))]
        if hasattr(runtime,'safe_workspace_registry'): state['safe_workspaces']=self._serialize_list(runtime.safe_workspace_registry.list_workspaces())
        if hasattr(runtime,'apply_executor'): state['apply_results']=self._serialize_list(runtime.apply_executor.list_results())
        if hasattr(runtime,'backup_service'): state['backup_records_metadata']=self._serialize_list(runtime.backup_service.list_backups())
        if hasattr(runtime,'rollback_service'): state['rollback_packages_metadata']=self._serialize_list(runtime.rollback_service.list_rollback_packages())
        if include_audit: state['audit_entries']=self._serialize_list(runtime.audit_log.list_entries())
        return state
    def get_record_id(self, collection: str, payload: dict) -> str:
        ids={"providers":"providerId","actions":"actionId","policy_rules":"ruleId","policy_limits":"limitId","host_apps":"hostAppId","projects":"projectId","file_snapshots":"snapshotId","decisions":"decisionId","dialog_sessions":"sessionId","dialog_messages":"messageId","approvals":"promptId","patch_plans":"resultId","diff_previews":"diffPreviewId","test_plans":"testPlanId","rollback_metadata":"rollbackMetadataId","sandbox_workspaces":"workspaceId","sandbox_test_results":"testRunResultId","apply_packages":"applyPackageId","audit_entries":"auditId","real_apply_config":"mode","safe_workspaces":"workspaceId","apply_results":"applyId","backup_records_metadata":"backupId","rollback_packages_metadata":"rollbackPackageId"}
        return str(payload.get(ids.get(collection,'id')) or uuid.uuid4())
