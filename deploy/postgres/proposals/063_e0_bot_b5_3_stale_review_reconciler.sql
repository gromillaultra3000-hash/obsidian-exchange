-- E0.3 PROPOSAL ONLY. Ambiguity-safe stale review and bounded reconciler sweep.
BEGIN;
DO $$ BEGIN
 IF to_regrole('obsidian_exchange_bot_notification_reconciler_owner') IS NULL
 OR to_regrole('obsidian_exchange_bot_notification_reconciler') IS NULL THEN
  RAISE EXCEPTION 'b63_reconciler_roles_missing';
 END IF;
END $$;

ALTER TABLE public.bot_notification_delivery_evidence
 DROP CONSTRAINT bot_notification_evidence_outcome_v62_check,
 ADD CONSTRAINT bot_notification_evidence_outcome_v63_check CHECK(
  (outcome='ACCEPTED' AND reason_code IS NULL AND provider_message_id IS NOT NULL AND provider_request_id IS NULL)
  OR (outcome='NOT_STARTED' AND reason_code='PROVIDER_REJECTED_PRE_SUBMIT' AND provider_message_id IS NULL AND provider_request_id IS NULL)
  OR (outcome='UNCERTAIN' AND reason_code IN('TRANSPORT_UNCERTAIN','ACK_PERSISTENCE_UNCERTAIN')
      AND provider_message_id IS NULL AND provider_request_id IS NULL)
 );

CREATE TABLE public.bot_notification_stale_attempt_reviews(
 review_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 job_id bigint UNIQUE NOT NULL REFERENCES public.bot_notification_jobs(id) ON DELETE RESTRICT,
 attempt_no integer NOT NULL,
 attempt_token uuid UNIQUE NOT NULL,
 classification text NOT NULL CHECK(classification IN('PRE_SUBMIT_ABANDONED','AUTHORIZED_NO_TERMINAL_EVIDENCE')),
 submit_authorization_id uuid REFERENCES public.bot_notification_submit_authorizations(authorization_id)
  ON DELETE RESTRICT,
 reason_code text NOT NULL CHECK(reason_code IN(
  'STALE_PRE_SUBMIT_ABANDONED','STALE_AUTHORIZED_NO_TERMINAL_EVIDENCE')),
 claimed_at timestamptz NOT NULL,
 reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 reconciler_principal text NOT NULL CHECK(length(reconciler_principal) BETWEEN 1 AND 128),
 FOREIGN KEY(job_id,attempt_no) REFERENCES public.bot_notification_delivery_attempts(job_id,attempt_no)
  ON DELETE RESTRICT,
 UNIQUE(job_id,attempt_token)
);
CREATE TRIGGER bot_b63_stale_review_immutable BEFORE UPDATE OR DELETE
 ON public.bot_notification_stale_attempt_reviews FOR EACH ROW
 EXECUTE FUNCTION public.bot_b62_append_only_guard();

CREATE FUNCTION public.bot_b63_reconcile_batch(a_limit integer,a_stale_after_seconds integer)
RETURNS jsonb LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;v_accepted integer:=0;v_stale integer:=0;v_now timestamptz:=clock_timestamp();
BEGIN
 IF a_limit IS NULL OR a_limit<1 OR a_limit>1000
 OR a_stale_after_seconds IS NULL OR a_stale_after_seconds<60 OR a_stale_after_seconds>86400
 THEN RAISE EXCEPTION 'invalid_b63_reconcile_bounds';END IF;

 v_accepted=public.bot_b62_reconcile_accepted(a_limit);
 FOR v IN
  SELECT j.id,a.attempt_no,a.attempt_token,a.claimed_at,s.authorization_id
  FROM public.bot_notification_jobs j
  JOIN public.bot_notification_delivery_attempts a
   ON a.job_id=j.id AND a.attempt_token=j.attempt_token
  LEFT JOIN public.bot_notification_submit_authorizations s
   ON s.job_id=j.id AND s.attempt_token=j.attempt_token
  WHERE j.state='sending' AND a.terminal_evidence_id IS NULL
   AND a.claimed_at<=v_now-pg_catalog.make_interval(secs=>a_stale_after_seconds)
  ORDER BY a.claimed_at,j.id FOR UPDATE OF j,a SKIP LOCKED LIMIT a_limit
 LOOP
  INSERT INTO public.bot_notification_stale_attempt_reviews(
   job_id,attempt_no,attempt_token,classification,submit_authorization_id,reason_code,
   claimed_at,reconciler_principal)
  VALUES(v.id,v.attempt_no,v.attempt_token,
   CASE WHEN v.authorization_id IS NULL THEN 'PRE_SUBMIT_ABANDONED'
        ELSE 'AUTHORIZED_NO_TERMINAL_EVIDENCE' END,
   v.authorization_id,
   CASE WHEN v.authorization_id IS NULL THEN 'STALE_PRE_SUBMIT_ABANDONED'
        ELSE 'STALE_AUTHORIZED_NO_TERMINAL_EVIDENCE' END,
   v.claimed_at,session_user);
  UPDATE public.bot_notification_jobs
   SET state='manual',manual_reason_code=
    CASE WHEN v.authorization_id IS NULL THEN 'STALE_PRE_SUBMIT_ABANDONED'
         ELSE 'STALE_AUTHORIZED_NO_TERMINAL_EVIDENCE' END,updated_at=v_now
   WHERE id=v.id AND state='sending' AND attempt_token=v.attempt_token;
  IF NOT FOUND THEN RAISE EXCEPTION 'b63_stale_transition_lost';END IF;
  v_stale=v_stale+1;
 END LOOP;
 RETURN pg_catalog.jsonb_build_object(
  'acceptedFinalized',v_accepted,
  'staleManualReview',v_stale,
  'actionAllowed',false,
  'automaticRetryAllowed',false
 );
END $$;

GRANT INSERT ON public.bot_notification_stale_attempt_reviews
 TO obsidian_exchange_bot_notification_reconciler_owner;
GRANT SELECT ON public.bot_notification_submit_authorizations
 TO obsidian_exchange_bot_notification_reconciler_owner;
-- Required only for the row lock that serializes stale classification against
-- transport terminal-evidence assignment; the LOGIN still has no direct grant.
GRANT SELECT,UPDATE(terminal_evidence_id) ON public.bot_notification_delivery_attempts
 TO obsidian_exchange_bot_notification_reconciler_owner;
GRANT SELECT(id,state,attempt_token,claimed_at),UPDATE(state,manual_reason_code,updated_at)
 ON public.bot_notification_jobs TO obsidian_exchange_bot_notification_reconciler_owner;
ALTER FUNCTION public.bot_b63_reconcile_batch(integer,integer)
 OWNER TO obsidian_exchange_bot_notification_reconciler_owner;
REVOKE ALL ON FUNCTION public.bot_b63_reconcile_batch(integer,integer)
 FROM PUBLIC,obsidian_exchange_bot,obsidian_exchange_bot_background,
 obsidian_exchange_bot_delivery,obsidian_exchange_bot_transport,
 obsidian_exchange_bot_policy_approver,obsidian_exchange_bot_reconciler;
GRANT EXECUTE ON FUNCTION public.bot_b63_reconcile_batch(integer,integer)
 TO obsidian_exchange_bot_notification_reconciler;
COMMIT;
