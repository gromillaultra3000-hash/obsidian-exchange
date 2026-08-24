import os
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

StorageBackendType = Literal["sqlite", "json", "memory"]
StorageStatus = Literal["ready", "not_initialized", "degraded", "failed", "disabled"]
ProfileStatus = Literal["active", "inactive", "archived", "corrupted"]

class RuntimeProfile(BaseModel):
    profileId: str
    displayName: str = ""
    status: ProfileStatus = "active"
    createdAt: str = ""
    updatedAt: str = ""
    storageBackend: StorageBackendType = "sqlite"
    storagePath: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class StorageConfig(BaseModel):
    enabled: bool = True
    backendType: StorageBackendType = "sqlite"
    dataDir: str = Field(default_factory=lambda: os.getenv("LUMI_DATA_DIR") or "data/lumi_profiles")
    activeProfileId: str = "default"
    autoSave: bool = False
    autoLoad: bool = False
    redactedOnly: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class StorageHealth(BaseModel):
    status: StorageStatus = "not_initialized"
    backendType: StorageBackendType = "sqlite"
    activeProfileId: str = "default"
    storagePath: Optional[str] = None
    readable: bool = False
    writable: bool = False
    lastSaveAt: Optional[str] = None
    lastLoadAt: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PersistenceSaveRequest(BaseModel):
    profileId: Optional[str] = "default"
    includeAudit: bool = True
    includeSnapshots: bool = True
    includeUiState: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PersistenceSaveResult(BaseModel):
    saveId: str
    profileId: str
    status: str = "saved"
    savedAt: str = ""
    collectionsSaved: List[str] = Field(default_factory=list)
    recordsSaved: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PersistenceLoadRequest(BaseModel):
    profileId: Optional[str] = "default"
    collections: Optional[List[str]] = None
    safeMode: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class PersistenceLoadResult(BaseModel):
    loadId: str
    profileId: str
    status: str = "loaded"
    loadedAt: str = ""
    collectionsLoaded: List[str] = Field(default_factory=list)
    recordsLoaded: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RuntimeSnapshot(BaseModel):
    snapshotId: str
    profileId: str = "default"
    createdAt: str = ""
    version: str = "1.2.0"
    redacted: bool = True
    collections: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ExportSnapshotRequest(BaseModel):
    profileId: Optional[str] = "default"
    includeAudit: bool = True
    includeSnapshots: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ExportSnapshotResult(BaseModel):
    exportId: str
    profileId: str
    createdAt: str = ""
    snapshot: RuntimeSnapshot
    filePath: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ImportSnapshotRequest(BaseModel):
    profileId: Optional[str] = "default"
    snapshot: RuntimeSnapshot
    mode: Literal["merge", "replace"] = "merge"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ImportSnapshotResult(BaseModel):
    importId: str
    profileId: str
    importedAt: str = ""
    status: str = "imported"
    collectionsImported: List[str] = Field(default_factory=list)
    recordsImported: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RetentionPolicy(BaseModel):
    policyId: str = "default"
    maxAuditEntries: int = 1000
    maxDecisions: int = 500
    maxDialogMessagesPerSession: int = 200
    keepAllProfiles: bool = True
    keepAllActions: bool = True
    keepAllProviders: bool = True
    keepAllProjects: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
