-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- Four P4 operator-reporting bodies. Admin authentication remains an
-- application-layer precondition; the database projections are bounded.

GRANT SELECT(user_id,reason,blocked_at) ON public.blocked_users TO obsidian_relay_owner;
GRANT SELECT(order_id,user_id,username,rub_amount,currency,status,created_at)
  ON public.orders TO obsidian_relay_owner;
GRANT SELECT(id,order_id,provider) ON public.payment_sessions TO obsidian_relay_owner;
GRANT SELECT(provider,is_healthy,failed_count,avg_response_time,status,blocker)
  ON public.provider_health TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_admin_config_blocked_user_rows(p_limit smallint)
RETURNS TABLE(user_id bigint,reason text,blocked_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_limit IS NULL OR p_limit<1 OR p_limit>100 THEN
  RAISE EXCEPTION 'invalid_admin_blocked_limit';
 END IF;
 RETURN QUERY SELECT b.user_id,b.reason,b.blocked_at FROM public.blocked_users b
  ORDER BY b.blocked_at DESC,b.user_id DESC LIMIT p_limit;
END $$;

CREATE OR REPLACE FUNCTION public.relay_order_admin_recent(p_limit smallint)
RETURNS TABLE(order_id bigint,user_id bigint,username text,rub_amount numeric(20,2),
 currency text,status text,created_at timestamptz)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_limit IS NULL OR p_limit<1 OR p_limit>100 THEN
  RAISE EXCEPTION 'invalid_admin_order_limit';
 END IF;
 RETURN QUERY SELECT o.order_id,o.user_id,o.username,o.rub_amount,o.currency,
  o.status,o.created_at FROM public.orders o
  ORDER BY o.created_at DESC,o.order_id DESC LIMIT p_limit;
END $$;

CREATE OR REPLACE FUNCTION public.relay_reporting_admin_stats()
RETURNS TABLE(total bigint,pending bigint,sent bigint,volume numeric(20,2))
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT count(o.order_id),count(o.order_id) FILTER(WHERE o.status='pending'),
  count(o.order_id) FILTER(WHERE o.status='sent'),
  COALESCE(sum(o.rub_amount) FILTER(WHERE o.status='sent'),0)::numeric(20,2)
 FROM public.orders o
$$;

CREATE OR REPLACE FUNCTION public.relay_reporting_admin_analytics()
RETURNS TABLE(daily jsonb,hourly jsonb,by_currency jsonb,by_status jsonb,
 providers jsonb,recent jsonb,totals jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
 SELECT
  COALESCE((SELECT jsonb_agg(jsonb_build_object('day',d.day,'orders',d.orders,
   'volume',d.volume,'paid',d.paid) ORDER BY d.day) FROM (
    SELECT to_char(o.created_at,'MM-DD') AS "day",count(o.order_id) orders,
     sum(o.rub_amount) volume,
     count(o.order_id) FILTER(WHERE o.status IN('paid','sent')) paid
    FROM public.orders o WHERE o.created_at>CURRENT_DATE-interval '14 days'
    GROUP BY 1 ORDER BY 1 LIMIT 15) d),'[]'::jsonb),
  COALESCE((SELECT jsonb_agg(jsonb_build_object('hour',h.hour,'cnt',h.cnt)
   ORDER BY h.hour) FROM (SELECT extract(hour FROM o.created_at)::integer AS "hour",
    count(o.order_id) cnt FROM public.orders o GROUP BY 1 ORDER BY 1 LIMIT 24) h),'[]'::jsonb),
  COALESCE((SELECT jsonb_agg(jsonb_build_object('currency',c.currency,'cnt',c.cnt,
   'vol',c.vol) ORDER BY c.currency) FROM (SELECT o.currency,count(o.order_id) cnt,
    sum(o.rub_amount) vol FROM public.orders o GROUP BY o.currency
    ORDER BY o.currency LIMIT 32) c),'[]'::jsonb),
  COALESCE((SELECT jsonb_agg(jsonb_build_object('status',s.status,'cnt',s.cnt)
   ORDER BY s.status) FROM (SELECT o.status,count(o.order_id) cnt FROM public.orders o
    GROUP BY o.status ORDER BY o.status LIMIT 32) s),'[]'::jsonb),
  COALESCE((SELECT jsonb_agg(jsonb_build_object('provider',p.provider,
   'is_healthy',p.is_healthy,'failed_count',p.failed_count,
   'avg_response_time',p.avg_response_time,'status',COALESCE(p.status,''),
   'blocker',COALESCE(p.blocker,'')) ORDER BY p.provider)
   FROM (SELECT ph.provider,ph.is_healthy,ph.failed_count,ph.avg_response_time,
    ph.status,ph.blocker FROM public.provider_health ph ORDER BY ph.provider LIMIT 64) p),
   '[]'::jsonb),
  COALESCE((SELECT jsonb_agg(jsonb_build_object('order_id',r.order_id,
   'currency',r.currency,'rub_amount',r.rub_amount,'status',r.status,
   'created_at',r.created_at,'username',r.username,'provider',r.provider)
   ORDER BY r.order_id DESC) FROM (SELECT o.order_id,o.currency,o.rub_amount,o.status,
    o.created_at,o.username,(SELECT ps.provider FROM public.payment_sessions ps
     WHERE ps.order_id=o.order_id ORDER BY ps.id DESC LIMIT 1) provider
    FROM public.orders o ORDER BY o.order_id DESC LIMIT 20) r),'[]'::jsonb),
  (SELECT jsonb_build_object('total_orders',count(o.order_id),
    'total_volume',sum(o.rub_amount),'paid_orders',count(o.order_id)
      FILTER(WHERE o.status IN('paid','sent')),
    'paid_volume',sum(o.rub_amount) FILTER(WHERE o.status IN('paid','sent')))
   FROM public.orders o)
$$;

ALTER FUNCTION public.relay_admin_config_blocked_user_rows(smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_order_admin_recent(smallint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_reporting_admin_stats() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_reporting_admin_analytics() OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_admin_config_blocked_user_rows(smallint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_order_admin_recent(smallint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_reporting_admin_stats() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_reporting_admin_analytics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_admin_config_blocked_user_rows(smallint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_order_admin_recent(smallint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_reporting_admin_stats() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_reporting_admin_analytics() TO obsidian_relay;
