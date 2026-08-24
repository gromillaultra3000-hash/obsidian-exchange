import uuid
from typing import List, Optional
from lumi.app.core.config import RuntimeConfig
from lumi.app.core.status import RuntimeStatus
from lumi.app.providers.registry import ProviderRegistry
from lumi.app.providers.adapter_base import ProviderAdapterBase
from lumi.app.providers.mock_adapter import MockProviderAdapter
from lumi.app.providers.redaction import RedactionUtil
from lumi.app.resolver.validated_routing_resolver import ValidatedRoutingResolver
from lumi.app.audit.audit_log import AuditLog
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.schemas.decision import StructuredDecision
from lumi.app.schemas.audit import AuditEntry
from lumi.app.version.metadata import VERSION
from lumi.app.routing.task_classifier import TaskClassifier
from lumi.app.routing.task_requirements import TaskRequirementsBuilder
from lumi.app.routing.provider_router import ProviderRouter
from lumi.app.validation.validation_pipeline import ValidationPipeline
from lumi.app.policy.policy_registry import PolicyRegistry
from lumi.app.policy.limits import LimitsChecker
from lumi.app.policy.policy_engine import PolicyEngine
from lumi.app.actions.action_registry import ActionRegistry
from lumi.app.actions.action_proposal import ActionProposalBuilder
from lumi.app.actions.approval_prompt import ApprovalPromptManager
from lumi.app.actions.action_gateway import ActionGateway
from lumi.app.schemas.policy import PolicyRule, LimitDefinition, PolicyCheckRequest
from lumi.app.schemas.actions import ActionDefinition
from lumi.app.history.decision_history import DecisionHistoryStore
from lumi.app.history.timeline_builder import TimelineBuilder
from lumi.app.explainability.explanation_builder import ExplanationBuilder
from lumi.app.dialog.dialog_session import DialogSessionStore
from lumi.app.dialog.dialog_message import DialogMessageStore
from lumi.app.dialog.dialog_runtime import DialogRuntime

from lumi.app.integration.host_app_registry import HostAppRegistry
from lumi.app.integration.host_manifest import HostManifestValidator
from lumi.app.integration.integration_handshake import IntegrationHandshakeService
from lumi.app.integration.connector_contract import ConnectorContract
from lumi.app.integration.event_contract import HostEventProcessor
from lumi.app.integration.callback_contract import DecisionCallbackService
from lumi.app.integration.sidecar_runtime import SidecarRuntimeInfo
from lumi.app.schemas.integration import HostAppManifest, IntegrationHandshakeRequest, HostEvent, DecisionCallbackConfig, DecisionCallbackPayload

from lumi.app.schemas.project_scanner import ProjectManifest, FileSnapshot, ProjectScanRequest
from lumi.app.project_scanner.project_registry import HostProjectRegistry
from lumi.app.project_scanner.project_manifest import ProjectManifestValidator
from lumi.app.project_scanner.file_snapshot_store import FileSnapshotStore
from lumi.app.project_scanner.inventory_builder import ProjectInventoryBuilder
from lumi.app.project_scanner.static_inspector import StaticInspector
from lumi.app.project_scanner.issue_detector import IssueDetector
from lumi.app.project_scanner.improvement_candidate import ImprovementCandidateBuilder
from lumi.app.project_scanner.improvement_planner import ImprovementPlanner
from lumi.app.project_scanner.patch_plan_preview import PatchPlanPreviewBuilder
from lumi.app.project_scanner.scan_runtime import ProjectScanRuntime
from lumi.app.schemas.patch_planner import PatchRequest
from lumi.app.patch_planner.patch_request import PatchRequestNormalizer
from lumi.app.patch_planner.patch_safety import PatchSafetyGuard
from lumi.app.patch_planner.patch_proposal import PatchProposalBuilder
from lumi.app.patch_planner.diff_preview import DiffPreviewBuilder
from lumi.app.patch_planner.test_plan import TestPlanBuilder
from lumi.app.patch_planner.test_runner_preview import TestRunnerPreview
from lumi.app.patch_planner.rollback_metadata import RollbackMetadataBuilder
from lumi.app.patch_planner.patch_runtime import PatchRuntime

from lumi.app.schemas.sandbox import SandboxWorkspaceRequest, SandboxTestRunRequest, ApplyPreparationRequest
from lumi.app.sandbox.sandbox_workspace import SandboxWorkspaceBuilder
from lumi.app.sandbox.sandbox_store import SandboxStore
from lumi.app.sandbox.sandbox_patch_applier import SandboxPatchApplierPreview
from lumi.app.sandbox.command_guard import CommandExecutionGuard
from lumi.app.sandbox.sandbox_test_runner import SandboxTestRunner
from lumi.app.sandbox.sandbox_result_store import SandboxResultStore
from lumi.app.sandbox.apply_preparation import ApplyPreparationBuilder
from lumi.app.sandbox.apply_package import ApplyPackageService
from lumi.app.sandbox.sandbox_runtime import SandboxRuntime
from lumi.app.ui.ui_state import UiStateService

from lumi.app.schemas.persistence import PersistenceSaveRequest, PersistenceLoadRequest, ExportSnapshotRequest, ImportSnapshotRequest
from lumi.app.persistence.storage_config import StorageConfigService
from lumi.app.persistence.profile_manager import ProfileManager
from lumi.app.persistence.state_serializer import RuntimeStateSerializer
from lumi.app.persistence.state_loader import RuntimeStateLoader
from lumi.app.persistence.sqlite_adapter import SQLiteStorageAdapter
from lumi.app.persistence.json_snapshot import RuntimeSnapshotService
from lumi.app.persistence.storage_health import StorageHealthService
from lumi.app.persistence.retention_policy import RetentionPolicyService
from lumi.app.security.security_config import SecurityConfigService
from lumi.app.security.password_hasher import PasswordHasher
from lumi.app.security.token_manager import TokenManager
from lumi.app.security.encryption_service import EncryptionService
from lumi.app.security.vault_storage import VaultStorage
from lumi.app.security.secret_vault import SecretVault
from lumi.app.security.auth_guard import AuthGuard
from lumi.app.security.security_runtime import SecurityRuntime
from lumi.app.schemas.security import SetupPasswordRequest, UnlockRequest, SecretCreateRequest, SecretUpdateRequest, SecretResolveRequest

from lumi.app.localization.localization_config import LocalizationConfigService
from lumi.app.localization.language_registry import LanguageRegistry
from lumi.app.localization.translation_service import TranslationService
from lumi.app.localization.ui_localizer import UiLocalizer
from lumi.app.localization.dialog_localizer import DialogLocalizer
from lumi.app.launcher.launcher_config import LauncherConfigService
from lumi.app.launcher.port_check import PortChecker
from lumi.app.launcher.startup_check import StartupChecker
from lumi.app.launcher.launcher_diagnostics import LauncherDiagnosticsService
from lumi.app.launcher.launch_report import LaunchReportService
from lumi.app.provider_runtime.provider_presets import ProviderPresetRegistry
from lumi.app.provider_runtime.provider_config import ProviderRuntimeConfigService
from lumi.app.provider_runtime.provider_usage_tracker import ProviderUsageTracker
from lumi.app.provider_runtime.provider_diagnostics import ProviderDiagnosticsService
from lumi.app.provider_runtime.provider_runtime import ProviderRuntime
from lumi.app.schemas.localization import SetLanguageRequest, TranslationLookupRequest
from lumi.app.schemas.provider_runtime import ProviderRuntimeConfig, ProviderConnectionTestRequest, ProviderLiveCallRequest, ModelDiscoveryRequest, CreateProviderSecretRequest

