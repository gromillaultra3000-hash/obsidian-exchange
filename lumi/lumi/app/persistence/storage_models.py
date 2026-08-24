COLLECTIONS = [
    "providers","actions","policy_rules","policy_limits","host_apps","projects","file_snapshots",
    "decisions","dialog_sessions","dialog_messages","approvals","project_scan_results","patch_plans",
    "diff_previews","test_plans","rollback_metadata","sandbox_workspaces","sandbox_test_results",
    "apply_packages","audit_entries","ui_state"
]
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS lumi_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    collection TEXT NOT NULL,
    record_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(profile_id, collection, record_id)
);
CREATE INDEX IF NOT EXISTS idx_lumi_records_profile ON lumi_records(profile_id);
CREATE INDEX IF NOT EXISTS idx_lumi_records_collection ON lumi_records(profile_id, collection);
CREATE INDEX IF NOT EXISTS idx_lumi_records_record ON lumi_records(profile_id, collection, record_id);
CREATE TABLE IF NOT EXISTS lumi_profile_meta (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}'
);
"""
