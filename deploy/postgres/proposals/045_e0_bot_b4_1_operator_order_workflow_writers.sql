-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal after role envelope.
GRANT SELECT(order_id,status,verification_requested,montera_invoice_id),UPDATE(status,updated_at,verification_requested,montera_invoice_id,receipt_deadline) ON public.orders TO obsidian_exchange_bot_owner;
GRANT SELECT(order_id,event),INSERT(order_id,event) ON public.sent_notifications TO obsidian_exchange_bot_owner;

CREATE OR REPLACE FUNCTION public.bot_b4_clear_verification(a_order_id bigint,a_type text)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_order_id IS NULL OR a_order_id<=0 OR a_type IS NULL OR a_type NOT IN('video','pdf-success') THEN RAISE EXCEPTION 'invalid_verification_clear'; END IF;
 UPDATE public.orders SET verification_requested=NULL,updated_at=clock_timestamp()
 WHERE order_id=a_order_id AND verification_requested=a_type;
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b4_reject_review(a_order_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_order_id IS NULL OR a_order_id<=0 THEN RAISE EXCEPTION 'invalid_review_reject'; END IF;
 UPDATE public.orders SET status='cancelled',updated_at=clock_timestamp()
 WHERE order_id=a_order_id AND status='pending';
 IF NOT FOUND THEN RETURN false; END IF;
 INSERT INTO public.sent_notifications(order_id,event) VALUES(a_order_id,'receipt_rejected')
 ON CONFLICT(order_id,event) DO NOTHING;
 RETURN true;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b4_reopen_review(a_order_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_order_id IS NULL OR a_order_id<=0 THEN RAISE EXCEPTION 'invalid_review_reopen'; END IF;
 UPDATE public.orders SET status='pending',updated_at=clock_timestamp()
 WHERE order_id=a_order_id AND status IN('cancelled','expired','failed');
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.bot_b4_set_montera_invoice(a_order_id bigint,a_invoice text,a_deadline timestamptz)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 a_invoice=trim(a_invoice);
 IF a_order_id IS NULL OR a_order_id<=0 OR a_invoice IS NULL OR a_invoice='' OR length(a_invoice)>255 OR a_deadline IS NULL THEN RAISE EXCEPTION 'invalid_montera_invoice'; END IF;
 UPDATE public.orders SET montera_invoice_id=a_invoice,receipt_deadline=a_deadline,updated_at=clock_timestamp()
 WHERE order_id=a_order_id AND status='pending'
   AND (montera_invoice_id IS NULL OR montera_invoice_id='' OR montera_invoice_id=a_invoice);
 RETURN FOUND;
END $$;

ALTER FUNCTION public.bot_b4_clear_verification(bigint,text) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b4_reject_review(bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b4_reopen_review(bigint) OWNER TO obsidian_exchange_bot_owner;
ALTER FUNCTION public.bot_b4_set_montera_invoice(bigint,text,timestamptz) OWNER TO obsidian_exchange_bot_owner;
REVOKE ALL ON FUNCTION public.bot_b4_clear_verification(bigint,text),public.bot_b4_reject_review(bigint),public.bot_b4_reopen_review(bigint),public.bot_b4_set_montera_invoice(bigint,text,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.bot_b4_clear_verification(bigint,text),public.bot_b4_reject_review(bigint),public.bot_b4_reopen_review(bigint),public.bot_b4_set_montera_invoice(bigint,text,timestamptz) TO obsidian_exchange_bot;
