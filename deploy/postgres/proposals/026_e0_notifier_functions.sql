-- E0.3 PROPOSAL ONLY. Rehearse on a disposable PostgreSQL 17 database.
-- Production application requires a separately authorized migration/rollback.
BEGIN;

DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obsidian_notifier_owner') THEN
    CREATE ROLE obsidian_notifier_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'obsidian_notifier') THEN
    CREATE ROLE obsidian_notifier NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
END
$roles$;

CREATE OR REPLACE FUNCTION public.notifier_pending(p_event text, p_max_rows integer)
RETURNS TABLE(order_id bigint,user_id bigint,rub_amount numeric,currency text,paid_btc_tx text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
BEGIN
  IF p_event IS NULL OR p_event NOT IN ('paid','sent') THEN
    RAISE EXCEPTION 'invalid_notification_event' USING ERRCODE = '22023';
  END IF;
  IF p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 100 THEN
    RAISE EXCEPTION 'invalid_notification_limit' USING ERRCODE = '22023';
  END IF;
  RETURN QUERY
    SELECT o.order_id,o.user_id,o.rub_amount,o.currency,o.paid_btc_tx
      FROM public.orders AS o
     WHERE o.status=p_event
       AND NOT EXISTS(
         SELECT 1 FROM public.sent_notifications AS sn
          WHERE sn.order_id=o.order_id AND sn.event=p_event)
     ORDER BY o.order_id LIMIT p_max_rows;
END
$fn$;

CREATE OR REPLACE FUNCTION public.notifier_complete(p_order_id bigint,p_event text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE affected integer;
BEGIN
  IF p_event IS NULL OR p_event NOT IN ('paid','sent') THEN
    RAISE EXCEPTION 'invalid_notification_event' USING ERRCODE = '22023';
  END IF;
  IF p_order_id IS NULL OR p_order_id < 1 OR NOT EXISTS (SELECT 1 FROM public.orders WHERE order_id=p_order_id AND status=p_event) THEN
    RAISE EXCEPTION 'notification_order_state_mismatch' USING ERRCODE = '23514';
  END IF;
  INSERT INTO public.sent_notifications(order_id,event) VALUES(p_order_id,p_event)
    ON CONFLICT(order_id,event) DO NOTHING;
  GET DIAGNOSTICS affected = ROW_COUNT;
  IF p_event='paid' THEN
    UPDATE public.gift_vouchers SET status='paid'
     WHERE order_id=p_order_id AND status='pending';
  END IF;
  RETURN affected = 1;
END
$fn$;

CREATE OR REPLACE FUNCTION public.notifier_ensure_review(p_order_id bigint,p_user_id bigint)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog
AS $fn$
DECLARE affected integer;
BEGIN
  IF p_order_id IS NULL OR p_order_id < 1 OR p_user_id IS NULL OR p_user_id < 1 OR NOT EXISTS (
    SELECT 1 FROM public.orders
     WHERE order_id=p_order_id AND user_id=p_user_id AND status='sent'
  ) THEN
    RAISE EXCEPTION 'review_order_owner_or_state_mismatch' USING ERRCODE = '23514';
  END IF;
  IF EXISTS (SELECT 1 FROM public.reviews WHERE order_id=p_order_id
             AND (user_id<>p_user_id OR status<>'pending_rating')) THEN
    RAISE EXCEPTION 'review_binding_conflict' USING ERRCODE = '23514';
  END IF;
  INSERT INTO public.reviews(order_id,user_id,status)
    VALUES(p_order_id,p_user_id,'pending_rating')
    ON CONFLICT(order_id) DO NOTHING;
  GET DIAGNOSTICS affected = ROW_COUNT;
  RETURN affected = 1;
END
$fn$;

ALTER FUNCTION public.notifier_pending(text,integer) OWNER TO obsidian_notifier_owner;
ALTER FUNCTION public.notifier_complete(bigint,text) OWNER TO obsidian_notifier_owner;
ALTER FUNCTION public.notifier_ensure_review(bigint,bigint) OWNER TO obsidian_notifier_owner;

REVOKE ALL ON FUNCTION public.notifier_pending(text,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notifier_complete(bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.notifier_ensure_review(bigint,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.notifier_pending(text,integer) TO obsidian_notifier;
GRANT EXECUTE ON FUNCTION public.notifier_complete(bigint,text) TO obsidian_notifier;
GRANT EXECUTE ON FUNCTION public.notifier_ensure_review(bigint,bigint) TO obsidian_notifier;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM obsidian_notifier;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM obsidian_notifier;
REVOKE CREATE ON SCHEMA public FROM obsidian_notifier;
DO $acl$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM obsidian_notifier',current_database());
END
$acl$;

GRANT SELECT ON public.orders,public.sent_notifications,public.reviews
  TO obsidian_notifier_owner;
GRANT SELECT(order_id,status) ON public.gift_vouchers TO obsidian_notifier_owner;
GRANT INSERT ON public.sent_notifications,public.reviews TO obsidian_notifier_owner;
GRANT UPDATE(status) ON public.gift_vouchers TO obsidian_notifier_owner;
GRANT USAGE,SELECT ON SEQUENCE public.reviews_id_seq TO obsidian_notifier_owner;

COMMIT;
