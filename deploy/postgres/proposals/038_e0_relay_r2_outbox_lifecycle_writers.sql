-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- R2: atomic claims and exact sending-state completion/retry transitions.

GRANT SELECT(id,kind,state,order_id,session_token,provider,provider_invoice_id,user_id,
 currency,rub_amount,order_status,has_receipt,detail,attempts,created_at,claimed_at,
 completed_at,updated_at) ON public.order_lifecycle_work TO obsidian_relay_owner;
GRANT UPDATE(state,attempts,claimed_at,completed_at,updated_at)
 ON public.order_lifecycle_work TO obsidian_relay_owner;
GRANT SELECT(id,state,order_id,recipient_id,payload,attempts)
 ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT UPDATE(state,attempts,claimed_at,sent_at,updated_at)
 ON public.payment_notification_outbox TO obsidian_relay_owner;
GRANT SELECT(id,state,sell_id,recipient_id,rub_amount,attempts)
 ON public.sell_settlement_outbox TO obsidian_relay_owner;
GRANT UPDATE(state,attempts,claimed_at,sent_at,updated_at)
 ON public.sell_settlement_outbox TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_lifecycle_claim_work(p_kind text)
RETURNS TABLE(id bigint,kind text,order_id bigint,session_token text,provider text,
 provider_invoice_id text,user_id bigint,currency text,rub_amount numeric,
 order_status text,has_receipt boolean,detail text,attempts integer,
 created_at timestamptz,claimed_at timestamptz,completed_at timestamptz,updated_at timestamptz)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_kind IS NOT NULL AND p_kind NOT IN('order_expired_notify','session_dead_admin',
  'session_dead_customer','provider_cancel') THEN RAISE EXCEPTION 'invalid_work_kind';END IF;
 RETURN QUERY WITH candidate AS (
  SELECT w.id FROM public.order_lifecycle_work w WHERE w.state='pending'
   AND (p_kind IS NULL OR w.kind=p_kind) ORDER BY w.id FOR UPDATE SKIP LOCKED LIMIT 1)
 UPDATE public.order_lifecycle_work w SET state='sending',attempts=w.attempts+1,
  claimed_at=clock_timestamp(),updated_at=clock_timestamp()
 FROM candidate c WHERE w.id=c.id AND w.state='pending'
 RETURNING w.id,w.kind,w.order_id,w.session_token,w.provider,w.provider_invoice_id,
  w.user_id,w.currency,w.rub_amount,w.order_status,w.has_receipt,w.detail,w.attempts,
  w.created_at,w.claimed_at,w.completed_at,w.updated_at;
END $$;

CREATE OR REPLACE FUNCTION public.relay_lifecycle_complete_work(p_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_id IS NULL OR p_id<=0 THEN RAISE EXCEPTION 'invalid_work_id';END IF;
 UPDATE public.order_lifecycle_work w SET state='done',completed_at=clock_timestamp(),
  updated_at=clock_timestamp() WHERE w.id=p_id AND w.state='sending';
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.relay_lifecycle_retry_work(p_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_id IS NULL OR p_id<=0 THEN RAISE EXCEPTION 'invalid_work_id';END IF;
 UPDATE public.order_lifecycle_work w SET state='pending',claimed_at=NULL,
  updated_at=clock_timestamp() WHERE w.id=p_id AND w.state='sending';
 RETURN FOUND;
END $$;

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

CREATE OR REPLACE FUNCTION public.relay_payment_mark_notification_sent(p_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_id IS NULL OR p_id<=0 THEN RAISE EXCEPTION 'invalid_notification_id';END IF;
 UPDATE public.payment_notification_outbox o SET state='sent',sent_at=clock_timestamp(),
  updated_at=clock_timestamp() WHERE o.id=p_id AND o.state='sending';
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.relay_payment_retry_notification(p_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_id IS NULL OR p_id<=0 THEN RAISE EXCEPTION 'invalid_notification_id';END IF;
 UPDATE public.payment_notification_outbox o SET state='pending',claimed_at=NULL,
  updated_at=clock_timestamp() WHERE o.id=p_id AND o.state='sending';
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.relay_sell_claim_notification()
RETURNS TABLE(id bigint,sell_id bigint,recipient_id bigint,rub_amount numeric,attempts integer)
LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
 WITH candidate AS (SELECT o.id FROM public.sell_settlement_outbox o
  WHERE o.state='pending' ORDER BY o.id FOR UPDATE SKIP LOCKED LIMIT 1)
 UPDATE public.sell_settlement_outbox o SET state='sending',attempts=o.attempts+1,
  claimed_at=clock_timestamp(),updated_at=clock_timestamp()
 FROM candidate c WHERE o.id=c.id AND o.state='pending'
 RETURNING o.id,o.sell_id,o.recipient_id,o.rub_amount,o.attempts
$$;

CREATE OR REPLACE FUNCTION public.relay_sell_mark_notification_sent(p_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_id IS NULL OR p_id<=0 THEN RAISE EXCEPTION 'invalid_notification_id';END IF;
 UPDATE public.sell_settlement_outbox o SET state='sent',sent_at=clock_timestamp(),
  updated_at=clock_timestamp() WHERE o.id=p_id AND o.state='sending';
 RETURN FOUND;
END $$;

ALTER FUNCTION public.relay_lifecycle_claim_work(text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_lifecycle_complete_work(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_lifecycle_retry_work(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_claim_notification() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_mark_notification_sent(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_payment_retry_notification(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_claim_notification() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_mark_notification_sent(bigint) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_lifecycle_claim_work(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_lifecycle_complete_work(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_lifecycle_retry_work(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_claim_notification() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_mark_notification_sent(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_payment_retry_notification(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_sell_claim_notification() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_sell_mark_notification_sent(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_lifecycle_claim_work(text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_lifecycle_complete_work(bigint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_lifecycle_retry_work(bigint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_claim_notification() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_mark_notification_sent(bigint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_payment_retry_notification(bigint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_sell_claim_notification() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_sell_mark_notification_sent(bigint) TO obsidian_relay;
