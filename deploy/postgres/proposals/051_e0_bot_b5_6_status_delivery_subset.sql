-- E0.3 PROPOSAL ONLY. Safe paid/sent delivery subset; payout_* events are deliberately excluded.
GRANT SELECT(order_id,status) ON public.orders TO obsidian_exchange_bot_owner;
GRANT SELECT(order_id,event),INSERT(order_id,event) ON public.sent_notifications TO obsidian_exchange_bot_owner;
GRANT SELECT(order_id,status),UPDATE(status) ON public.gift_vouchers TO obsidian_exchange_bot_owner;
CREATE OR REPLACE FUNCTION public.bot_b5_complete_status_delivery(a_order_id bigint,a_event text) RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_order_id IS NULL OR a_order_id<=0 OR a_event NOT IN('paid','sent') THEN RAISE EXCEPTION 'invalid_status_delivery';END IF;
 IF NOT EXISTS(SELECT 1 FROM public.orders WHERE order_id=a_order_id AND status=a_event) THEN RETURN false;END IF;
 INSERT INTO public.sent_notifications(order_id,event) VALUES(a_order_id,a_event) ON CONFLICT DO NOTHING;
 IF NOT FOUND THEN RETURN false;END IF;
 IF a_event='paid' THEN UPDATE public.gift_vouchers SET status='paid' WHERE order_id=a_order_id AND status='pending';END IF;
 RETURN true;
END $$;
ALTER FUNCTION public.bot_b5_complete_status_delivery(bigint,text) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b5_complete_status_delivery(bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b5_complete_status_delivery(bigint,text) TO obsidian_exchange_bot;
