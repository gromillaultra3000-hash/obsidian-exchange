-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- R5A: verification, sell cancellation, swap CAS and referral payout metadata.
GRANT SELECT(order_id,user_id,verification_requested,status) ON public.orders TO obsidian_relay_owner;
GRANT UPDATE(verification_requested,updated_at) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(id,status) ON public.sell_orders TO obsidian_relay_owner;
GRANT UPDATE(status,updated_at) ON public.sell_orders TO obsidian_relay_owner;
GRANT SELECT(session_token,status) ON public.swap_sessions TO obsidian_relay_owner;
GRANT UPDATE(status,updated_at) ON public.swap_sessions TO obsidian_relay_owner;
GRANT INSERT(user_id,currency,address) ON public.referral_addresses TO obsidian_relay_owner;
GRANT SELECT(user_id,currency,address) ON public.referral_addresses TO obsidian_relay_owner;
GRANT UPDATE(currency,address) ON public.referral_addresses TO obsidian_relay_owner;

CREATE FUNCTION public.relay_order_request_verification(p_order_id bigint,p_kind text)
RETURNS TABLE(action text,order_id bigint,user_id bigint,verification_requested text,status text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_order_id IS NULL OR p_order_id<=0 OR p_kind NOT IN('video','pdf-success') THEN RAISE EXCEPTION 'invalid_verification_request';END IF;
 UPDATE public.orders o SET verification_requested=p_kind,updated_at=clock_timestamp()
  WHERE o.order_id=p_order_id AND o.status='pending' AND COALESCE(o.verification_requested,'')='';
 RETURN QUERY SELECT CASE WHEN FOUND THEN 'requested' ELSE 'conflict' END,o.order_id,o.user_id,o.verification_requested,o.status
  FROM public.orders o WHERE o.order_id=p_order_id;
 IF NOT FOUND THEN RETURN QUERY SELECT 'missing'::text,p_order_id,NULL::bigint,NULL::text,NULL::text;END IF;
END $$;
CREATE FUNCTION public.relay_sell_cancel_pending(p_sell_id bigint) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_sell_id IS NULL OR p_sell_id<=0 THEN RAISE EXCEPTION 'invalid_sell_id';END IF;
 UPDATE public.sell_orders s SET status='cancelled',updated_at=clock_timestamp() WHERE s.id=p_sell_id AND s.status='pending';RETURN FOUND;END $$;
CREATE FUNCTION public.relay_swap_transition(p_token text,p_expected text,p_new text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_token IS NULL OR length(trim(p_token))<16 OR length(p_token)>256 OR p_expected IS NULL OR length(p_expected)>64 OR p_new IS NULL OR length(p_new)>64 THEN RAISE EXCEPTION 'invalid_swap_transition';END IF;
 IF p_new=p_expected THEN RETURN true;END IF;
 UPDATE public.swap_sessions s SET status=p_new,updated_at=clock_timestamp() WHERE s.session_token=p_token AND s.status=p_expected;RETURN FOUND;END $$;
CREATE FUNCTION public.relay_user_profile_set_referral_address(p_user_id bigint,p_currency text,p_address text) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id IS NULL OR p_user_id<=0 OR p_currency IS NULL OR length(trim(p_currency))<1 OR length(p_currency)>16 OR p_address IS NULL OR length(trim(p_address))<1 OR length(p_address)>256 THEN RAISE EXCEPTION 'invalid_referral_address';END IF;
 INSERT INTO public.referral_addresses(user_id,currency,address) VALUES(p_user_id,upper(trim(p_currency)),trim(p_address))
 ON CONFLICT(user_id) DO UPDATE SET currency=excluded.currency,address=excluded.address;END $$;

ALTER FUNCTION public.relay_order_request_verification(bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_sell_cancel_pending(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_swap_transition(text,text,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_user_profile_set_referral_address(bigint,text,text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_order_request_verification(bigint,text),public.relay_sell_cancel_pending(bigint),public.relay_swap_transition(text,text,text),public.relay_user_profile_set_referral_address(bigint,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_order_request_verification(bigint,text),public.relay_sell_cancel_pending(bigint),public.relay_swap_transition(text,text,text),public.relay_user_profile_set_referral_address(bigint,text,text) TO obsidian_relay;
