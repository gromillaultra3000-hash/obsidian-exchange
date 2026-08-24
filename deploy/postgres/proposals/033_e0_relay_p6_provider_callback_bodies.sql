-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- Three P6 provider-callback correlation bodies; no production rollout.

GRANT SELECT(order_id,user_id,verification_requested,status)
  ON public.orders TO obsidian_relay_owner;
GRANT UPDATE(verification_requested,updated_at)
  ON public.orders TO obsidian_relay_owner;
GRANT SELECT(id,user_id,rub_amount,payout_ref,payout_status,payout_provider)
  ON public.sell_orders TO obsidian_relay_owner;
GRANT SELECT(session_token,user_id,coin_from,coin_to,amount_from,address_to,
  trocador_id,trocador_url,status,provider,deposit_address)
  ON public.swap_sessions TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_order_request_verification(
 p_order_id bigint,p_requested_type text)
RETURNS TABLE(action text,order_id bigint,user_id bigint,
 verification_requested text,status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR
    p_requested_type IS NULL OR p_requested_type NOT IN ('video','pdf-success') THEN
  RAISE EXCEPTION 'invalid_verification_request';
 END IF;
 RETURN QUERY UPDATE public.orders o
  SET verification_requested=p_requested_type,updated_at=clock_timestamp()
  WHERE o.order_id=p_order_id AND o.status='pending'
    AND COALESCE(o.verification_requested,'')=''
  RETURNING 'requested'::text,o.order_id,o.user_id,o.verification_requested,o.status;
 IF FOUND THEN RETURN; END IF;
 RETURN QUERY SELECT 'conflict'::text,o.order_id,o.user_id,
  o.verification_requested,o.status FROM public.orders o WHERE o.order_id=p_order_id;
 IF NOT FOUND THEN
  RETURN QUERY SELECT 'missing'::text,p_order_id,NULL::bigint,NULL::text,NULL::text;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION public.relay_sell_vertu_payout_by_ref(p_ref text)
RETURNS TABLE(id bigint,user_id bigint,rub_amount numeric(20,2),payout_status text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_suffix text;
BEGIN
 IF p_ref IS NULL OR length(trim(p_ref))<1 OR length(p_ref)>256 THEN
  RAISE EXCEPTION 'invalid_vertu_payout_ref';
 END IF;
 RETURN QUERY SELECT s.id,s.user_id,s.rub_amount,s.payout_status
  FROM public.sell_orders s
  WHERE s.payout_provider='vertu' AND s.payout_ref=trim(p_ref) LIMIT 1;
 IF FOUND THEN RETURN; END IF;
 v_suffix=pg_catalog.regexp_replace(trim(p_ref),'^.*_','');
 RETURN QUERY SELECT s.id,s.user_id,s.rub_amount,s.payout_status
  FROM public.sell_orders s WHERE s.payout_provider='vertu' AND s.payout_ref=v_suffix
    AND (SELECT count(c.id) FROM public.sell_orders c
         WHERE c.payout_provider='vertu' AND c.payout_ref=v_suffix)=1
  ORDER BY s.id LIMIT 1;
END $$;

CREATE OR REPLACE FUNCTION public.relay_swap_get_by_external_id(p_external_id text)
RETURNS TABLE(session_token text,user_id bigint,coin_from text,coin_to text,
 amount_from numeric(30,12),address_to text,external_id text,external_url text,
 status text,provider text,deposit_address text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_external_id IS NULL OR length(trim(p_external_id))<1
    OR length(p_external_id)>256 THEN RAISE EXCEPTION 'invalid_swap_external_id'; END IF;
 RETURN QUERY SELECT s.session_token,s.user_id,s.coin_from,s.coin_to,s.amount_from,
  s.address_to,s.trocador_id,s.trocador_url,s.status,s.provider,s.deposit_address
  FROM public.swap_sessions s WHERE s.trocador_id=trim(p_external_id) LIMIT 1;
END $$;

ALTER FUNCTION public.relay_order_request_verification(bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_vertu_payout_by_ref(text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_swap_get_by_external_id(text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_order_request_verification(bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_sell_vertu_payout_by_ref(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_swap_get_by_external_id(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_order_request_verification(bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_sell_vertu_payout_by_ref(text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_swap_get_by_external_id(text) TO obsidian_relay;
