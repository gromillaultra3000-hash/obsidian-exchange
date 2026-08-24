-- E0.3 PROPOSAL ONLY. Exact-attempt pre-submit authorization after Proposal 060.
BEGIN;
CREATE TABLE public.bot_notification_submit_authorizations(
 authorization_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 job_id bigint NOT NULL REFERENCES public.bot_notification_jobs(id) ON DELETE RESTRICT,
 attempt_token uuid NOT NULL,
 recipient_id bigint NOT NULL CHECK(recipient_id>0),
 client_correlation_id uuid UNIQUE NOT NULL,
 revocation_event_id uuid REFERENCES public.bot_notification_recipient_revocation_events(event_id) ON DELETE RESTRICT,
 authorized_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 authorizer_principal text NOT NULL CHECK(length(authorizer_principal) BETWEEN 1 AND 128),
 FOREIGN KEY(job_id,attempt_token,recipient_id)
  REFERENCES public.bot_notification_delivery_attempts(job_id,attempt_token,recipient_id) ON DELETE RESTRICT,
 UNIQUE(job_id,attempt_token)
);
CREATE FUNCTION public.bot_b61_submit_authorization_immutable() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog AS $$BEGIN RAISE EXCEPTION 'submit_authorization_immutable';END$$;
CREATE TRIGGER bot_b61_submit_authorization_immutable BEFORE UPDATE OR DELETE
 ON public.bot_notification_submit_authorizations FOR EACH ROW
 EXECUTE FUNCTION public.bot_b61_submit_authorization_immutable();
CREATE TABLE public.bot_notification_local_failures(
 failure_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 job_id bigint NOT NULL REFERENCES public.bot_notification_jobs(id) ON DELETE RESTRICT,
 attempt_token uuid UNIQUE NOT NULL,
 reason_code text NOT NULL CHECK(reason_code IN('RENDER_INVALID','PAYLOAD_INVALID')),
 evidence_sha256 text NOT NULL CHECK(evidence_sha256~'^[0-9a-f]{64}$'),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 recorder_principal text NOT NULL CHECK(length(recorder_principal) BETWEEN 1 AND 128),
 UNIQUE(job_id,attempt_token)
);
CREATE TRIGGER bot_b61_local_failure_immutable BEFORE UPDATE OR DELETE
 ON public.bot_notification_local_failures FOR EACH ROW
 EXECUTE FUNCTION public.bot_b61_submit_authorization_immutable();

DROP INDEX public.bot_notification_evidence_provider_message_unique;
CREATE UNIQUE INDEX bot_notification_evidence_provider_message_recipient_unique
 ON public.bot_notification_delivery_evidence(provider,channel,recipient_id,provider_message_id)
 WHERE provider_message_id IS NOT NULL;

CREATE FUNCTION public.bot_b61_delivery_pre_submit(a_job_id bigint,a_token uuid,a_client_correlation_id uuid)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE j record;r record;v_revocation_found boolean;v_existing record;
BEGIN
 IF a_job_id IS NULL OR a_job_id<=0 OR a_token IS NULL OR a_client_correlation_id IS NULL THEN RAISE EXCEPTION 'invalid_pre_submit_request';END IF;
 SELECT id,recipient_id INTO j FROM public.bot_notification_jobs WHERE id=a_job_id;
 IF NOT FOUND THEN RETURN 'DENY_STALE';END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('B60_RECIPIENT:'||j.recipient_id::text,530061));
 SELECT id,recipient_id,state,attempt_token,quarantine_event_id INTO j
  FROM public.bot_notification_jobs WHERE id=a_job_id FOR UPDATE;
 IF NOT FOUND OR j.state<>'sending' OR j.attempt_token<>a_token THEN RETURN 'DENY_STALE';END IF;
 SELECT revoked,current_event_id INTO r FROM public.bot_notification_recipient_revocations
  WHERE recipient_id=j.recipient_id;
 v_revocation_found=FOUND;
 IF j.quarantine_event_id IS NOT NULL OR (v_revocation_found AND r.revoked) THEN RETURN 'DENY_REVOKED';END IF;
 SELECT * INTO v_existing FROM public.bot_notification_submit_authorizations
  WHERE job_id=a_job_id AND attempt_token=a_token;
 IF FOUND THEN
  IF v_existing.client_correlation_id=a_client_correlation_id THEN RETURN 'ALLOW';END IF;
  RAISE EXCEPTION 'conflicting_submit_authorization';
 END IF;
 INSERT INTO public.bot_notification_submit_authorizations(job_id,attempt_token,recipient_id,
  client_correlation_id,revocation_event_id,authorizer_principal)
 VALUES(j.id,a_token,j.recipient_id,a_client_correlation_id,
  CASE WHEN v_revocation_found THEN r.current_event_id ELSE NULL END,session_user);
 RETURN 'ALLOW';
