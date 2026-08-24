-- E0.3 PROPOSAL ONLY. Apply after 035 in disposable PostgreSQL 17 only.
GRANT SELECT(user_id,enabled) ON public.rate_subscriptions TO obsidian_exchange_bot_owner;
GRANT SELECT(user_id,total_rub) ON public.user_vip_volume TO obsidian_exchange_bot_owner;
GRANT SELECT(referrer_id,bonus_amount,created_at) ON public.referral_bonuses TO obsidian_exchange_bot_owner;
GRANT SELECT(id,user_id,created_at) ON public.orders TO obsidian_exchange_bot_owner;
GRANT SELECT(id,user_id,subject,status,updated_at) ON public.support_tickets TO obsidian_exchange_bot_owner;
GRANT SELECT(id,ticket_id,sender,message,created_at) ON public.support_messages TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b2_rate_enabled(p_user_id bigint) RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner'; END IF;
 RETURN COALESCE((SELECT r.enabled FROM public.rate_subscriptions r WHERE r.user_id=p_user_id),false);
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_vip_total(p_user_id bigint) RETURNS numeric
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner'; END IF;
 RETURN COALESCE((SELECT v.total_rub FROM public.user_vip_volume v WHERE v.user_id=p_user_id),0);
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_referral_bonus_owner(p_user_id bigint) RETURNS numeric
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner'; END IF;
 RETURN COALESCE((SELECT sum(b.bonus_amount) FROM public.referral_bonuses b WHERE b.referrer_id=p_user_id),0);
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_creation_limit_state(p_user_id bigint,p_daily_since timestamptz,p_cooldown_since timestamptz)
RETURNS TABLE(daily_count bigint,cooldown_active boolean,latest_created_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 OR p_daily_since IS NULL OR p_cooldown_since IS NULL THEN RAISE EXCEPTION 'invalid_creation_limit'; END IF;
 RETURN QUERY SELECT count(o.id),EXISTS(SELECT 1 FROM public.orders c WHERE c.user_id=p_user_id AND c.created_at>p_cooldown_since),max(o.created_at)
  FROM public.orders o WHERE o.user_id=p_user_id AND o.created_at>p_daily_since;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_support_list(p_user_id bigint,p_limit integer)
RETURNS TABLE(id bigint,subject text,status text,updated_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 OR p_limit<1 OR p_limit>100 THEN RAISE EXCEPTION 'invalid_support_list'; END IF;
 RETURN QUERY SELECT t.id,t.subject,t.status,t.updated_at FROM public.support_tickets t WHERE t.user_id=p_user_id ORDER BY t.updated_at DESC,t.id DESC LIMIT p_limit;
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_support_open_count(p_user_id bigint) RETURNS bigint
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner'; END IF;
 RETURN (SELECT count(*) FROM public.support_tickets t WHERE t.user_id=p_user_id AND t.status='open');
END $$;
CREATE OR REPLACE FUNCTION public.bot_b2_support_thread(p_ticket_id bigint,p_user_id bigint)
RETURNS TABLE(subject text,status text,messages jsonb)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN
 IF p_ticket_id<=0 OR p_user_id<=0 THEN RAISE EXCEPTION 'invalid_support_thread'; END IF;
 RETURN QUERY SELECT t.subject,t.status,COALESCE((SELECT jsonb_agg(jsonb_build_object('sender',q.sender,'message',q.message,'created_at',q.created_at) ORDER BY q.id)
  FROM (SELECT m.id,m.sender,m.message,m.created_at FROM public.support_messages m WHERE m.ticket_id=t.id ORDER BY m.id DESC LIMIT 500) q),'[]'::jsonb)
  FROM public.support_tickets t WHERE t.id=p_ticket_id AND t.user_id=p_user_id;
END $$;

ALTER FUNCTION public.bot_b2_rate_enabled(bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_vip_total(bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_referral_bonus_owner(bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_creation_limit_state(bigint,timestamptz,timestamptz) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_support_list(bigint,integer) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_support_open_count(bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b2_support_thread(bigint,bigint) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b2_rate_enabled(bigint),public.bot_b2_vip_total(bigint),public.bot_b2_referral_bonus_owner(bigint),public.bot_b2_creation_limit_state(bigint,timestamptz,timestamptz),public.bot_b2_support_list(bigint,integer),public.bot_b2_support_open_count(bigint),public.bot_b2_support_thread(bigint,bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b2_rate_enabled(bigint),public.bot_b2_vip_total(bigint),public.bot_b2_referral_bonus_owner(bigint),public.bot_b2_creation_limit_state(bigint,timestamptz,timestamptz),public.bot_b2_support_list(bigint,integer),public.bot_b2_support_open_count(bigint),public.bot_b2_support_thread(bigint,bigint) TO obsidian_exchange_bot;
