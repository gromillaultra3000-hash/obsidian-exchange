-- E0.3 PROPOSAL ONLY. Run after 028 in disposable PostgreSQL 17.
-- Production-equivalent P2 owner-scoped read bodies (12 functions).

GRANT SELECT(id,web_user_id,subject,status,created_at,updated_at) ON public.support_tickets TO obsidian_relay_owner;
GRANT SELECT(ticket_id,sender,message,created_at,id) ON public.support_messages TO obsidian_relay_owner;
GRANT SELECT(referrer_id,referred_id,total_bonus_btc) ON public.referrals TO obsidian_relay_owner;
GRANT SELECT(order_id,user_id,web_user_id,rub_amount,crypto_address,currency,status,created_at,paid_btc_tx,network,receipt_sent_at) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(session_token,order_id,status,created_at,id) ON public.payment_sessions TO obsidian_relay_owner;
GRANT SELECT(order_id) ON public.order_receipts TO obsidian_relay_owner;
GRANT SELECT(session_token,web_user_id,user_id,coin_from,coin_to,amount_from,status,created_at,id) ON public.swap_sessions TO obsidian_relay_owner;
GRANT SELECT(user_id,currency,address) ON public.referral_addresses TO obsidian_relay_owner;
GRANT SELECT(id,user_id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,status,created_at,payout_method,payout_details,payout_bank) ON public.sell_orders TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_support_exists_for_web_user(p_ticket_id bigint,p_web_user_id bigint)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_ticket_id<=0 OR p_web_user_id<=0 THEN RAISE EXCEPTION 'invalid_support_owner'; END IF;
 RETURN EXISTS(SELECT 1 FROM public.support_tickets t WHERE t.id=p_ticket_id AND t.web_user_id=p_web_user_id);
END $$;

