import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))

from load_sqlite_snapshot import (
    DORMANT_MIGRATION_TABLE_ORDER,
    MIGRATION_COMPLETE_TABLE_ORDER,
    PRODUCTION_TABLE_ORDER,
    TABLE_ORDER,
)
from migration_profile import selected_paths
from verify_runtime_privileges import (
    EXPECTED_SEQUENCES,
    PAYOUT_FUNCTIONS,
    READONLY_TABLES,
)


production_paths = selected_paths(ROOT, "production-cutover")
dormant_paths = selected_paths(ROOT, "post-cutover-dormant")
migration_paths = selected_paths(ROOT, "repository-complete")


def joined(paths):
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


def created_tables(source):
    return set(re.findall(
        r"\bCREATE\s+TABLE\s+([a-z][a-z0-9_]*)\s*\(", source, re.I
    ))


def created_serials(source):
    return {
        f"{table}_{column}_seq"
        for table, body in re.findall(
            r"\bCREATE\s+TABLE\s+([a-z][a-z0-9_]*)\s*\((.*?);",
            source,
            re.I | re.S,
        )
        for column in re.findall(
            r"\b([a-z][a-z0-9_]*)\s+BIGSERIAL\b", body, re.I
        )
    }


def created_function_names(source):
    return set(re.findall(
        r"\bCREATE\s+OR\s+REPLACE\s+FUNCTION\s+"
        r"([a-z][a-z0-9_]*)\s*\(",
        source,
        re.I,
    ))


production_migrations = joined(production_paths)
dormant_migrations = joined(dormant_paths)
all_migrations = joined(migration_paths)
production_tables = created_tables(production_migrations)
all_tables = created_tables(all_migrations)
production_serials = created_serials(production_migrations)
all_serials = created_serials(all_migrations)
production_functions = created_function_names(production_migrations)
dormant_functions = created_function_names(dormant_migrations)

assert TABLE_ORDER is PRODUCTION_TABLE_ORDER
assert production_tables == set(PRODUCTION_TABLE_ORDER)
assert all_tables == set(MIGRATION_COMPLETE_TABLE_ORDER)
assert all_tables - production_tables == set(DORMANT_MIGRATION_TABLE_ORDER)
assert len(production_tables) == 54
assert len(all_tables) == 56
assert production_serials == EXPECTED_SEQUENCES
assert all_serials == EXPECTED_SEQUENCES
assert production_functions == {name.removesuffix("()") for name in PAYOUT_FUNCTIONS}
assert dormant_functions == {
    "e3_append_paper_evidence",
    "e3_reject_evidence_mutation",
}
assert READONLY_TABLES == production_tables

privileges = (ROOT / "deploy/postgres/runtime_privileges.sql").read_text("utf-8")
bootstrap = (ROOT / "deploy/postgres/bootstrap_roles.sql").read_text("utf-8")
for role in ("obsidian_migrator", "obsidian_app", "obsidian_readonly", "obsidian_payout"):
    assert role in privileges
    assert role in bootstrap
assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in privileges
assert "runtime privilege matrix requires exact 001-023 table inventory" \
    in privileges
assert "runtime privilege matrix requires exact 001-023 sequence inventory" \
    in privileges
assert "runtime privilege matrix requires exact 001-023 function inventory" \
    in privileges
assert "GRANT EXECUTE ON ALL FUNCTIONS" not in privileges
assert "TO obsidian_readonly" in privileges
assert "TO obsidian_payout" in privileges
assert "PASSWORD" not in bootstrap.upper().replace("PASSWORDS ARE DELIBERATELY", "")
assert re.search(
    r"ALTER\s+DEFAULT\s+PRIVILEGES\s+FOR\s+ROLE\s+obsidian_migrator\s+"
    r"REVOKE\s+EXECUTE\s+ON\s+FUNCTIONS\s+FROM\s+PUBLIC",
    privileges,
    re.I | re.S,
)
assert not re.search(
    r"ALTER\s+DEFAULT\s+PRIVILEGES\s+FOR\s+ROLE\s+obsidian_migrator\s+"
    r"IN\s+SCHEMA\s+public\s+REVOKE\s+EXECUTE",
    privileges,
    re.I | re.S,
)
assert "REVOKE ALL ON FUNCTION e3_reject_evidence_mutation() FROM PUBLIC" \
    in dormant_migrations
assert "REVOKE ALL ON FUNCTION e3_append_paper_evidence(" in dormant_migrations
for wrapper_name in ("container_pg_dump.sh", "container_pg_restore.sh"):
    wrapper = ROOT / "deploy/postgres" / wrapper_name
    source = wrapper.read_text("utf-8")
    assert os.access(wrapper, os.X_OK), wrapper
    assert "PGPASSWORD" not in source
    assert "obsidian-postgres" in source

print(
    f"PostgreSQL privilege inventory: {len(production_tables)} production / "
    f"{len(all_tables)} migration-complete tables, "
    f"{len(all_serials)} sequences, "
    f"{len(production_functions | dormant_functions)} functions: OK"
)
