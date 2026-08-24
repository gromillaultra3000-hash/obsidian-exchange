-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal after role envelope.
GRANT SELECT(id,user_id,currency,used),INSERT(user_id,currency,locked_rate,fee_rub,locked_until),UPDATE(used) ON public.rate_locks TO obsidian_exchange_bot_owner;
GRANT USAGE ON SEQUENCE public.rate_locks_id_seq TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b4_replace_rate_lock(a_user_id bigint,a_currency text,a_rate numeric,a_fee numeric,a_until timestamptz)
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE new_id bigint;
BEGIN
 a_currency=upper(trim(a_currency));
 IF a_user_id IS NULL OR a_user_id<=0 OR a_currency IS NULL OR a_currency NOT IN('BTC','LTC','USDT')
    OR a_rate IS NULL OR a_rate::text IN('NaN','Infinity','-Infinity') OR a_rate<=0 OR a_rate>999999999999999999.999999999999
    OR a_fee IS NULL OR a_fee::text IN('NaN','Infinity','-Infinity') OR a_fee<0 OR a_fee>999999999999999999.99
    OR a_until IS NULL OR a_until<=clock_timestamp() OR a_until>clock_timestamp()+interval '1 day' THEN
  RAISE EXCEPTION 'invalid_rate_lock';
 END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(a_user_id);
 PERFORM id FROM public.rate_locks WHERE user_id=a_user_id AND currency=a_currency AND used=false FOR UPDATE;
 UPDATE public.rate_locks SET used=true WHERE user_id=a_user_id AND currency=a_currency AND used=false;
 INSERT INTO public.rate_locks(user_id,currency,locked_rate,fee_rub,locked_until)
 VALUES(a_user_id,a_currency,a_rate,a_fee,a_until) RETURNING id INTO new_id;
 RETURN new_id;
END $$;

ALTER FUNCTION public.bot_b4_replace_rate_lock(bigint,text,numeric,numeric,timestamptz) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b4_replace_rate_lock(bigint,text,numeric,numeric,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b4_replace_rate_lock(bigint,text,numeric,numeric,timestamptz) TO obsidian_exchange_bot;
