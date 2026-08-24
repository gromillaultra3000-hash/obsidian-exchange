-- E0.3 PROPOSAL ONLY. Disposable PostgreSQL 17 rehearsal only.
-- R3: exact user block/unblock and fixed 90-day audit retention.

GRANT INSERT(user_id,reason) ON public.blocked_users TO obsidian_relay_owner;
GRANT DELETE ON public.blocked_users TO obsidian_relay_owner;
GRANT SELECT(user_id) ON public.blocked_users TO obsidian_relay_owner;
GRANT DELETE ON public.audit_log TO obsidian_relay_owner;
GRANT SELECT(created_at) ON public.audit_log TO obsidian_relay_owner;

CREATE OR REPLACE FUNCTION public.relay_admin_block_user(p_user_id bigint,p_reason text)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id IS NULL OR p_user_id<=0 OR p_reason IS NULL
    OR length(trim(p_reason))<1 OR length(p_reason)>500 THEN
  RAISE EXCEPTION 'invalid_user_block';
 END IF;
 INSERT INTO public.blocked_users(user_id,reason) VALUES(p_user_id,trim(p_reason))
  ON CONFLICT(user_id) DO NOTHING;
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.relay_admin_unblock_user(p_user_id bigint)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF p_user_id IS NULL OR p_user_id<=0 THEN RAISE EXCEPTION 'invalid_user_id';END IF;
 DELETE FROM public.blocked_users b WHERE b.user_id=p_user_id;
 RETURN FOUND;
END $$;

CREATE OR REPLACE FUNCTION public.relay_ops_cleanup_audit()
RETURNS integer LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v_deleted integer;
BEGIN
 DELETE FROM public.audit_log a WHERE a.created_at<current_timestamp-interval '90 days';
 GET DIAGNOSTICS v_deleted=ROW_COUNT;
 RETURN v_deleted;
END $$;

ALTER FUNCTION public.relay_admin_block_user(bigint,text) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_admin_unblock_user(bigint) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_ops_cleanup_audit() OWNER TO obsidian_relay_owner;
REVOKE ALL ON FUNCTION public.relay_admin_block_user(bigint,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_admin_unblock_user(bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_ops_cleanup_audit() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_admin_block_user(bigint,text) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_admin_unblock_user(bigint) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_ops_cleanup_audit() TO obsidian_relay;
