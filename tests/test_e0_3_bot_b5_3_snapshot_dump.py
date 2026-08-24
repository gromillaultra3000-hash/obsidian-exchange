import copy
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "deploy/postgres/b64_snapshot_dump.py").read_text()
CHECKER_PATH = ROOT / "deploy/postgres/check_b64_notification_migration.py"


def _checker():
    spec = importlib.util.spec_from_file_location("b64_dirty_scan_contract", CHECKER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_blocked_scan():
    return {
        "schemaVersion": "b64-notification-dirty-data-scan.v1",
        "status": "IN_PROGRESS",
        "criterionStatus": "BLOCKED",
        "blockers": ["LEGACY_PENDING_DRAINED", "LEGACY_SENDING_RECONCILED"],
        "counts": {
            "total": 60, "pending": 4, "sending": 14, "sent": 42,
            "invalidState": 0, "invalidKind": 0, "staleSending": 10,
            "monteraAdmin": 0, "activeMonteraAdmin": 0,
            "invalidActiveRecipientShape": 0, "invalidLifecycle": 0,
        },
        "privacy": "NO_IDENTIFIERS_OR_PAYLOAD",
        "migrationApplied": False,
        "cutoverAuthorized": False,
        "unverifiedGates": [
            "CATALOG_ACL_OBJECT_HASH", "BACKUP_RESTORE_EQUALITY",
            "AUTHENTICATED_OWNER_REVIEW", "AMBIGUOUS_OPERATOR_DISPOSITION",
        ],
    }


def test_snapshot_dump_is_exact_read_only_snapshot_and_env_only():
    assert "REPEATABLE READ READ ONLY" in SOURCE
    assert "pg_export_snapshot()" in SOURCE and '"--snapshot", snapshot' in SOURCE
    assert "B64_READONLY_DATABASE_URL" in SOURCE and "--dsn" not in SOURCE
    assert "transaction_read_only" in SOURCE and "server_version_num" in SOURCE
    assert "_catalog_fingerprint(conn)" in SOURCE
    assert "B64_CATALOG_MANIFEST_PATH" in SOURCE
    assert "b64-catalog-security-fingerprint.v2" in SOURCE
    assert "inspect_dirty_data(conn, configure_transaction=False)" in SOURCE
    assert "if not valid_snapshot_scan(dirty_data):" in SOURCE
    assert '"dirtyDataScan": dirty_data' in SOURCE
    assert 'source.index("WITH sections' not in SOURCE
    assert 'source.rindex("\\nCOMMIT;")' not in SOURCE


def test_dirty_scan_can_share_the_exported_snapshot_without_restarting_transaction():
    source = (ROOT / "deploy/postgres/check_b64_notification_migration.py").read_text()
    assert "configure_transaction: bool = True" in source
    assert "if configure_transaction:" in source
    assert "NO_IDENTIFIERS_OR_PAYLOAD" in source


def test_snapshot_scan_contract_accepts_complete_aggregate_blocked_observation():
    assert _checker().valid_snapshot_scan(_valid_blocked_scan()) is True


def test_snapshot_scan_contract_accepts_partitioned_invalid_state_observation():
    scan = _valid_blocked_scan()
    scan["counts"]["total"] = 61
    scan["counts"]["invalidState"] = 1
    scan["blockers"].insert(0, "LEGACY_STATE_VALID")
    assert _checker().valid_snapshot_scan(scan) is True


def test_snapshot_scan_contract_rejects_target_shape_failure_and_empty_counts():
    scan = _valid_blocked_scan()
    scan.pop("unverifiedGates")
    scan["blockers"] = ["TARGET_PG17_READONLY_AND_LEGACY_SHAPE_EXACT"]
    scan["counts"] = {}
    assert _checker().valid_snapshot_scan(scan) is False


def test_snapshot_scan_contract_rejects_ambiguous_or_inconsistent_mutations():
    mutations = []
    for path, value in (
        (("criterionStatus",), "PASS"),
        (("counts", "total"), 61),
        (("counts", "staleSending"), 15),
        (("counts", "pending"), True),
        (("blockers",), ["LEGACY_SENDING_RECONCILED"]),
        (("extra",), False),
    ):
        item = copy.deepcopy(_valid_blocked_scan())
        if len(path) == 1:
            item[path[0]] = value
        else:
            item[path[0]][path[1]] = value
        mutations.append(item)
    assert mutations and all(_checker().valid_snapshot_scan(item) is False
                             for item in mutations)


def test_snapshot_scan_contract_rejects_impossible_diagnostic_subsets():
    mutations = []
    for name, maximum, blocker, position in (
        ("invalidState", 60, "LEGACY_STATE_VALID", 0),
        ("invalidKind", 60, "LEGACY_KIND_VALID", 0),
        ("invalidActiveRecipientShape", 18,
         "LEGACY_ACTIVE_RECIPIENT_SHAPE_VALID", 0),
        ("invalidLifecycle", 60, "LEGACY_LIFECYCLE_VALID", 0),
    ):
        item = copy.deepcopy(_valid_blocked_scan())
        item["counts"][name] = maximum + 1
        item["blockers"].insert(position, blocker)
        mutations.append(item)
    assert mutations and all(_checker().valid_snapshot_scan(item) is False
                             for item in mutations)


def test_snapshot_scan_contract_rejects_active_admin_outside_non_sent_partition():
    scan = _valid_blocked_scan()
    scan["counts"].update({
        "pending": 0, "sending": 0, "sent": 60, "staleSending": 0,
        "monteraAdmin": 1, "activeMonteraAdmin": 1,
    })
    scan["blockers"] = ["LEGACY_MONTERA_ADMIN_RECIPIENT_PROVEN"]
    assert _checker().valid_snapshot_scan(scan) is False


def test_snapshot_scan_contract_rejects_overlap_of_invalid_and_allowlisted_admin_kind():
    scan = _valid_blocked_scan()
    scan["counts"].update({"invalidKind": 60, "monteraAdmin": 1})
    scan["blockers"].insert(0, "LEGACY_KIND_VALID")
    assert _checker().valid_snapshot_scan(scan) is False


def test_snapshot_scan_contract_rejects_non_active_admin_outside_sent_partition():
    scan = _valid_blocked_scan()
    scan["counts"].update({
        "pending": 60, "sending": 0, "sent": 0, "staleSending": 0,
        "monteraAdmin": 1, "activeMonteraAdmin": 0,
    })
    scan["blockers"] = ["LEGACY_PENDING_DRAINED"]
    assert _checker().valid_snapshot_scan(scan) is False


def test_sensitive_archive_is_exclusive_0600_bounded_and_redacted():
    assert "O_EXCL" in SOURCE and "0o600" in SOURCE and "0o700" in SOURCE
    assert 'startswith("/tmp/b64-")' in SOURCE
    assert "archive.unlink" in SOURCE
    assert "stderr.decode" not in SOURCE and "str(exc)" not in SOURCE
    assert '"containsProductionData": True' in SOURCE


def test_comparator_emits_only_table_names_not_rows():
    source = (ROOT / "deploy/postgres/b64_compare_table_fingerprints.py").read_text()
    assert "differentTables" in source and "restoredSha256" in source
    assert "print(source" not in source and "print(restored" not in source


def test_catalog_comparator_separates_database_local_and_cluster_global():
    source = (ROOT / "deploy/postgres/b64_compare_catalog_fingerprints.py").read_text()
    assert 'CLUSTER_GLOBAL = {"membership", "db_role_setting"}' in source
    assert "differentDatabaseLocalSections" in source
    assert "differentClusterGlobalSections" in source
    assert '"sequenceStateCompared": False' in source
    assert "rolpassword" not in source and "last_value" not in source


def test_catalog_query_cannot_commit_exported_snapshot_and_canonicalizes_internal_triggers():
    catalog = (ROOT / "deploy/postgres/b64_catalog_security_fingerprint.sql").read_text()
    assert "BEGIN TRANSACTION" not in catalog and "COMMIT;" not in catalog
    assert "CASE WHEN t.tgisinternal THEN NULL ELSE t.tgname END" in catalog
    assert "constraintRelation" in catalog and "typeBits" in catalog
    assert "CASE WHEN t.tgisinternal THEN NULL ELSE pg_catalog.pg_get_triggerdef" in catalog
