-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- P5A: three atomic claims and two bounded provider poll projections.

GRANT SELECT(id,kind,state,order_id,session_token,provider,provider_invoice_id,user_id,
 currency,rub_amount,order_status,has_receipt,detail,attempts,created_at,claimed_at,
 completed_at,updated_at) ON public.order_lifecycle_work TO obsidian_relay_owner;
GRANT UPDATE(state,attempts,claimed_at,updated_at)
 ON public.order_lifecycle_work TO obsidian_relay_owner;
GRANT SELECT(id,session_token,provider_invoice_id,order_id,provider,status,created_at)
 ON public.payment_sessions TO obsidian_relay_owner;
GRANT SELECT(order_id,status) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(id,order_id,recipient_id,payload,state,attempts)
 ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT UPDATE(state,attempts,claimed_at,updated_at)
 ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT SELECT(id,user_id,rub_amount,payout_ref,payout_status,payout_provider,updated_at)
 ON public.sell_orders TO obsidian_relay_owner;
GRANT SELECT(id,sell_id,recipient_id,rub_amount,state,attempts)
 ON public.sell_settlement_outbox TO obsidian_relay_owner;
GRANT UPDATE(state,attempts,claimed_at,updated_at)
 ON public.sell_settlement_outbox TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_lifecycle_claim_work(p_kind text)
RETURNS TABLE(id bigint,kind text,order_id bigint,session_token text,provider text,
 provider_invoice_id text,user_id bigint,currency text,rub_amount numeric(20,2),
 order_status text,has_receipt boolean,detail text,state text,attempts integer,
 created_at timestamptz,claimed_at timestamptz,completed_at timestamptz,
 updated_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_kind IS NOT NULL AND p_kind NOT IN ('order_expired_notify','session_dead_admin',
   'session_dead_customer','provider_cancel') THEN RAISE EXCEPTION 'invalid_work_kind'; END IF;
 RETURN QUERY WITH candidate AS (
  SELECT w.id FROM public.order_lifecycle_work w WHERE w.state='pending'
   AND (p_kind IS NULL OR w.kind=p_kind) ORDER BY w.id FOR UPDATE SKIP LOCKED LIMIT 1)
 UPDATE public.order_lifecycle_work w SET state='sending',attempts=w.attempts+1,
  claimed_at=clock_timestamp(),updated_at=clock_timestamp()
 FROM candidate c WHERE w.id=c.id AND w.state='pending'
 RETURNING w.id,w.kind,w.order_id,w.session_token,w.provider,w.provider_invoice_id,
  w.user_id,w.currency,w.rub_amount,w.order_status,w.has_receipt,w.detail,w.state,
  w.attempts,w.created_at,w.claimed_at,w.completed_at,w.updated_at;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_pending_vertu()
RETURNS TABLE(session_token text,provider_invoice_id text,order_id bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT ps.session_token,ps.provider_invoice_id,ps.order_id
 FROM public.payment_sessions ps JOIN public.orders o ON o.order_id=ps.order_id
 WHERE ps.provider='vertu' AND ps.status='invoice_created'
  AND ps.provider_invoice_id IS NOT NULL AND o.status='pending'
  AND ps.created_at>CURRENT_TIMESTAMP-interval '2 hours'
 ORDER BY ps.id LIMIT 100
$$;

CREATE OR REPLACE FUNCTION public.relay_payment_claim_notification()
RETURNS TABLE(id bigint,order_id bigint,recipient_id bigint,payload jsonb,attempts integer)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 WITH candidate AS (SELECT o.id FROM public.payment_notification_outbox o
  WHERE o.state='pending' ORDER BY o.id FOR UPDATE SKIP LOCKED LIMIT 1)
 UPDATE public.payment_notification_outbox o SET state='sending',attempts=o.attempts+1,
  claimed_at=clock_timestamp(),updated_at=clock_timestamp()
 FROM candidate c WHERE o.id=c.id AND o.state='pending'
 RETURNING o.id,o.order_id,o.recipient_id,o.payload,o.attempts
$$;

CREATE OR REPLACE FUNCTION public.relay_sell_active_vertu_payouts(
 p_terminal_statuses text[],p_newer_than_days smallint)
RETURNS TABLE(id bigint,user_id bigint,rub_amount numeric(20,2),payout_ref text,
 payout_status text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_terminal_statuses IS NULL OR cardinality(p_terminal_statuses)<1
    OR cardinality(p_terminal_statuses)>4 OR p_newer_than_days IS NULL
    OR p_newer_than_days<1 OR p_newer_than_days>30
    OR EXISTS(SELECT 1 FROM unnest(p_terminal_statuses) s
              WHERE s IS NULL OR lower(trim(s)) NOT IN ('paid','failed','declined','revoked')) THEN
  RAISE EXCEPTION 'invalid_vertu_poll_filter';
 END IF;
 RETURN QUERY SELECT s.id,s.user_id,s.rub_amount,s.payout_ref,s.payout_status
 FROM public.sell_orders s WHERE s.payout_provider='vertu'
  AND COALESCE(s.payout_ref,'')<>''
  AND (s.payout_status IS NULL OR NOT EXISTS(SELECT 1
       FROM unnest(p_terminal_statuses) terminal
       WHERE lower(s.payout_status)=lower(trim(terminal))))
  AND s.updated_at>CURRENT_TIMESTAMP-(p_newer_than_days*interval '1 day')
 ORDER BY s.id LIMIT 100;
END $$;

CREATE OR REPLACE FUNCTION public.relay_sell_claim_notification()
RETURNS TABLE(id bigint,sell_id bigint,recipient_id bigint,rub_amount numeric(20,2),
 attempts integer)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 WITH candidate AS (SELECT o.id FROM public.sell_settlement_outbox o
  WHERE o.state='pending' ORDER BY o.id FOR UPDATE SKIP LOCKED LIMIT 1)
 UPDATE public.sell_settlement_outbox o SET state='sending',attempts=o.attempts+1,
  claimed_at=clock_timestamp(),updated_at=clock_timestamp()
 FROM candidate c WHERE o.id=c.id AND o.state='pending'
 RETURNING o.id,o.sell_id,o.recipient_id,o.rub_amount,o.attempts
$$;

ALTER FUNCTION public.relay_lifecycle_claim_work(text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_pending_vertu() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_claim_notification() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_active_vertu_payouts(text[],smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_claim_notification() OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_lifecycle_claim_work(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_pending_vertu() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_claim_notification() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_sell_active_vertu_payouts(text[],smallint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_sell_claim_notification() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_lifecycle_claim_work(text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_pending_vertu() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_claim_notification() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_sell_active_vertu_payouts(text[],smallint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_sell_claim_notification() TO obsidian_relay;
