from pydantic import BaseModel, Field


class RuntimeStatus(BaseModel):
    initialized: bool = False
    providersCount: int = 0
    enabledProvidersCount: int = 0
    auditEntriesCount: int = 0
    version: str = "1.7.0"
    mode: str = "local"
    status: str = "ok"
    errors: list[str] = Field(default_factory=list)
    actionsCount: int = 0
    enabledActionsCount: int = 0
    policyRulesCount: int = 0
    enabledPolicyRulesCount: int = 0
    pendingApprovalPromptsCount: int = 0
    limitsCount: int = 0
    enabledLimitsCount: int = 0
    decisionsCount: int = 0
    dialogSessionsCount: int = 0
    activeDialogSessionsCount: int = 0
    dialogMessagesCount: int = 0
    hostAppsCount: int = 0
    activeHostAppsCount: int = 0
    callbacksCount: int = 0
    connectorModesSupported: list[str] = Field(default_factory=list)
    projectsCount: int = 0
    activeProjectsCount: int = 0
    fileSnapshotsCount: int = 0
    projectScansCount: int = 0
    patchPlansCount: int = 0
    diffPreviewsCount: int = 0
    testPlansCount: int = 0
    rollbackMetadataCount: int = 0
    sandboxWorkspacesCount: int = 0
    sandboxTestResultsCount: int = 0
    applyPackagesCount: int = 0
    storageStatus: str = "unknown"
    activeProfileId: str = "default"
    profilesCount: int = 0
    lastSaveAt: str | None = None
    lastLoadAt: str | None = None
    securityStatus: str = "not_configured"
    securityMode: str = "compatibility"
    securityConfigured: bool = False
    vaultEnabled: bool = False
    secretsCount: int = 0
    protectedEndpointsEnabled: bool = False
    providerRuntimeConfigsCount: int = 0
    realProvidersCount: int = 0
    liveProvidersAllowedCount: int = 0
    providerUsageRecordsCount: int = 0
    providerConnectionTestsCount: int = 0

    providerReliabilityRecordsCount: int = 0
    providerQualityRecordsCount: int = 0
    providerFallbackChainsCount: int = 0
    providerBudgetLimitsCount: int = 0
    multiProviderReviewsCount: int = 0
    activeLanguage: str = "ru"
    defaultLanguage: str = "ru"
    launcherStatus: str = "unknown"
    dashboardUrl: str = "http://127.0.0.1:8000/ui"
    realApplyMode: str = "disabled"
    controlledApplyEnabled: bool = False
    safeWorkspacesCount: int = 0
    applyResultsCount: int = 0
    rollbackPackagesCount: int = 0
    backupsCount: int = 0
