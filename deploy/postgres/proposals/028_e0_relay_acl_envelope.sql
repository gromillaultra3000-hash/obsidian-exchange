-- E0.3 PROPOSAL ONLY. Run only in a disposable PostgreSQL 17 database.
-- This rehearses the Relay role/ambient-privilege envelope with representative
-- read, outbox, creation and money-transition functions. It is not a production
-- migration and does not claim that all 43 read / 26 writer bodies are complete.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='obsidian_relay_owner') THEN
    CREATE ROLE obsidian_relay_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='obsidian_relay') THEN
    CREATE ROLE obsidian_relay LOGIN PASSWORD 'synthetic-rehearsal-only'
      CONNECTION LIMIT 12 NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
      NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;

ALTER ROLE obsidian_relay_owner NOLOGIN PASSWORD NULL NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE obsidian_relay LOGIN PASSWORD 'synthetic-rehearsal-only'
  CONNECTION LIMIT 12 NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
  NOREPLICATION NOBYPASSRLS;
ALTER ROLE obsidian_relay SET statement_timeout='5s';
ALTER ROLE obsidian_relay SET lock_timeout='1s';

DO $$ BEGIN
  EXECUTE format('REVOKE CONNECT,TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM obsidian_relay',current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO obsidian_relay',current_database());
END $$;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM obsidian_relay,obsidian_relay_owner;
GRANT USAGE ON SCHEMA public TO obsidian_relay,obsidian_relay_owner;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC,obsidian_relay,obsidian_relay_owner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC,obsidian_relay,obsidian_relay_owner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC,obsidian_relay,obsidian_relay_owner;

GRANT SELECT(order_id,user_id,status,rub_amount) ON public.orders TO obsidian_relay_owner;
GRANT UPDATE(status,updated_at) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(id,order_id,recipient_id,payload,state,attempts) ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT UPDATE(state,attempts,claimed_at,updated_at) ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT INSERT(ticket_id,web_user_id,subject,status) ON public.support_tickets TO obsidian_relay_owner;
GRANT SELECT(ticket_id) ON public.support_tickets TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.support_tickets_ticket_id_seq TO obsidian_relay_owner;
GRANT INSERT(order_id,from_status,to_status,evidence) ON public.payment_transition_audit TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.payment_transition_audit_id_seq TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_rehearsal_public_stats()
RETURNS TABLE(total bigint,paid bigint,volume numeric)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
  SELECT count(o.order_id),count(o.order_id) FILTER(WHERE o.status='paid'),
         COALESCE(sum(o.rub_amount) FILTER(WHERE o.status='paid'),0)
  FROM public.orders o
$$;

CREATE OR REPLACE FUNCTION public.relay_rehearsal_customer_orders(p_user_id bigint,p_limit smallint)
RETURNS TABLE(order_id bigint,status text,rub_amount numeric)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF p_user_id<=0 OR p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_customer_read'; END IF;
  RETURN QUERY SELECT o.order_id,o.status,o.rub_amount FROM public.orders o
    WHERE o.user_id=p_user_id ORDER BY o.order_id DESC LIMIT p_limit;
END $$;

CREATE OR REPLACE FUNCTION public.relay_rehearsal_claim_notification()
RETURNS TABLE(id bigint,order_id bigint,recipient_id bigint,payload jsonb,attempts integer)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
  WITH candidate AS (
    SELECT o.id FROM public.payment_notification_outbox o WHERE o.state='pending'
    ORDER BY o.id FOR UPDATE SKIP LOCKED LIMIT 1
  )
  UPDATE public.payment_notification_outbox o SET state='sending',
    attempts=o.attempts+1,claimed_at=clock_timestamp(),updated_at=clock_timestamp()
  FROM candidate c WHERE o.id=c.id
  RETURNING o.id,o.order_id,o.recipient_id,o.payload,o.attempts
$$;

CREATE OR REPLACE FUNCTION public.relay_rehearsal_support_create(
  p_web_user_id bigint,p_subject text)
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE result bigint;
BEGIN
  IF p_web_user_id<=0 OR length(trim(p_subject))<1 OR length(p_subject)>200 THEN
    RAISE EXCEPTION 'invalid_support_create';
  END IF;
  INSERT INTO public.support_tickets(web_user_id,subject,status)
    VALUES(p_web_user_id,trim(p_subject),'open') RETURNING ticket_id INTO result;
  RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.relay_rehearsal_mark_paid(
  p_order_id bigint,p_evidence text)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE current_status text;
BEGIN
  IF p_order_id<=0 OR length(trim(p_evidence))<1 OR length(p_evidence)>160 THEN
    RAISE EXCEPTION 'invalid_payment_transition';
  END IF;
  SELECT o.status INTO current_status FROM public.orders o
    WHERE o.order_id=p_order_id FOR UPDATE;
  IF NOT FOUND THEN RETURN 'missing'; END IF;
  IF current_status='paid' THEN RETURN 'already_paid'; END IF;
  IF current_status<>'pending' THEN RETURN 'status_conflict'; END IF;
  UPDATE public.orders SET status='paid',updated_at=clock_timestamp()
    WHERE order_id=p_order_id AND status='pending';
  IF NOT FOUND THEN RAISE EXCEPTION 'payment_transition_lost'; END IF;
  INSERT INTO public.payment_transition_audit(order_id,from_status,to_status,evidence)
    VALUES(p_order_id,'pending','paid',p_evidence);
  RETURN 'transitioned';
END $$;

ALTER FUNCTION public.relay_rehearsal_public_stats() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_rehearsal_customer_orders(bigint,smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_rehearsal_claim_notification() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_rehearsal_support_create(bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_rehearsal_mark_paid(bigint,text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_rehearsal_public_stats() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_rehearsal_customer_orders(bigint,smallint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_rehearsal_claim_notification() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_rehearsal_support_create(bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_rehearsal_mark_paid(bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_rehearsal_public_stats() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_rehearsal_customer_orders(bigint,smallint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_rehearsal_claim_notification() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_rehearsal_support_create(bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_rehearsal_mark_paid(bigint,text) TO obsidian_relay;

DO $$
DECLARE unexpected bigint;
BEGIN
  SELECT count(*) INTO unexpected FROM pg_auth_members m
    WHERE m.roleid=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay')
       OR m.member=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay')
       OR m.roleid=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_owner')
       OR m.member=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_owner');
  IF unexpected<>0 THEN RAISE EXCEPTION 'relay_role_membership_present'; END IF;
  IF has_database_privilege('obsidian_relay',current_database(),'TEMPORARY')
     OR has_schema_privilege('obsidian_relay','public','CREATE') THEN
    RAISE EXCEPTION 'relay_ambient_create_privilege';
  END IF;
END $$;
