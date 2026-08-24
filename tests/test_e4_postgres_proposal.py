from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "deploy/postgres/proposals/025_e4_action_handoff.sql").read_text()
ACL = (ROOT / "deploy/postgres/proposals/025_e4_action_handoff_acl.sql").read_text()


def test_proposal_is_outside_active_migration_sequence_and_fail_closed():
    assert "PROPOSAL ONLY" in MIGRATION
    assert "CREATE TABLE e4_action_reservations" in MIGRATION
    assert "BEFORE UPDATE OR DELETE" in MIGRATION
    assert "OLD.state<>'reserved' OR NEW.state<>'committed'" in MIGRATION
    assert "missing e4 buy result" in MIGRATION and "missing e4 sell result" in MIGRATION
    assert not (ROOT / "deploy/postgres/025_e4_action_handoff.sql").exists()


def test_acl_is_narrow_and_must_follow_base_acl():
    assert "apply after the base runtime ACL file" in ACL
    assert "GRANT SELECT,INSERT ON TABLE e4_action_reservations TO obsidian_app" in ACL
    assert "GRANT UPDATE(state,result_kind,result_id)" in ACL
    assert "obsidian_readonly" in ACL and "obsidian_payout" in ACL
    for forbidden in ("GRANT DELETE", "GRANT TRUNCATE", "GRANT ALL"):
        assert forbidden not in ACL
