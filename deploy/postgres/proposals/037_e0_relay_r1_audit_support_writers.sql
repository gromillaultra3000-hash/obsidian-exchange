-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- R1: append-only audit and owner-bound support writers.

GRANT INSERT(event,details) ON public.audit_log TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.audit_log_id_seq TO obsidian_relay_owner;
GRANT INSERT(user_id,username,web_user_id,subject,status)
 ON public.support_tickets TO obsidian_relay_owner;
GRANT SELECT(id,user_id,web_user_id,subject,username)
 ON public.support_tickets TO obsidian_relay_owner;
GRANT UPDATE(status,updated_at) ON public.support_tickets TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.support_tickets_id_seq TO obsidian_relay_owner;
GRANT INSERT(ticket_id,sender,message) ON public.support_messages TO obsidian_relay_owner;
GRANT USAGE ON SEQUENCE public.support_messages_id_seq TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_ops_audit(p_event text,p_details text)
RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_event IS NULL OR length(trim(p_event))<1 OR length(p_event)>120
    OR p_details IS NULL OR length(p_details)>4000 THEN
  RAISE EXCEPTION 'invalid_audit_event';
 END IF;
 INSERT INTO public.audit_log(event,details) VALUES(trim(p_event),p_details);
END $$;

CREATE OR REPLACE FUNCTION public.relay_support_create(
 p_subject text,p_message text,p_user_id bigint,p_username text,p_web_user_id bigint)
RETURNS bigint LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_ticket_id bigint;
BEGIN
 IF p_subject IS NULL OR length(trim(p_subject))<1 OR length(p_subject)>200
    OR p_message IS NULL OR length(trim(p_message))<1 OR length(p_message)>4000
    OR (p_username IS NOT NULL AND length(p_username)>64)
    OR ((COALESCE(p_user_id,0)>0)::integer+(COALESCE(p_web_user_id,0)>0)::integer)<>1 THEN
  RAISE EXCEPTION 'invalid_support_create';
 END IF;
 INSERT INTO public.support_tickets(user_id,username,web_user_id,subject,status)
  VALUES(CASE WHEN COALESCE(p_user_id,0)>0 THEN p_user_id END,
   NULLIF(trim(COALESCE(p_username,'')),''),COALESCE(p_web_user_id,0),trim(p_subject),'open')
  RETURNING id INTO v_ticket_id;
 INSERT INTO public.support_messages(ticket_id,sender,message)
  VALUES(v_ticket_id,'user',p_message);
 RETURN v_ticket_id;
END $$;

CREATE OR REPLACE FUNCTION public.relay_support_user_reply(
 p_ticket_id bigint,p_user_id bigint,p_web_user_id bigint,p_message text)
RETURNS TABLE(subject text,username text)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_subject text;v_username text;
BEGIN
 IF p_ticket_id IS NULL OR p_ticket_id<=0
    OR ((COALESCE(p_user_id,0)>0)::integer+(COALESCE(p_web_user_id,0)>0)::integer)<>1
    OR p_message IS NULL OR length(trim(p_message))<1 OR length(p_message)>4000 THEN
  RAISE EXCEPTION 'invalid_support_reply';
 END IF;
 SELECT t.subject,t.username INTO v_subject,v_username FROM public.support_tickets t
  WHERE t.id=p_ticket_id
   AND ((COALESCE(p_user_id,0)>0 AND t.user_id=p_user_id)
    OR (COALESCE(p_web_user_id,0)>0 AND t.web_user_id=p_web_user_id))
  FOR UPDATE;
 IF NOT FOUND THEN RETURN; END IF;
 INSERT INTO public.support_messages(ticket_id,sender,message)
  VALUES(p_ticket_id,'user',p_message);
 UPDATE public.support_tickets t SET status='open',updated_at=clock_timestamp()
  WHERE t.id=p_ticket_id;
 RETURN QUERY SELECT v_subject,v_username;
END $$;

ALTER FUNCTION public.relay_ops_audit(text,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_support_create(text,text,bigint,text,bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_support_user_reply(bigint,bigint,bigint,text) OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_ops_audit(text,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_support_create(text,text,bigint,text,bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_support_user_reply(bigint,bigint,bigint,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_ops_audit(text,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_support_create(text,text,bigint,text,bigint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_support_user_reply(bigint,bigint,bigint,text) TO obsidian_relay;
