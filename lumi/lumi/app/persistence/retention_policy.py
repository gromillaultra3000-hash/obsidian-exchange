from lumi.app.schemas.persistence import RetentionPolicy
class RetentionPolicyService:
    def __init__(self, audit_log=None): self.audit_log=audit_log; self._policy=RetentionPolicy()
    def get_default_policy(self): return self._policy
    def apply_retention(self, runtime, profile_id=None, dry_run=True):
        actions=[]
        audit_count=len(runtime.audit_log.list_entries())
        if audit_count > self._policy.maxAuditEntries: actions.append({'collection':'audit_entries','current':audit_count,'limit':self._policy.maxAuditEntries,'wouldDelete':audit_count-self._policy.maxAuditEntries})
        decision_count=len(runtime.decision_history.list_decisions())
        if decision_count > self._policy.maxDecisions: actions.append({'collection':'decisions','current':decision_count,'limit':self._policy.maxDecisions,'wouldDelete':decision_count-self._policy.maxDecisions})
        if self.audit_log: self.audit_log.add_entry('retention_policy_dry_run_completed', summary=f'Retention dry run: {len(actions)} actions')
        return {'dryRun': dry_run, 'actions': actions, 'policy': self._policy.model_dump()}
