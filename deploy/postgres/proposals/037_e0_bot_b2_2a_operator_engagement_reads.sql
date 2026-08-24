-- E0.3 PROPOSAL ONLY. Apply after 035/036 in disposable PostgreSQL 17 only.
GRANT SELECT(user_id,broadcast_enabled) ON public.bot_users TO obsidian_exchange_bot_owner;
GRANT SELECT(user_id) ON public.orders TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b2_broadcast_count() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT count(*) FROM public.bot_users b WHERE b.broadcast_enabled=true
$$;
CREATE OR REPLACE FUNCTION public.bot_b2_broadcast_user_ids(p_after bigint,p_limit integer)
RETURNS TABLE(user_id bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_after<0 OR p_limit<1 OR p_limit>500 THEN RAISE EXCEPTION 'invalid_operator_page'; END IF;
 RETURN QUERY SELECT b.user_id FROM public.bot_users b
  WHERE b.broadcast_enabled=true AND b.user_id>p_after ORDER BY b.user_id LIMIT p_limit;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_order_customer_ids(p_after bigint,p_limit integer)
RETURNS TABLE(user_id bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_after<0 OR p_limit<1 OR p_limit>500 THEN RAISE EXCEPTION 'invalid_operator_page'; END IF;
 RETURN QUERY SELECT DISTINCT o.user_id FROM public.orders o
  WHERE o.user_id>p_after ORDER BY o.user_id LIMIT p_limit;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_referral_bonus_period(p_from date,p_to date) RETURNS numeric
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_from IS NULL OR p_to IS NULL OR p_from>p_to OR p_to-p_from>366 THEN RAISE EXCEPTION 'invalid_operator_period'; END IF;
 RETURN COALESCE((SELECT sum(b.bonus_amount) FROM public.referral_bonuses b
  WHERE b.created_at::date BETWEEN p_from AND p_to),0);
END $$;

ALTER FUNCTION public.bot_b2_broadcast_count() OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_broadcast_user_ids(bigint,integer) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_order_customer_ids(bigint,integer) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_referral_bonus_period(date,date) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b2_broadcast_count(),public.bot_b2_broadcast_user_ids(bigint,integer),public.bot_b2_order_customer_ids(bigint,integer),public.bot_b2_referral_bonus_period(date,date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b2_broadcast_count(),public.bot_b2_broadcast_user_ids(bigint,integer),public.bot_b2_order_customer_ids(bigint,integer),public.bot_b2_referral_bonus_period(date,date) TO obsidian_exchange_bot;
