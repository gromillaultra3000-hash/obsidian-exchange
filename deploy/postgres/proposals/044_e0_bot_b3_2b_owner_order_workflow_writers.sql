-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal after role envelope.
GRANT SELECT(order_id,user_id,status),UPDATE(status,rub_amount,updated_at) ON public.orders TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b3_owner_cancel_pending(a_order_id bigint,a_user_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_order_id IS NULL OR a_user_id IS NULL OR a_order_id<=0 OR a_user_id<=0 THEN RAISE EXCEPTION 'invalid_owner_order'; END IF;
 UPDATE public.orders SET status='cancelled',updated_at=clock_timestamp()
 WHERE order_id=a_order_id AND user_id=a_user_id AND status='pending';
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b3_owner_retry_amount(a_order_id bigint,a_user_id bigint,a_amount numeric)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_order_id IS NULL OR a_user_id IS NULL OR a_order_id<=0 OR a_user_id<=0 OR a_amount IS NULL OR a_amount::text IN('NaN','Infinity','-Infinity')
    OR a_amount<=0 OR a_amount>999999999999999999.99 THEN
  RAISE EXCEPTION 'invalid_owner_order_amount';
 END IF;
 UPDATE public.orders SET rub_amount=a_amount,updated_at=clock_timestamp()
 WHERE order_id=a_order_id AND user_id=a_user_id AND status='pending';
 RETURN FOUND;
END $$;

ALTER FUNCTION public.bot_b3_owner_cancel_pending(bigint,bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b3_owner_retry_amount(bigint,bigint,numeric) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b3_owner_cancel_pending(bigint,bigint),public.bot_b3_owner_retry_amount(bigint,bigint,numeric) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b3_owner_cancel_pending(bigint,bigint),public.bot_b3_owner_retry_amount(bigint,bigint,numeric) TO obsidian_exchange_bot;
