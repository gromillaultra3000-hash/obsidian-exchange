-- PROPOSAL ONLY: apply after the base runtime ACL file, never by itself.
BEGIN;
REVOKE ALL ON TABLE e4_action_reservations
 FROM PUBLIC,obsidian_app,obsidian_readonly,obsidian_payout;
GRANT SELECT,INSERT ON TABLE e4_action_reservations TO obsidian_app;
GRANT UPDATE(state,result_kind,result_id)
 ON TABLE e4_action_reservations TO obsidian_app;
REVOKE EXECUTE ON FUNCTION e4_guard_action_reservation_mutation()
 FROM PUBLIC,obsidian_app,obsidian_readonly,obsidian_payout;
COMMIT;