from lumi.app.provider_intelligence.reliability_score import ProviderReliabilityScorer
from lumi.app.provider_intelligence.quality_score import ProviderQualityScorer
from lumi.app.provider_intelligence.latency_tracker import ProviderLatencyTracker
from lumi.app.provider_intelligence.error_tracker import ProviderErrorTracker
from lumi.app.provider_intelligence.budget_limits import ProviderBudgetLimitService
from lumi.app.provider_intelligence.fallback_chain import ProviderFallbackChainService
from lumi.app.provider_intelligence.selection_policy import ProviderSelectionPolicy
from lumi.app.provider_intelligence.output_comparison import ProviderOutputComparator
from lumi.app.provider_intelligence.provider_consensus import ProviderConsensusBuilder
from lumi.app.provider_intelligence.multi_provider_review import MultiProviderReviewRuntime
from lumi.app.provider_intelligence.provider_performance_report import ProviderPerformanceReportBuilder
from lumi.app.provider_intelligence.provider_intelligence_runtime import ProviderIntelligenceRuntime
from lumi.app.schemas.provider_intelligence import ProviderBudgetLimits, ProviderFallbackChain, ProviderSelectionRequest, MultiProviderReviewRequest

from lumi.app.real_apply.apply_config import RealApplyConfigService
from lumi.app.real_apply.workspace_registry import SafeWorkspaceRegistry
from lumi.app.real_apply.path_guard import PathGuard
from lumi.app.real_apply.file_classifier import FileClassifier
from lumi.app.real_apply.diff_validator import DiffValidator
from lumi.app.real_apply.apply_gate import ApplyGate
from lumi.app.real_apply.backup_service import BackupService
from lumi.app.real_apply.apply_executor import ApplyExecutor
from lumi.app.real_apply.rollback_service import RollbackService
from lumi.app.real_apply.apply_audit import ApplyAuditBuilder
from lumi.app.real_apply.apply_runtime import RealApplyRuntime
from lumi.app.schemas.real_apply import RegisterWorkspaceRequest, ApplyGateRequest, ApplyExecutionRequest, RollbackRequest



