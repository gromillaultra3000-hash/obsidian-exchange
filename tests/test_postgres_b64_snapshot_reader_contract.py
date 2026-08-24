import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

from load_sqlite_snapshot import PRODUCTION_TABLE_ORDER
from verify_b64_snapshot_reader import (
    EXPECTED_SETTINGS,
    ROLE,
    SEQUENCE_PRIVILEGES,
    TABLE_PRIVILEGES,
)
from verify_runtime_privileges import EXPECTED_SEQUENCES


PROVISION = (POSTGRES / "provision_b64_snapshot_reader.sql").read_text("utf-8")
ROLLBACK = (POSTGRES / "rollback_b64_snapshot_reader.sql").read_text("utf-8")
DEPLOY_RUNNER = (POSTGRES / "deploy_b64_snapshot_reader.py").read_text("utf-8")


def _array(name: str) -> set[str]:
    match = re.search(
        rf"{name}\s+text\[\]\s*:=\s*ARRAY\[(.*?)\];",
        PROVISION,
        re.I | re.S,
    )
    assert match is not None
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_provisioning_is_bound_to_the_frozen_001_023_inventory():
    assert _array("expected_tables") == set(PRODUCTION_TABLE_ORDER)
    assert _array("expected_sequences") == EXPECTED_SEQUENCES
    assert _array("expected_functions") == {
        "claim_next_order_payout()",
        "claim_next_referral_payout()",
    }
    assert len(_array("expected_tables")) == 54
    assert len(_array("expected_sequences")) == 29
    assert "unexpected public relations" in PROVISION
    assert "refuses row-level security tables" in PROVISION
    assert "refuses databases with large objects" in PROVISION


def test_role_contract_is_login_non_inheriting_bounded_and_secret_free():
    normalized = re.sub(r"\s+", " ", PROVISION.upper())
    executable = re.sub(r"--[^\n]*", "", PROVISION.upper())
    assert ROLE.upper() in normalized
    assert "NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE" in normalized
    assert "NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 2" in normalized
    assert " PASSWORD " not in f" {executable} "
    assert EXPECTED_SETTINGS == {
        "search_path": "pg_catalog",
        "default_transaction_read_only": "on",
        "default_transaction_isolation": "repeatable read",
        "statement_timeout": "180s",
        "lock_timeout": "5s",
        "idle_in_transaction_session_timeout": "210s",
        "row_security": "off",
    }


def test_acl_is_exact_read_only_and_sequence_state_is_not_mutable():
    normalized = re.sub(r"\s+", " ", PROVISION.upper())
    assert "GRANT SELECT ON TABLE " in normalized
    assert "GRANT SELECT ON SEQUENCE " in normalized
    assert "GRANT USAGE ON SEQUENCE" not in normalized
    assert "GRANT UPDATE ON SEQUENCE" not in normalized
    assert TABLE_PRIVILEGES == (
        "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
        "REFERENCES", "TRIGGER", "MAINTAIN",
    )
    assert SEQUENCE_PRIVILEGES == ("SELECT", "USAGE", "UPDATE")
    assert "REVOKE ALL ON ALL FUNCTIONS IN SCHEMA PUBLIC" in normalized
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA %I" in normalized
    assert "REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I" in normalized
    assert "REVOKE ALL (%S) ON TABLE %I.%I" in normalized
    assert "PG_SHDEPEND" in normalized
    assert "PG_DB_ROLE_SETTING" in normalized
    assert "PRE-EXISTING CREDENTIAL STATE" in normalized


def test_rollback_is_transactional_scoped_and_fail_closed():
    normalized = re.sub(r"\s+", " ", ROLLBACK.upper())
    assert normalized.startswith("-- TRANSACTIONAL ROLLBACK")
    assert "BEGIN;" in normalized and normalized.rstrip().endswith("COMMIT;")
    assert "REFUSING ROLLBACK OF ELEVATED SNAPSHOT READER ROLE" in normalized
    assert "REFUSING ROLLBACK WITH SNAPSHOT READER MEMBERSHIP" in normalized
    assert "DROP ROLE OBSIDIAN_B64_SNAPSHOT_READER" in normalized
    assert "DROP OWNED" not in normalized


def test_deployment_runner_binds_identity_bytes_and_auto_rollback():
    assert "ARTIFACT_DIGEST_MISMATCH" in DEPLOY_RUNNER
    assert "CONTAINER_IDENTITY_MISMATCH" in DEPLOY_RUNNER
    assert "DSN_CONTAINER_PORT_BINDING_MISMATCH" in DEPLOY_RUNNER
    assert "ADMIN_AUTHORITY_INSUFFICIENT" in DEPLOY_RUNNER
    assert "ADMIN_DSN_CREDENTIAL_FORBIDDEN" in DEPLOY_RUNNER
    assert "AMBIENT_LIBPQ_ENV_FORBIDDEN" in DEPLOY_RUNNER
    assert "ADMIN_POSTGRES_ENV_REQUIRED_FOR_APPLY" in DEPLOY_RUNNER
    assert "EMPTY_MEMFD" in DEPLOY_RUNNER
    assert "inet_client_addr() IS NULL" in DEPLOY_RUNNER
    assert "BOUND_CONTAINER_UNIX_SOCKET" in DEPLOY_RUNNER
    assert "ROLE_ALREADY_EXISTS" in DEPLOY_RUNNER
    assert "require_absent=True" in DEPLOY_RUNNER
    assert "POST_APPLY_VERIFICATION_FAILED" in DEPLOY_RUNNER
    assert "rollbackAttempted" in DEPLOY_RUNNER
    assert "rollbackVerified" in DEPLOY_RUNNER
    assert "adminCredentialLogged\": False" in DEPLOY_RUNNER
    assert "customer" not in DEPLOY_RUNNER.lower()
