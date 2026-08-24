-- PROPOSAL ONLY: do not apply until E4 production gate approval.
CREATE TABLE e4_action_reservations(
 reservation_id TEXT PRIMARY KEY,
 request_id TEXT NOT NULL UNIQUE,
 draft_id TEXT NOT NULL UNIQUE,
 assessment_id TEXT NOT NULL,
 principal_ref TEXT NOT NULL,
 actor_user_id BIGINT NOT NULL CHECK(actor_user_id>0),
 idempotency_key_sha256 TEXT NOT NULL CHECK(length(idempotency_key_sha256)=64),
 workflow_mapping TEXT NOT NULL CHECK(workflow_mapping IN
  ('BUY_ORDER_CREATION','SELL_ORDER_CREATION')),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 quote_expires_at_epoch_ms BIGINT NOT NULL,
 requested_at_epoch_ms BIGINT NOT NULL CHECK(requested_at_epoch_ms>0),
 expires_at_epoch_ms BIGINT NOT NULL CHECK(
  expires_at_epoch_ms>requested_at_epoch_ms
  AND expires_at_epoch_ms<=quote_expires_at_epoch_ms),
 state TEXT NOT NULL CHECK(state IN('reserved','committed')),
 result_kind TEXT CHECK(result_kind IN('BUY_ORDER','SELL_ORDER')),
 result_id BIGINT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(principal_ref,idempotency_key_sha256),
 CHECK((state='reserved' AND result_kind IS NULL AND result_id IS NULL)
    OR (state='committed' AND result_kind IS NOT NULL AND result_id>0)),
 CHECK((workflow_mapping='BUY_ORDER_CREATION' AND
        (result_kind IS NULL OR result_kind='BUY_ORDER'))
    OR (workflow_mapping='SELL_ORDER_CREATION' AND
        (result_kind IS NULL OR result_kind='SELL_ORDER')))
);

CREATE FUNCTION e4_guard_action_reservation_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'e4 action reservations cannot be deleted';
 END IF;
 IF OLD.state<>'reserved' OR NEW.state<>'committed' THEN
  RAISE EXCEPTION 'invalid e4 reservation transition';
 END IF;
 IF ROW(NEW.reservation_id,NEW.request_id,NEW.draft_id,NEW.assessment_id,
        NEW.principal_ref,NEW.actor_user_id,NEW.idempotency_key_sha256,
        NEW.workflow_mapping,NEW.payload_sha256,NEW.quote_expires_at_epoch_ms,
        NEW.requested_at_epoch_ms,NEW.expires_at_epoch_ms,NEW.created_at)
    IS DISTINCT FROM
    ROW(OLD.reservation_id,OLD.request_id,OLD.draft_id,OLD.assessment_id,
        OLD.principal_ref,OLD.actor_user_id,OLD.idempotency_key_sha256,
        OLD.workflow_mapping,OLD.payload_sha256,OLD.quote_expires_at_epoch_ms,
        OLD.requested_at_epoch_ms,OLD.expires_at_epoch_ms,OLD.created_at) THEN
  RAISE EXCEPTION 'immutable e4 reservation fields changed';
 END IF;
 IF NEW.result_kind='BUY_ORDER' AND NOT EXISTS(
      SELECT 1 FROM orders WHERE order_id=NEW.result_id) THEN
  RAISE EXCEPTION 'missing e4 buy result';
 END IF;
 IF NEW.result_kind='SELL_ORDER' AND NOT EXISTS(
      SELECT 1 FROM sell_orders WHERE id=NEW.result_id) THEN
  RAISE EXCEPTION 'missing e4 sell result';
 END IF;
 RETURN NEW;
END$$;

CREATE TRIGGER e4_action_reservations_guard
BEFORE UPDATE OR DELETE ON e4_action_reservations
FOR EACH ROW EXECUTE FUNCTION e4_guard_action_reservation_mutation();

REVOKE ALL ON e4_action_reservations FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION e4_guard_action_reservation_mutation() FROM PUBLIC;