class LumiRuntime:
    def __init__(self, config: Optional[RuntimeConfig] = None):
        self.config = config or RuntimeConfig()
        self.redaction = RedactionUtil(self.config.secret_mask)
        self.registry = ProviderRegistry()
        self.audit_log = AuditLog(self.redaction)
        self.task_classifier = TaskClassifier()
        self.task_requirements_builder = TaskRequirementsBuilder()
        self.provider_router = ProviderRouter(self.registry, self.audit_log)
        self.validation_pipeline = ValidationPipeline(self.audit_log, self.redaction)
        self.policy_registry = PolicyRegistry(self.audit_log)
        self.limits_checker = LimitsChecker()
        self.policy_engine = PolicyEngine(self.policy_registry, self.limits_checker, self.audit_log, self.redaction)
        self.action_registry = ActionRegistry(self.audit_log, self.redaction)
        self.action_proposal_builder = ActionProposalBuilder(self.action_registry, self.redaction)
        self.approval_manager = ApprovalPromptManager(self.audit_log, self.redaction)
        self.action_gateway = ActionGateway(self.action_registry, self.policy_engine, self.action_proposal_builder, self.approval_manager, self.audit_log, self.redaction)
        self.decision_history = DecisionHistoryStore(self.audit_log, self.redaction)
        self.timeline_builder = TimelineBuilder(self.audit_log, self.decision_history)
        self.explanation_builder = ExplanationBuilder(self.decision_history, self.timeline_builder, self.audit_log, self.redaction)
        self.dialog_sessions = DialogSessionStore(self.audit_log, self.redaction)
        self.dialog_messages = DialogMessageStore(self.audit_log, self.redaction)
        self.dialog_runtime = DialogRuntime(self, self.dialog_sessions, self.dialog_messages, self.decision_history, self.explanation_builder, self.audit_log)
        self.host_app_registry = HostAppRegistry(self.audit_log, self.redaction)
        self.manifest_validator = HostManifestValidator(self.redaction)
        self.handshake_service = IntegrationHandshakeService(self.host_app_registry, self.manifest_validator, self.audit_log, self.redaction)
        self.connector_contract = ConnectorContract()
        self.host_event_processor = HostEventProcessor(self, self.host_app_registry, self.audit_log, self.redaction)
        self.callback_service = DecisionCallbackService(self.audit_log, self.redaction)
        self.sidecar_runtime_info = SidecarRuntimeInfo()
        self.host_project_registry = HostProjectRegistry(self.audit_log, self.redaction)
        self.project_manifest_validator = ProjectManifestValidator(self.redaction)
        self.file_snapshot_store = FileSnapshotStore(self.audit_log, self.redaction)
        self.project_inventory_builder = ProjectInventoryBuilder()
        self.static_inspector = StaticInspector()
        self.issue_detector = IssueDetector()
        self.improvement_candidate_builder = ImprovementCandidateBuilder()
        self.improvement_planner = ImprovementPlanner(self.action_gateway)
        self.patch_preview_builder = PatchPlanPreviewBuilder()
        self.project_scan_runtime = ProjectScanRuntime(
            self,
            self.host_project_registry,
            self.file_snapshot_store,
            self.project_inventory_builder,
            self.static_inspector,
            self.issue_detector,
            self.improvement_candidate_builder,
            self.improvement_planner,
            self.patch_preview_builder,
            self.audit_log,
            self.redaction,
        )
        self.patch_request_normalizer = PatchRequestNormalizer(self.redaction)
        self.patch_safety_guard = PatchSafetyGuard(self.redaction)
        self.patch_proposal_builder = PatchProposalBuilder(self.action_gateway, self.redaction)
        self.diff_preview_builder = DiffPreviewBuilder(self.file_snapshot_store, self.redaction)
        self.test_plan_builder = TestPlanBuilder()
        self.test_runner_preview = TestRunnerPreview()
        self.rollback_metadata_builder = RollbackMetadataBuilder(self.file_snapshot_store)
        self.patch_runtime = PatchRuntime(
            self,
            self.host_project_registry,
            self.file_snapshot_store,
            self.patch_request_normalizer,
            self.patch_safety_guard,
            self.patch_proposal_builder,
            self.diff_preview_builder,
            self.test_plan_builder,
            self.test_runner_preview,
            self.rollback_metadata_builder,
            self.action_gateway,
            self.audit_log,
            self.redaction,
        )
        self.sandbox_workspace_builder = SandboxWorkspaceBuilder(self.redaction)
        self.sandbox_store = SandboxStore(self.audit_log)
        self.sandbox_patch_applier = SandboxPatchApplierPreview(self.audit_log)
        self.command_guard = CommandExecutionGuard()
        self.sandbox_test_runner = SandboxTestRunner(self.command_guard, self.audit_log, self.redaction)
        self.sandbox_result_store = SandboxResultStore()
        self.apply_preparation_builder = ApplyPreparationBuilder(self.action_gateway, self.audit_log)
        self.apply_package_service = ApplyPackageService(self.redaction)
        self.sandbox_runtime = SandboxRuntime(
            self,
            self.host_project_registry,
            self.file_snapshot_store,
            self.patch_runtime,
            self.sandbox_workspace_builder,
            self.sandbox_store,
            self.sandbox_patch_applier,
            self.command_guard,
            self.sandbox_test_runner,
            self.sandbox_result_store,
            self.apply_preparation_builder,
            self.apply_package_service,
            self.audit_log,
            self.redaction,
        )
        self.ui_state_service = UiStateService(self.audit_log, self.redaction)
        self.storage_config = StorageConfigService()
        self.profile_manager = ProfileManager(self.storage_config, self.audit_log, self.redaction)
        self.state_serializer = RuntimeStateSerializer(self.redaction)
        self.state_loader = RuntimeStateLoader(self.redaction, self.audit_log)
        self.storage_adapter = SQLiteStorageAdapter(self.redaction)
        self.snapshot_service = RuntimeSnapshotService(self.state_serializer, self.state_loader, self.redaction, self.audit_log)
        self.storage_health_service = StorageHealthService(self.storage_config)
        self.retention_policy_service = RetentionPolicyService(self.audit_log)
        self.security_config_service = SecurityConfigService()
        self.password_hasher = PasswordHasher()
        self.token_manager = TokenManager(self.audit_log)
        self.encryption_service = EncryptionService(self.audit_log)
        self.vault_storage = VaultStorage(self.storage_adapter, self.audit_log, self.redaction)
        self.secret_vault = SecretVault(self.vault_storage, self.encryption_service, self.audit_log, self.redaction)
        self.auth_guard = AuthGuard(self.security_config_service, self.token_manager, self.audit_log)
        self.security_runtime = SecurityRuntime(self.security_config_service, self.password_hasher, self.token_manager, self.encryption_service, self.vault_storage, self.secret_vault, self.auth_guard, self.audit_log, self.redaction)

        self.localization_config_service = LocalizationConfigService()
        self.language_registry = LanguageRegistry()
        self.translation_service = TranslationService(self.language_registry)
        self.ui_localizer = UiLocalizer(self.translation_service)
        self.dialog_localizer = DialogLocalizer(self.translation_service)
        self.launcher_config_service = LauncherConfigService()
        self.port_checker = PortChecker()
        self.startup_checker = StartupChecker()
        self.launcher_diagnostics_service = LauncherDiagnosticsService(self.launcher_config_service, self.port_checker, self.startup_checker)
        self.launch_report_service = LaunchReportService()
        self.provider_preset_registry = ProviderPresetRegistry()
        self.provider_runtime_config_service = ProviderRuntimeConfigService(self.audit_log)
        self.provider_usage_tracker = ProviderUsageTracker(self.audit_log)
        self.provider_diagnostics_service = ProviderDiagnosticsService(self.provider_runtime_config_service, self.provider_usage_tracker, self.audit_log)
        self.provider_runtime = ProviderRuntime(self, self.provider_preset_registry, self.provider_runtime_config_service, self.provider_usage_tracker, self.audit_log, self.redaction)

        self.provider_reliability_scorer = ProviderReliabilityScorer(self.provider_usage_tracker)
        self.provider_quality_scorer = ProviderQualityScorer(self.audit_log)
        self.provider_latency_tracker = ProviderLatencyTracker()
        self.provider_error_tracker = ProviderErrorTracker(self.redaction)
        self.provider_budget_limit_service = ProviderBudgetLimitService(self.audit_log)
        self.provider_fallback_chain_service = ProviderFallbackChainService(self.audit_log)
        self.provider_selection_policy = ProviderSelectionPolicy(self.registry, self.provider_runtime_config_service, self.provider_reliability_scorer, self.provider_quality_scorer, self.provider_budget_limit_service)
        self.provider_output_comparator = ProviderOutputComparator()
        self.provider_consensus_builder = ProviderConsensusBuilder()
        self.multi_provider_review_runtime = MultiProviderReviewRuntime(self, self.provider_selection_policy, self.provider_budget_limit_service, self.provider_output_comparator, self.provider_consensus_builder, self.provider_reliability_scorer, self.provider_quality_scorer, self.provider_latency_tracker, self.provider_error_tracker, self.audit_log, self.redaction)
        self.provider_performance_report_builder = ProviderPerformanceReportBuilder(self.provider_reliability_scorer, self.provider_quality_scorer, self.provider_usage_tracker, self.provider_fallback_chain_service, self.provider_budget_limit_service)
        self.provider_intelligence_runtime = ProviderIntelligenceRuntime(self.provider_reliability_scorer, self.provider_quality_scorer, self.provider_latency_tracker, self.provider_error_tracker, self.provider_budget_limit_service, self.provider_fallback_chain_service, self.provider_selection_policy, self.provider_output_comparator, self.provider_consensus_builder, self.multi_provider_review_runtime, self.provider_performance_report_builder, self.audit_log)

        self.real_apply_config_service = RealApplyConfigService(self.audit_log)
        self.safe_workspace_registry = SafeWorkspaceRegistry(self.audit_log)
        self.real_apply_path_guard = PathGuard(self.real_apply_config_service, self.audit_log)
        self.real_apply_file_classifier = FileClassifier(self.real_apply_config_service, self.audit_log)
        self.real_apply_diff_validator = DiffValidator(self.real_apply_config_service)
        self.real_apply_gate = ApplyGate(self.real_apply_config_service, self.safe_workspace_registry, self.real_apply_path_guard, self.real_apply_file_classifier, self.real_apply_diff_validator, self.audit_log)
        self.backup_service = BackupService(self.audit_log, self.redaction)
        self.apply_executor = ApplyExecutor(self.audit_log)
        self.rollback_service = RollbackService(self.backup_service, self.audit_log)
        self.apply_audit_builder = ApplyAuditBuilder(self.redaction)
        self.real_apply_runtime = RealApplyRuntime(self.real_apply_config_service, self.safe_workspace_registry, self.real_apply_path_guard, self.real_apply_file_classifier, self.real_apply_diff_validator, self.real_apply_gate, self.backup_service, self.apply_executor, self.rollback_service, self.apply_audit_builder, self.audit_log, self.redaction)
        self._last_save_at = None
        self._last_load_at = None
        self.resolver = ValidatedRoutingResolver(self)
        self._initialized = False

    def initialize_storage(self):
        config = self.storage_config.get_default_config()
        if not config.enabled:
            self.audit_log.add_entry("storage_initialized", summary="Storage disabled")
            return
        self.storage_config.ensure_profile_dirs(config.activeProfileId, config)
        db_path = self.storage_config.resolve_sqlite_path(config.activeProfileId, config)
        self.storage_adapter.initialize(db_path)
        self.profile_manager.ensure_default_profile()
        self.audit_log.add_entry("storage_initialized", summary=f"Storage initialized for profile {config.activeProfileId}", details={"backend":"sqlite"})

    def initialize(self):
        if not self._initialized:
            try:
                self.initialize_storage()
            except Exception as e:
                self.audit_log.add_entry("storage_initialization_failed", summary=f"Storage initialization failed: {str(e)}")
            self._initialized = True
            self.policy_registry.load_defaults()
            self.security_runtime.initialize()
            self.audit_log.add_entry("runtime_initialized", summary="Lumi runtime initialized v1.3.0")
            if self.storage_config.get_default_config().autoLoad:
                try:
                    self.load_state(PersistenceLoadRequest(profileId=self.storage_config.get_default_config().activeProfileId, safeMode=True))
                except Exception as e:
                    self.audit_log.add_entry("state_load_failed", summary=f"Auto-load failed: {str(e)}")
        return self.get_status()

    def reset_for_tests(self):
        self.registry.clear_for_tests()
        self.audit_log.clear_for_tests()
        self.policy_registry.clear_for_tests()
        self.action_registry.clear_for_tests()
        self.approval_manager.clear_for_tests()
        self.decision_history.clear_for_tests()
        self.dialog_sessions.clear_for_tests()
        self.dialog_messages.clear_for_tests()
        self.host_app_registry.clear_for_tests()
        self.callback_service.clear_for_tests()
        self.host_project_registry.clear_for_tests()
        self.file_snapshot_store.clear_for_tests()
        self.project_scan_runtime.clear_for_tests()
        self.patch_runtime.clear_for_tests()
        self.sandbox_store.clear_for_tests()
        self.sandbox_result_store.clear_for_tests()
        self.profile_manager.clear_for_tests()
        self.token_manager.revoke_all()
        self.security_config_service.disable_protected_mode()
        self.security_runtime._password_hash = None
        self.security_runtime._configured = False
        self.security_runtime._unlocked = False
        self.security_runtime._failed_attempts = 0
        self.security_runtime._locked_until = None
        self.encryption_service.clear_key()
        if hasattr(self, "provider_budget_limit_service"):
            self.provider_budget_limit_service.reset_session_counters()
        if hasattr(self, "provider_quality_scorer"):
            self.provider_quality_scorer._samples.clear(); self.provider_quality_scorer._scores.clear()
        if hasattr(self, "provider_latency_tracker"):
            self.provider_latency_tracker._records.clear()
        if hasattr(self, "provider_error_tracker"):
            self.provider_error_tracker._errors.clear()
        if hasattr(self, "provider_fallback_chain_service"):
            self.provider_fallback_chain_service._chains.clear()
        if hasattr(self, "safe_workspace_registry"):
            self.safe_workspace_registry.clear_for_tests()
        if hasattr(self, "backup_service"):
            self.backup_service.clear_for_tests()
        if hasattr(self, "apply_executor"):
            self.apply_executor.clear_for_tests()
        if hasattr(self, "rollback_service"):
            self.rollback_service.clear_for_tests()
        if hasattr(self, "real_apply_config_service"):
            self.real_apply_config_service.disable_apply()
        self._initialized = False
        self.initialize()

    def get_status(self) -> RuntimeStatus:
        providers = self.registry.list_providers()
        enabled = self.registry.list_enabled_providers()
        actions = self.action_registry.list_actions()
        rules = self.policy_registry.list_rules()
        limits = self.policy_registry.list_limits()
        sessions = self.dialog_sessions.list_sessions()
        hosts = self.host_app_registry.list_hosts()
        callbacks = self.callback_service.list_callbacks()
        projects = self.host_project_registry.list_projects()
        snapshots = self.file_snapshot_store.list_all_snapshots()
        profiles = self.profile_manager.list_profiles()
        active_profile = self.profile_manager.get_active_profile()
        try:
            storage_health = self.storage_health_service.check_health(self.storage_adapter, self.storage_config.get_default_config(), active_profile.profileId if active_profile else "default")
        except Exception:
            storage_health = None
        status = "not_initialized" if not self._initialized else "no_providers" if not enabled else "ok"
        return RuntimeStatus(
            initialized=self._initialized,
            providersCount=len(providers),
            enabledProvidersCount=len(enabled),
            auditEntriesCount=len(self.audit_log.list_entries()),
            version=VERSION,
            mode=self.config.mode,
            status=status,
            actionsCount=len(actions),
            enabledActionsCount=len([a for a in actions if a.enabled]),
            policyRulesCount=len(rules),
            enabledPolicyRulesCount=len([r for r in rules if r.enabled]),
            pendingApprovalPromptsCount=len(self.approval_manager.list_pending()),
            limitsCount=len(limits),
            enabledLimitsCount=len([l for l in limits if l.enabled]),
            decisionsCount=len(self.decision_history.list_decisions()),
            dialogSessionsCount=len(sessions),
            activeDialogSessionsCount=len([s for s in sessions if s.status == "active"]),
            dialogMessagesCount=len(self.dialog_messages.list_all()),
            hostAppsCount=len(hosts),
            activeHostAppsCount=len([h for h in hosts if h.status == "active"]),
            callbacksCount=len(callbacks),
            connectorModesSupported=["rest", "sdk", "sidecar"],
            projectsCount=len(projects),
            activeProjectsCount=len([p for p in projects if p.status == "active"]),
            fileSnapshotsCount=len(snapshots),
            projectScansCount=self.project_scan_runtime.scan_count,
            patchPlansCount=len(self.patch_runtime._patch_results),
            diffPreviewsCount=len(self.patch_runtime._diff_previews),
            testPlansCount=len(self.patch_runtime._test_plans),
            rollbackMetadataCount=len(self.patch_runtime._rollback_metadata),
            sandboxWorkspacesCount=len(self.sandbox_store.list_workspaces()),
            sandboxTestResultsCount=len(self.sandbox_result_store.list_test_results()),
            applyPackagesCount=len(self.sandbox_result_store.list_apply_packages()),
            storageStatus=storage_health.status if storage_health else "degraded",
            activeProfileId=active_profile.profileId if active_profile else "default",
            profilesCount=len(profiles),
            lastSaveAt=self._last_save_at,
            lastLoadAt=self._last_load_at,
            securityStatus=self.security_runtime.get_security_state().status,
            securityMode=self.security_runtime.get_security_state().mode,
            securityConfigured=self.security_runtime.get_security_state().configured,
            vaultEnabled=self.security_config_service.get_default_config().vaultEnabled,
            secretsCount=self.secret_vault.list_secrets().count,
            protectedEndpointsEnabled=self.security_config_service.get_default_config().protectedEndpointsEnabled,
            providerRuntimeConfigsCount=len(self.provider_runtime_config_service.list_configs()),
            realProvidersCount=len([c for c in self.provider_runtime_config_service.list_configs() if c.runtimeType not in ("mock", "local", "disabled")]),
            liveProvidersAllowedCount=len([c for c in self.provider_runtime_config_service.list_configs() if c.liveCallsAllowed]),
            providerUsageRecordsCount=len(self.provider_usage_tracker.list_usage()),
            providerConnectionTestsCount=0,
            providerReliabilityRecordsCount=len(getattr(self.provider_reliability_scorer, "_scores", {})) if hasattr(self, "provider_reliability_scorer") else 0,
            providerQualityRecordsCount=sum(len(v) for v in getattr(self.provider_quality_scorer, "_samples", {}).values()) if hasattr(self, "provider_quality_scorer") else 0,
            providerFallbackChainsCount=len(self.provider_fallback_chain_service.list_chains()) if hasattr(self, "provider_fallback_chain_service") else 0,
            providerBudgetLimitsCount=len(self.provider_budget_limit_service.list_limits()) if hasattr(self, "provider_budget_limit_service") else 0,
            multiProviderReviewsCount=0,
            activeLanguage=self.localization_config_service.get_active_language(),
            defaultLanguage=self.localization_config_service.get_config().defaultLanguage,
            launcherStatus=self.launcher_diagnostics_service.run_diagnostics().status,
            dashboardUrl=self.launcher_config_service.dashboard_url(),
            realApplyMode=self.real_apply_config_service.get_config().mode if hasattr(self, "real_apply_config_service") else "disabled",
            controlledApplyEnabled=(self.real_apply_config_service.get_config().mode == "controlled") if hasattr(self, "real_apply_config_service") else False,
            safeWorkspacesCount=len(self.safe_workspace_registry.list_workspaces()) if hasattr(self, "safe_workspace_registry") else 0,
            applyResultsCount=len(self.apply_executor.list_results()) if hasattr(self, "apply_executor") else 0,
            rollbackPackagesCount=len(self.rollback_service.list_rollback_packages()) if hasattr(self, "rollback_service") else 0,
            backupsCount=len(self.backup_service.list_backups()) if hasattr(self, "backup_service") else 0,
        )

    def register_provider(self, profile: ProviderProfile) -> ProviderProfile:
        if not self._initialized:
            self.initialize()
        self.registry.add_provider(profile)
        self.audit_log.add_entry("provider_registered", provider_id=profile.providerId, summary=f"Provider {profile.providerId} registered", details={"profile": self.redaction.redact_model(profile)})
        return self.registry.get_provider(profile.providerId)

    def list_providers(self) -> List[ProviderProfile]:
        return self.registry.list_providers()

    def get_provider(self, provider_id: str) -> ProviderProfile:
        return self.registry.get_provider(provider_id)

    def enable_provider(self, provider_id: str) -> ProviderProfile:
        profile = self.registry.enable_provider(provider_id)
        self.audit_log.add_entry("provider_enabled", provider_id=provider_id, summary=f"Provider {provider_id} enabled")
        return profile

    def disable_provider(self, provider_id: str) -> ProviderProfile:
        profile = self.registry.disable_provider(provider_id)
        self.audit_log.add_entry("provider_disabled", provider_id=provider_id, summary=f"Provider {provider_id} disabled")
        return profile

    def health_check_provider(self, provider_id: str):
        profile = self.registry.get_provider(provider_id)
        adapter = self.get_adapter(profile)
        result = adapter.health_check(profile)
        self.audit_log.add_entry("provider_health_checked", provider_id=provider_id, summary=f"Health check for {provider_id}: {result.get('status')}", details=result)
        return result

    def classify_task(self, task_request: TaskRequest):
        return self.task_classifier.classify(task_request)

    def build_task_requirements(self, task_request: TaskRequest):
        classification = self.classify_task(task_request)
        return self.task_requirements_builder.build(classification)

    def build_route(self, task_request: TaskRequest, classification=None, requirements=None):
        if not self._initialized:
            self.initialize()
        if not task_request.taskId:
            task_request.taskId = str(uuid.uuid4())
        classification = classification or self.classify_task(task_request)
        requirements = requirements or self.task_requirements_builder.build(classification)
        return self.provider_router.build_route(task_request, requirements, classification)

    def resolve(self, task_request: TaskRequest) -> StructuredDecision:
        if not self._initialized:
            self.initialize()
        task_id = task_request.taskId or str(uuid.uuid4())
        task_request.taskId = task_id
        self.audit_log.add_entry("task_received", task_id=task_id, summary=f"Task {task_id} received")
        decision = self.resolver.resolve(task_request)
        self.audit_log.add_entry("decision_created", task_id=task_id, decision_id=decision.decisionId, summary=f"Decision {decision.decisionId}: {decision.status}", details={"status": decision.status, "winningRule": decision.winningRule, "actionGatewayStatus": decision.metadata.get("actionGatewayResult", {}).get("status") if isinstance(decision.metadata.get("actionGatewayResult"), dict) else None})
        session_id = (task_request.metadata or {}).get("dialogSessionId")
        self.decision_history.add_decision(decision, task_request, session_id)
        if session_id and self.dialog_sessions.session_exists(session_id):
            self.dialog_sessions.link_decision(session_id, decision.decisionId)
            self.decision_history.link_decision_to_session(decision.decisionId, session_id)
        return decision

    def get_audit_entries(self) -> List[AuditEntry]:
        return self.audit_log.list_entries()

    def get_audit_entry(self, audit_id: str) -> AuditEntry:
        return self.audit_log.get_entry(audit_id)

    def get_adapter(self, profile: ProviderProfile) -> ProviderAdapterBase:
        return MockProviderAdapter(self.redaction)

    # Policy API facade
    def list_policies(self): return self.policy_registry.list_rules()
    def get_policy_summary(self): return self.policy_registry.get_summary()
    def add_policy_rule(self, rule: PolicyRule): return self.policy_registry.add_rule(rule)
    def enable_policy_rule(self, rule_id: str): return self.policy_registry.enable_rule(rule_id)
    def disable_policy_rule(self, rule_id: str): return self.policy_registry.disable_rule(rule_id)
    def list_limits(self): return self.policy_registry.list_limits()
    def add_limit(self, limit: LimitDefinition): return self.policy_registry.add_limit(limit)
    def enable_limit(self, limit_id: str): return self.policy_registry.enable_limit(limit_id)
    def disable_limit(self, limit_id: str): return self.policy_registry.disable_limit(limit_id)
    def check_policy(self, check_request: PolicyCheckRequest): return self.policy_engine.check_action(check_request)

    # Action API facade
    def register_action(self, action_def: ActionDefinition): return self.action_registry.register_action(action_def)
    def list_actions(self): return self.action_registry.list_actions()
    def get_action(self, action_id: str): return self.action_registry.get_action(action_id)
    def enable_action(self, action_id: str): return self.action_registry.enable_action(action_id)
    def disable_action(self, action_id: str): return self.action_registry.disable_action(action_id)
    def propose_action(self, action_id: str, task_request=None, decision=None, proposed_input=None, requested_mode="proposal"):
        return self.action_gateway.propose_action(action_id, task_request, decision, proposed_input, requested_mode)
    def check_action_policy(self, action_id: str, task_request=None, decision=None, proposed_input=None, requested_mode="proposal"):
        return self.action_gateway.check_action_policy(action_id, task_request, decision, proposed_input, requested_mode)
    def list_approvals(self): return self.approval_manager.list_all()
    def get_approval(self, prompt_id: str): return self.approval_manager.get_prompt(prompt_id)
    def record_approval_decision(self, prompt_id: str, decision: str, user_id: str | None = None, reason: str | None = None, metadata: dict | None = None):
        return self.approval_manager.record_decision(prompt_id, decision, user_id, reason, metadata)

    # History/explainability/dialog API facade
    def add_decision_history(self, decision, task_request=None, session_id=None): return self.decision_history.add_decision(decision, task_request, session_id)
    def get_decision_history(self, decision_id: str): return self.decision_history.get_decision(decision_id)
    def list_decision_history(self, query=None): return self.decision_history.filter_decisions(query).records if query else self.decision_history.list_decisions()
    def filter_decision_history(self, query): return self.decision_history.filter_decisions(query)
    def build_decision_timeline(self, decision_id: str):
        record = self.decision_history.get_decision(decision_id)
        return self.timeline_builder.build_timeline(decision_id=decision_id, task_id=record.taskId if record else None, session_id=record.sessionId if record else None)
    def explain_decision(self, decision_id: str, mode: str = "human", include_timeline: bool = False): return self.explanation_builder.build_explanation_response(decision_id, mode, include_timeline)
    def create_dialog_session(self, host_app_id=None, user_id=None, title=None, metadata=None): return self.dialog_sessions.create_session(host_app_id, user_id, title, metadata)
    def list_dialog_sessions(self): return self.dialog_sessions.list_sessions()
    def get_dialog_session(self, session_id: str): return self.dialog_sessions.get_session(session_id)
    def close_dialog_session(self, session_id: str): return self.dialog_sessions.close_session(session_id)
    def send_dialog_message(self, session_id: str, text: str, metadata=None): return self.dialog_runtime.send_message(session_id, text, metadata)
    def list_dialog_messages(self, session_id: str): return self.dialog_messages.list_messages(session_id)


    # Integration API facade
    def register_host_app(self, manifest: HostAppManifest):
        if not self._initialized:
            self.initialize()
        return self.host_app_registry.register_host(manifest)

    def list_host_apps(self):
        return self.host_app_registry.list_hosts()

    def get_host_app(self, host_app_id: str):
        return self.host_app_registry.get_host(host_app_id)

    def enable_host_app(self, host_app_id: str):
        return self.host_app_registry.enable_host(host_app_id)

    def disable_host_app(self, host_app_id: str):
        return self.host_app_registry.disable_host(host_app_id)

    def integration_handshake(self, request: IntegrationHandshakeRequest):
        if not self._initialized:
            self.initialize()
        return self.handshake_service.handshake(request)

    def process_host_event(self, event: HostEvent):
        return self.host_event_processor.process_event(event)

    def get_connector_contract_info(self):
        if self.audit_log:
            self.audit_log.add_entry("connector_contract_requested", summary="Connector contract requested")
        return self.connector_contract.get_connector_summary()

    def get_sidecar_status(self, host: str = "127.0.0.1", port: int = 8000):
        if self.audit_log:
            self.audit_log.add_entry("sidecar_status_requested", summary="Sidecar status requested")
        return self.sidecar_runtime_info.get_sidecar_status(self.get_status(), host, port)

    def get_sidecar_instructions(self):
        return {"launch": self.sidecar_runtime_info.get_launch_instructions(), "embed": self.sidecar_runtime_info.get_embed_instructions()}

    def register_decision_callback(self, config: DecisionCallbackConfig):
        return self.callback_service.register_callback(config)

    def list_decision_callbacks(self, host_app_id: str | None = None):
        return self.callback_service.list_callbacks(host_app_id)

    def deliver_decision_callback(self, payload: DecisionCallbackPayload, mode: str = "mock"):
        return self.callback_service.deliver_callback(payload, mode)


    # Project scanner API facade
    def register_project(self, manifest: ProjectManifest):
        if not self._initialized:
            self.initialize()
        return self.host_project_registry.register_project(manifest)

    def list_projects(self):
        return self.host_project_registry.list_projects()

    def get_project(self, project_id: str):
        return self.host_project_registry.get_project(project_id)

    def enable_project(self, project_id: str):
        return self.host_project_registry.enable_project(project_id)

    def disable_project(self, project_id: str):
        return self.host_project_registry.disable_project(project_id)

    def add_file_snapshot(self, snapshot: FileSnapshot):
        return self.file_snapshot_store.add_snapshot(snapshot)

    def add_file_snapshots(self, project_id: str, snapshots: list[FileSnapshot]):
        return self.file_snapshot_store.add_snapshots(project_id, snapshots)

    def list_file_snapshots(self, project_id: str):
        return self.file_snapshot_store.list_snapshots(project_id)

    def scan_project(self, request: ProjectScanRequest):
        return self.project_scan_runtime.scan_project(request)

    def get_project_inventory(self, project_id: str):
        return self.project_scan_runtime.get_latest_inventory(project_id)

    def get_project_issues(self, project_id: str):
        return self.project_scan_runtime.get_latest_issues(project_id)

    def get_project_improvement_plan(self, project_id: str):
        return self.project_scan_runtime.get_latest_improvement_plan(project_id)


    # Patch planner API facade
    def plan_patch(self, request: PatchRequest):
        if not self._initialized:
            self.initialize()
        return self.patch_runtime.plan_patch(request)

    def get_patch_plan(self, result_id: str):
        return self.patch_runtime.get_patch_plan(result_id)

    def get_patch_proposal(self, patch_proposal_id: str):
        return self.patch_runtime.get_patch_proposal(patch_proposal_id)

    def get_diff_preview(self, diff_preview_id: str):
        return self.patch_runtime.get_diff_preview(diff_preview_id)

    def get_test_plan(self, test_plan_id: str):
        return self.patch_runtime.get_test_plan(test_plan_id)

    def get_test_run_preview(self, test_run_preview_id: str):
        return self.patch_runtime.get_test_run_preview(test_run_preview_id)

    def get_rollback_metadata(self, rollback_metadata_id: str):
        return self.patch_runtime.get_rollback_metadata(rollback_metadata_id)

    def list_patch_plans(self, project_id: str | None = None):
        return self.patch_runtime.list_patch_plans(project_id)


    # Sandbox API facade
    def create_sandbox_workspace(self, request: SandboxWorkspaceRequest):
        if not self._initialized:
            self.initialize()
        return self.sandbox_runtime.create_workspace(request)

    def get_sandbox_workspace(self, workspace_id: str):
        return self.sandbox_store.get_workspace(workspace_id)

    def list_sandbox_workspaces(self, project_id: str | None = None):
        return self.sandbox_store.list_workspaces(project_id)

    def discard_sandbox_workspace(self, workspace_id: str):
        return self.sandbox_store.discard_workspace(workspace_id)

    def apply_patch_preview_to_sandbox(self, workspace_id: str, diff_preview_id: str):
        return self.sandbox_runtime.apply_patch_preview(workspace_id, diff_preview_id)

    def run_sandbox_tests(self, request: SandboxTestRunRequest):
        return self.sandbox_runtime.run_sandbox_tests(request)

    def get_sandbox_test_result(self, test_run_result_id: str):
        return self.sandbox_result_store.get_test_result(test_run_result_id)

    def list_sandbox_test_results(self, project_id: str | None = None):
        return self.sandbox_result_store.list_test_results(project_id)

    def prepare_apply_package(self, request: ApplyPreparationRequest):
        return self.sandbox_runtime.prepare_apply_package(request)

    def get_apply_package(self, apply_package_id: str):
        return self.sandbox_result_store.get_apply_package(apply_package_id)

    def list_apply_packages(self, project_id: str | None = None):
        return self.sandbox_result_store.list_apply_packages(project_id)

    def check_command(self, command: str, project_type: str | None = None):
        return self.command_guard.validate_command(command, project_type)


    # UI API facade
    def get_ui_dashboard_summary(self):
        return self.ui_state_service.get_dashboard_summary(self)

    def get_ui_panel_configs(self):
        return self.ui_state_service.get_panel_configs()

    def get_ui_safety_labels(self):
        return self.ui_state_service.get_safety_labels()

    def get_integration_wizard_state(self):
        return self.ui_state_service.get_integration_wizard_state()

    def get_project_wizard_state(self):
        return self.ui_state_service.get_project_wizard_state()


    # Persistence API facade
    def save_state(self, request: PersistenceSaveRequest | None = None):
        request = request or PersistenceSaveRequest()
        profile_id = request.profileId or "default"
        self.audit_log.add_entry("state_save_requested", summary=f"State save requested for profile {profile_id}")
        state = self.state_serializer.serialize_runtime(self, request.includeAudit, request.includeSnapshots)
        saved = {}
        for collection, records in state.items():
            count = 0
            for record in records:
                rid = self.state_serializer.get_record_id(collection, record)
                self.storage_adapter.save_record(profile_id, collection, rid, record)
                count += 1
            saved[collection] = count
        from datetime import datetime, timezone
        from lumi.app.schemas.persistence import PersistenceSaveResult
        self._last_save_at = datetime.now(timezone.utc).isoformat()
        self.audit_log.add_entry("state_saved", summary=f"State saved for profile {profile_id}", details={"recordsSaved": saved})
        return PersistenceSaveResult(saveId=str(uuid.uuid4()), profileId=profile_id, status="saved", savedAt=self._last_save_at, collectionsSaved=list(saved.keys()), recordsSaved=saved)

    def load_state(self, request: PersistenceLoadRequest | None = None):
        request = request or PersistenceLoadRequest()
        profile_id = request.profileId or "default"
        self.audit_log.add_entry("state_load_requested", summary=f"State load requested for profile {profile_id}")
        collections = request.collections or self.storage_adapter.list_collections(profile_id)
        state = {c: self.storage_adapter.load_collection(profile_id, c) for c in collections}
        result = self.state_loader.load_runtime(self, state, collections=collections, safe_mode=request.safeMode)
        from datetime import datetime, timezone
        self._last_load_at = datetime.now(timezone.utc).isoformat()
        result.profileId = profile_id
        result.loadedAt = self._last_load_at
        self.audit_log.add_entry("state_loaded", summary=f"State loaded for profile {profile_id}", details={"recordsLoaded": result.recordsLoaded})
        return result

    def export_state_snapshot(self, request: ExportSnapshotRequest | None = None):
        request = request or ExportSnapshotRequest()
        self.audit_log.add_entry("snapshot_export_requested", summary=f"Snapshot export requested for profile {request.profileId}")
        return self.snapshot_service.export_snapshot(self, request.profileId or "default", request.includeAudit, request.includeSnapshots)

    def import_state_snapshot(self, request: ImportSnapshotRequest):
        self.audit_log.add_entry("snapshot_import_requested", summary=f"Snapshot import requested for profile {request.profileId}")
        return self.snapshot_service.import_snapshot(self, request)

    def get_storage_health(self):
        active = self.profile_manager.get_active_profile()
        health = self.storage_health_service.check_health(self.storage_adapter, self.storage_config.get_default_config(), active.profileId if active else "default")
        self.audit_log.add_entry("storage_health_checked", summary=f"Storage health: {health.status}")
        return health

    def list_profiles(self): return self.profile_manager.list_profiles()
    def create_profile(self, profile_id: str, display_name: str | None = None): return self.profile_manager.create_profile(profile_id, display_name)
    def set_active_profile(self, profile_id: str): return self.profile_manager.set_active_profile(profile_id)
    def reset_profile(self, profile_id: str):
        profile = self.profile_manager.reset_profile(profile_id)
        try: self.storage_adapter.clear_profile(profile_id)
        except Exception: pass
        return profile
    def get_retention_policy(self): return self.retention_policy_service.get_default_policy()
    def apply_retention_policy(self, dry_run: bool = True): return self.retention_policy_service.apply_retention(self, dry_run=dry_run)


    # Security API facade
    def get_security_state(self): return self.security_runtime.get_security_state()
    def setup_security_password(self, request: SetupPasswordRequest): return self.security_runtime.setup_password(request)
    def unlock_security(self, request: UnlockRequest): return self.security_runtime.unlock(request)
    def lock_security(self): return self.security_runtime.lock()
    def create_secret(self, request: SecretCreateRequest): return self.secret_vault.create_secret(request)
    def list_secrets(self): return self.secret_vault.list_secrets()
    def get_secret(self, secret_id: str): return self.secret_vault.get_secret(secret_id)
    def update_secret(self, secret_id: str, request: SecretUpdateRequest): return self.secret_vault.update_secret(secret_id, request)
    def delete_secret(self, secret_id: str): return self.secret_vault.delete_secret(secret_id)
    def resolve_secret(self, request: SecretResolveRequest): return self.secret_vault.resolve_secret(request.secretRef, request.purpose)
    def internal_get_secret_value(self, secret_ref: str): return self.secret_vault.internal_get_secret_value(secret_ref)
    def verify_token(self, token: str): return self.token_manager.verify_token(token)


    # Provider runtime API facade
    def list_provider_presets(self): return self.provider_preset_registry.list_presets()
    def get_provider_preset(self, preset_id: str): return self.provider_preset_registry.get_preset(preset_id)
    def create_provider_from_preset(self, provider_id: str, preset_id: str, display_name: str | None = None): return self.provider_runtime.create_provider_from_preset(provider_id, preset_id, display_name)
    def configure_provider_runtime(self, config: ProviderRuntimeConfig): return self.provider_runtime.configure_provider(config)
    def get_provider_runtime_config(self, provider_id: str): return self.provider_runtime_config_service.get_config(provider_id)
    def bind_provider_secret(self, provider_id: str, secret_ref: str): return self.provider_runtime.bind_provider_secret(provider_id, secret_ref)
    def create_and_bind_provider_secret(self, provider_id: str, request: CreateProviderSecretRequest): return self.provider_runtime.create_and_bind_secret(provider_id, request)
    def test_provider_connection(self, request: ProviderConnectionTestRequest): return self.provider_runtime.test_provider_connection(request)
    def discover_provider_models(self, request: ModelDiscoveryRequest): return self.provider_runtime.discover_models(request)
    def call_provider_live(self, request: ProviderLiveCallRequest): return self.provider_runtime.call_provider_live(request)
    def get_provider_diagnostics(self, provider_id: str): return self.provider_diagnostics_service.get_diagnostics(provider_id)
    def list_provider_diagnostics(self): return self.provider_diagnostics_service.list_diagnostics()
    def get_provider_usage(self, provider_id: str): return self.provider_usage_tracker.get_provider_summary(provider_id)
    def list_provider_usage(self, provider_id: str | None = None): return self.provider_usage_tracker.list_usage(provider_id)


    # Provider intelligence API facade
    def compute_provider_reliability(self, provider_id: str): return self.provider_reliability_scorer.compute_score(provider_id)
    def list_provider_reliability(self): return self.provider_reliability_scorer.compute_all()
    def record_provider_quality_sample(self, provider_id: str, validation_status: str, confidence: float, risk_flags: list | None = None, empty: bool = False, malformed: bool = False, conflict: bool = False): return self.provider_quality_scorer.record_sample(provider_id, validation_status, confidence, risk_flags, empty, malformed, conflict)
    def compute_provider_quality(self, provider_id: str): return self.provider_quality_scorer.compute_quality(provider_id)
    def list_provider_quality(self): return self.provider_quality_scorer.list_quality_scores()
    def set_provider_budget_limits(self, limits: ProviderBudgetLimits): return self.provider_budget_limit_service.set_limits(limits)
    def get_provider_budget_limits(self, provider_id: str): return self.provider_budget_limit_service.get_limits(provider_id)
    def check_provider_budget_limits(self, provider_id: str, planned_input_chars: int = 0, planned_tokens: int = 0): return self.provider_budget_limit_service.check_limits(provider_id, planned_input_chars, planned_tokens)
    def create_provider_fallback_chain(self, chain: ProviderFallbackChain): return self.provider_fallback_chain_service.create_chain(chain)
    def list_provider_fallback_chains(self): return self.provider_fallback_chain_service.list_chains()
    def select_providers(self, request: ProviderSelectionRequest): return self.provider_selection_policy.select_providers(request)
    def run_multi_provider_review(self, request: MultiProviderReviewRequest): return self.multi_provider_review_runtime.run_review(request)
    def build_provider_comparison_report(self, provider_ids=None): return self.provider_performance_report_builder.build_report(provider_ids)
    def get_provider_latency(self, provider_id: str): return self.provider_latency_tracker.get_latency_records(provider_id)
    def get_provider_errors(self, provider_id: str): return self.provider_error_tracker.get_errors(provider_id)

    # Localization and launcher API facade
    def list_languages(self): return self.language_registry.list_languages()
    def get_localization_config(self): return self.localization_config_service.get_config()
    def set_language(self, request: SetLanguageRequest): return self.localization_config_service.set_language(request.language, request.profileId or "default")
    def translate(self, request: TranslationLookupRequest): return self.translation_service.lookup(request)
    def get_dictionary(self, language: str): return self.translation_service.get_dictionary(language)
    def get_localized_ui_state(self): return self.ui_localizer.build_localized_ui_state(self)
    def get_dialog_command_patterns(self, language: str | None = None): return self.dialog_localizer.get_command_patterns(language or self.localization_config_service.get_active_language())
    def get_active_language(self): return self.localization_config_service.get_active_language()
    def get_launcher_status(self): return self.launcher_diagnostics_service.run_diagnostics()
    def get_launcher_diagnostics(self): return self.launcher_diagnostics_service.run_diagnostics()
    def get_launcher_port_check(self, host: str = "127.0.0.1", port: int = 8000): return self.port_checker.check_port(host, port)
    def get_launcher_report(self):
        diagnostics = self.launcher_diagnostics_service.run_diagnostics()
        return self.launch_report_service.build_report(diagnostics)


    # Real apply API facade
    def get_real_apply_config(self): return self.real_apply_runtime.get_apply_config()
    def enable_controlled_apply(self): return self.real_apply_runtime.enable_controlled_apply()
    def disable_real_apply(self): return self.real_apply_runtime.disable_apply()
    def register_safe_workspace(self, request: RegisterWorkspaceRequest): return self.real_apply_runtime.register_workspace(request)
    def list_safe_workspaces(self): return self.real_apply_runtime.list_workspaces()
    def get_safe_workspace(self, workspace_id: str): return self.real_apply_runtime.get_workspace(workspace_id)
    def enable_workspace_apply(self, workspace_id: str): return self.real_apply_runtime.enable_workspace_apply(workspace_id)
    def disable_workspace_apply(self, workspace_id: str): return self.real_apply_runtime.disable_workspace_apply(workspace_id)
    def check_real_apply_gate(self, request: ApplyGateRequest): return self.real_apply_runtime.check_apply_gate(request)
    def build_real_backup_plan(self, workspace_id: str, file_changes): return self.real_apply_runtime.build_backup_plan(workspace_id, file_changes)
    def create_real_backup(self, workspace_id: str, file_changes): return self.real_apply_runtime.create_backup(workspace_id, file_changes)
    def execute_controlled_apply(self, request: ApplyExecutionRequest): return self.real_apply_runtime.execute_apply(request)
    def list_real_apply_results(self): return self.real_apply_runtime.list_apply_results()
    def get_real_apply_result(self, apply_id: str): return self.real_apply_runtime.get_apply_result(apply_id)
    def list_real_backups(self, workspace_id: str | None = None): return self.real_apply_runtime.list_backups(workspace_id)
    def get_real_backup(self, backup_id: str): return self.real_apply_runtime.get_backup(backup_id)
    def list_rollback_packages(self, workspace_id: str | None = None): return self.real_apply_runtime.list_rollback_packages(workspace_id)
    def get_rollback_package(self, rollback_package_id: str): return self.real_apply_runtime.get_rollback_package(rollback_package_id)
    def preview_rollback(self, rollback_package_id: str): return self.real_apply_runtime.preview_rollback(rollback_package_id)
    def execute_controlled_rollback(self, request: RollbackRequest): return self.real_apply_runtime.execute_rollback(request)


runtime_instance = LumiRuntime()
runtime_instance.initialize()
