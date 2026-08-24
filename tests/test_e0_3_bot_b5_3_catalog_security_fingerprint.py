from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/postgres/b64_catalog_security_fingerprint.sql").read_text()


def test_expanded_fingerprint_covers_every_deferred_security_class():
    for section in (
        "column_acl", "default_acl", "membership", "db_role_setting",
        "relation_security", "constraint_security", "index_security",
        "trigger_security", "function_security", "policy_security",
        "sequence_definition", "type_security", "extension_security",
    ):
        assert f"'{section}'" in SQL


def test_fingerprint_uses_stable_names_and_security_attributes_not_secrets():
    for value in (
        "attacl", "pg_default_acl", "admin_option", "inherit_option", "set_option",
        "pg_db_role_setting", "relrowsecurity", "relforcerowsecurity", "relreplident",
        "convalidated", "indisvalid", "tgenabled", "prosecdef", "proconfig",
        "proleakproof", "proparallel", "polroles", "pg_sequence", "pg_enum",
    ):
        assert value in SQL
    assert "rolpassword" not in SQL and "last_value" not in SQL
    assert "sha256" in SQL and "jsonb_agg(e.item ORDER BY e.item)" in SQL
    assert "b64-catalog-security-fingerprint.v2" in SQL
    assert "::regclass" in SQL  # comparisons only; no OID is serialized


def test_every_entry_is_structured_and_known_false_matches_are_covered():
    assert "||'|'||" not in SQL and "array_to_string" not in SQL
    for value in (
        "typacl", "tgisinternal", "contypid", "ownedBy", "extowner",
        "aclIsNull", "setrole=0", "IN('f','p')",
    ):
        assert value in SQL


def test_fingerprint_is_read_only():
    for mutation in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "CREATE ", "DROP ", "GRANT ", "REVOKE "):
        assert mutation not in SQL