CREATE OR REPLACE FUNCTION public.relay_support_list_for_web_user(p_web_user_id bigint)
RETURNS TABLE(id bigint,subject text,status text,created_at timestamptz,updated_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_web_user_id<=0 THEN RAISE EXCEPTION 'invalid_support_owner'; END IF;
 RETURN QUERY SELECT t.id,t.subject,t.status,t.created_at,t.updated_at
 FROM public.support_tickets t WHERE t.web_user_id=p_web_user_id
 ORDER BY t.updated_at DESC,t.id DESC LIMIT 100;
END $$;

CREATE OR REPLACE FUNCTION public.relay_support_open_count_for_web_user(p_web_user_id bigint)
RETURNS bigint LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE result bigint;
BEGIN
 IF p_web_user_id<=0 THEN RAISE EXCEPTION 'invalid_support_owner'; END IF;
 SELECT count(t.id) INTO result FROM public.support_tickets t
  WHERE t.web_user_id=p_web_user_id AND t.status<>'closed';
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.relay_support_thread_for_web_user(p_ticket_id bigint,p_web_user_id bigint)
RETURNS TABLE(ticket_id bigint,subject text,status text,messages jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_ticket_id<=0 OR p_web_user_id<=0 THEN RAISE EXCEPTION 'invalid_support_owner'; END IF;
 RETURN QUERY SELECT t.id,t.subject,t.status,COALESCE((
   SELECT jsonb_agg(jsonb_build_object('sender',m.sender,'message',m.message,'created_at',m.created_at)
                    ORDER BY m.created_at,m.id)
   FROM (SELECT sm.id,sm.sender,sm.message,sm.created_at FROM public.support_messages sm
         WHERE sm.ticket_id=p_ticket_id ORDER BY sm.created_at DESC,sm.id DESC LIMIT 500) m
  ),'[]'::jsonb)
 FROM public.support_tickets t WHERE t.id=p_ticket_id AND t.web_user_id=p_web_user_id;
END $$;

CREATE OR REPLACE FUNCTION public.relay_engagement_referral_stats(p_user_id bigint)
RETURNS TABLE(referrals bigint,active bigint,total_bonus_btc numeric(30,12))
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_referral_owner'; END IF;
 RETURN QUERY SELECT count(r.referred_id),
  count(DISTINCT r.referred_id) FILTER(WHERE EXISTS(
    SELECT 1 FROM public.orders o WHERE o.user_id=r.referred_id AND o.status='sent')),
  COALESCE(sum(r.total_bonus_btc),0)::numeric(30,12)
 FROM public.referrals r WHERE r.referrer_id=p_user_id;
END $$;

CREATE OR REPLACE FUNCTION public.relay_order_customer_orders(p_user_id bigint,p_limit smallint,p_offset integer)
RETURNS TABLE(order_id bigint,rub_amount numeric(20,2),crypto_address text,currency text,status text,
 created_at timestamptz,paid_btc_tx text,network text,receipt_sent_at timestamptz,session_token text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id<=0 OR p_limit<1 OR p_limit>100 OR p_offset<0 OR p_offset>1000000 THEN
  RAISE EXCEPTION 'invalid_customer_order_query'; END IF;
 RETURN QUERY SELECT o.order_id,o.rub_amount::numeric(20,2),o.crypto_address,o.currency,o.status,
  o.created_at,o.paid_btc_tx,o.network,o.receipt_sent_at,
  (SELECT ps.session_token FROM public.payment_sessions ps WHERE ps.order_id=o.order_id
    AND ps.session_token IS NOT NULL AND ps.status NOT IN ('failed','expired')
    ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1)
 FROM public.orders o WHERE o.user_id=p_user_id
 ORDER BY o.created_at DESC,o.order_id DESC LIMIT p_limit OFFSET p_offset;
END $$;

CREATE OR REPLACE FUNCTION public.relay_order_web_customer_orders(
 p_web_user_id bigint,p_linked_telegram_user_id bigint,p_limit smallint)
RETURNS TABLE(order_id bigint,rub_amount numeric(20,2),crypto_address text,currency text,status text,
 created_at timestamptz,paid_btc_tx text,network text,receipt_sent_at timestamptz,session_token text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_web_user_id<=0 OR (p_linked_telegram_user_id IS NOT NULL AND p_linked_telegram_user_id<=0)
    OR p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_web_customer_order_query'; END IF;
 RETURN QUERY SELECT o.order_id,o.rub_amount::numeric(20,2),o.crypto_address,o.currency,o.status,
  o.created_at,o.paid_btc_tx,o.network,o.receipt_sent_at,
  (SELECT ps.session_token FROM public.payment_sessions ps WHERE ps.order_id=o.order_id
    AND ps.session_token IS NOT NULL AND ps.status NOT IN ('failed','expired')
    ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1)
 FROM public.orders o WHERE o.web_user_id=p_web_user_id
    OR (p_linked_telegram_user_id IS NOT NULL AND o.user_id=p_linked_telegram_user_id)
 ORDER BY o.created_at DESC,o.order_id DESC LIMIT p_limit;
END $$;

CREATE OR REPLACE FUNCTION public.relay_order_receipt_order_ids(
 p_order_ids bigint[],p_telegram_user_id bigint,p_web_user_id bigint)
RETURNS TABLE(order_id bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF COALESCE(cardinality(p_order_ids),0)>100 OR EXISTS(SELECT 1 FROM unnest(p_order_ids) x WHERE x<=0)
    OR (p_telegram_user_id IS NULL AND p_web_user_id IS NULL)
    OR (p_telegram_user_id IS NOT NULL AND p_telegram_user_id<=0)
    OR (p_web_user_id IS NOT NULL AND p_web_user_id<=0) THEN
  RAISE EXCEPTION 'receipt_order_ids_too_many_or_invalid_owner'; END IF;
 RETURN QUERY SELECT r.order_id FROM public.order_receipts r JOIN public.orders o ON o.order_id=r.order_id
 WHERE r.order_id=ANY(COALESCE(p_order_ids,ARRAY[]::bigint[])) AND (
  (p_telegram_user_id IS NOT NULL AND o.user_id=p_telegram_user_id)
  OR (p_web_user_id IS NOT NULL AND o.web_user_id=p_web_user_id))
 ORDER BY r.order_id LIMIT 100;
END $$;

CREATE OR REPLACE FUNCTION public.relay_swap_swaps_for_web_user(
 p_web_user_id bigint,p_linked_telegram_user_id bigint,p_limit smallint)
RETURNS TABLE(token text,coin_from text,coin_to text,amount_from numeric,status text,created_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_web_user_id<=0 OR (p_linked_telegram_user_id IS NOT NULL AND p_linked_telegram_user_id<=0)
    OR p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_web_swap_query'; END IF;
 RETURN QUERY SELECT s.session_token,s.coin_from,s.coin_to,s.amount_from,s.status,s.created_at
 FROM public.swap_sessions s WHERE s.web_user_id=p_web_user_id
    OR (p_linked_telegram_user_id IS NOT NULL AND s.user_id=p_linked_telegram_user_id)
 ORDER BY s.created_at DESC,s.id DESC LIMIT p_limit;
END $$;

CREATE OR REPLACE FUNCTION public.relay_user_profile_referral_address(p_user_id bigint,p_currency text)
RETURNS TABLE(address text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id<=0 OR p_currency NOT IN ('BTC','LTC','USDT') THEN
  RAISE EXCEPTION 'invalid_referral_address_query'; END IF;
 RETURN QUERY SELECT r.address FROM public.referral_addresses r
  WHERE r.user_id=p_user_id AND r.currency=p_currency LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_sell_pending_view_for_user(p_user_id bigint,p_limit smallint)
RETURNS TABLE(id bigint,currency text,crypto_amount numeric(30,12),rub_amount numeric(20,2),
 sbp_phone text,receive_address text,created_at timestamptz,payout_method text,payout_details text,payout_bank text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id=0 OR p_limit<0 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_sell_owner_query'; END IF;
 RETURN QUERY SELECT s.id,s.currency,s.crypto_amount::numeric(30,12),s.rub_amount::numeric(20,2),
  s.sbp_phone,s.receive_address,s.created_at,s.payout_method,s.payout_details,s.payout_bank
 FROM public.sell_orders s WHERE s.user_id=p_user_id AND s.status='pending'
 ORDER BY s.id DESC LIMIT p_limit;
END $$;

CREATE OR REPLACE FUNCTION public.relay_sell_sells_for_user(p_user_id bigint,p_limit smallint)
RETURNS TABLE(id bigint,currency text,crypto_amount numeric(30,12),rub_amount numeric(20,2),
 sbp_phone text,status text,created_at timestamptz,payout_method text,payout_details text,payout_bank text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id=0 OR p_limit<0 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_sell_owner_query'; END IF;
 RETURN QUERY SELECT s.id,s.currency,s.crypto_amount::numeric(30,12),s.rub_amount::numeric(20,2),
  s.sbp_phone,s.status,s.created_at,s.payout_method,s.payout_details,s.payout_bank
 FROM public.sell_orders s WHERE s.user_id=p_user_id
 ORDER BY s.created_at DESC,s.id DESC LIMIT p_limit;
END $$;

ALTER FUNCTION public.relay_support_exists_for_web_user(bigint,bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_support_list_for_web_user(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_support_open_count_for_web_user(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_support_thread_for_web_user(bigint,bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_engagement_referral_stats(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_order_customer_orders(bigint,smallint,integer) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_order_web_customer_orders(bigint,bigint,smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_order_receipt_order_ids(bigint[],bigint,bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_swap_swaps_for_web_user(bigint,bigint,smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_user_profile_referral_address(bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_pending_view_for_user(bigint,smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_sells_for_user(bigint,smallint) OWNER TO obsidian_relay_owner;

DO $$ DECLARE p regprocedure; BEGIN
 FOR p IN SELECT oid::regprocedure FROM pg_proc WHERE pronamespace='public'::regnamespace
   AND proname IN ('relay_support_exists_for_web_user','relay_support_list_for_web_user',
   'relay_support_open_count_for_web_user','relay_support_thread_for_web_user',
   'relay_engagement_referral_stats','relay_order_customer_orders',
   'relay_order_web_customer_orders','relay_order_receipt_order_ids',
   'relay_swap_swaps_for_web_user','relay_user_profile_referral_address',
   'relay_sell_pending_view_for_user','relay_sell_sells_for_user')
 LOOP EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',p);
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO obsidian_relay',p); END LOOP;
END $$;
