from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "deploy/postgres/b64_acl_fingerprint.sql").read_text()


def test_acl_fingerprint_is_read_only_identifier_free_and_sha256():
    for mutation in ("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "CREATE ", "DROP "):
        assert mutation not in SQL
    assert "aclexplode" in SQL and "acldefault" in SQL
    assert "sha256" in SQL and "rolpassword" not in SQL
    assert "current_database()" in SQL


def test_acl_fingerprint_covers_owners_public_and_runtime_role_attributes():
    for value in ("relation|", "function|", "schema|public", "database|owner=",
                  "obsidian_migrator", "obsidian_app", "obsidian_readonly", "obsidian_payout",
                  "rolsuper", "rolbypassrls", "rolconnlimit", "rolconfig"):
        assert value in SQL


def test_table_fingerprint_never_emits_rows_and_is_deterministic():
    source = (ROOT / "deploy/postgres/b64_table_fingerprint.sql").read_text()
    assert "count(*)" in source and "sha256" in source
    assert "ORDER BY to_jsonb(t)::text" in source
    assert "SELECT *" not in source
    assert "\\gexec" in source