END$$;
CREATE FUNCTION public.bot_b61_delivery_mark_local_manual(a_job_id bigint,a_token uuid,a_reason_code text,a_evidence_sha256 text)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF a_reason_code NOT IN('RENDER_INVALID','PAYLOAD_INVALID') OR a_evidence_sha256!~'^[0-9a-f]{64}$'
 THEN RAISE EXCEPTION 'invalid_local_failure';END IF;
 PERFORM 1 FROM public.bot_notification_jobs WHERE id=a_job_id AND state='sending' AND attempt_token=a_token FOR UPDATE;
 IF NOT FOUND THEN RETURN false;END IF;
 IF EXISTS(SELECT 1 FROM public.bot_notification_submit_authorizations WHERE job_id=a_job_id AND attempt_token=a_token)
 THEN RAISE EXCEPTION 'submit_already_authorized';END IF;
 INSERT INTO public.bot_notification_local_failures(job_id,attempt_token,reason_code,evidence_sha256,recorder_principal)
 VALUES(a_job_id,a_token,a_reason_code,a_evidence_sha256,session_user);
 UPDATE public.bot_notification_jobs SET state='manual',manual_reason_code=a_reason_code,updated_at=clock_timestamp()
  WHERE id=a_job_id AND state='sending' AND attempt_token=a_token;
 RETURN FOUND;
END$$;
GRANT SELECT(id,recipient_id,state,attempt_token,quarantine_event_id) ON public.bot_notification_jobs
 TO obsidian_exchange_bot_delivery_owner;
GRANT SELECT(recipient_id,revoked,current_event_id) ON public.bot_notification_recipient_revocations
 TO obsidian_exchange_bot_delivery_owner;
GRANT SELECT,INSERT ON public.bot_notification_submit_authorizations TO obsidian_exchange_bot_delivery_owner;
GRANT SELECT,INSERT ON public.bot_notification_local_failures TO obsidian_exchange_bot_delivery_owner;
ALTER FUNCTION public.bot_b61_submit_authorization_immutable() OWNER TO obsidian_exchange_bot_delivery_owner;
ALTER FUNCTION public.bot_b61_delivery_pre_submit(bigint,uuid,uuid) OWNER TO obsidian_exchange_bot_delivery_owner;
ALTER FUNCTION public.bot_b61_delivery_mark_local_manual(bigint,uuid,text,text) OWNER TO obsidian_exchange_bot_delivery_owner;
REVOKE ALL ON FUNCTION public.bot_b61_submit_authorization_immutable(),public.bot_b61_delivery_pre_submit(bigint,uuid,uuid),
 public.bot_b61_delivery_mark_local_manual(bigint,uuid,text,text)
 FROM PUBLIC,obsidian_exchange_bot,obsidian_exchange_bot_background,obsidian_exchange_bot_transport,
 obsidian_exchange_bot_policy_approver,obsidian_exchange_bot_reconciler;
GRANT EXECUTE ON FUNCTION public.bot_b61_delivery_pre_submit(bigint,uuid,uuid)
 TO obsidian_exchange_bot_delivery;
GRANT EXECUTE ON FUNCTION public.bot_b61_delivery_mark_local_manual(bigint,uuid,text,text)
 TO obsidian_exchange_bot_delivery;
COMMIT;
