-- E0.3 PROPOSAL ONLY. Authenticated policy governance and recipient revocation.
-- Apply only after proposals 058 and 059 in a clean disposable rehearsal.
-- LOGIN credentials are provisioned separately; identity is always session_user.
BEGIN;
DO $$ BEGIN
 IF to_regrole('obsidian_exchange_bot_governance_owner') IS NULL
    OR to_regrole('obsidian_exchange_bot_policy_approver') IS NULL
    OR to_regrole('obsidian_exchange_bot_reconciler_owner') IS NULL
    OR to_regrole('obsidian_exchange_bot_reconciler') IS NULL THEN
  RAISE EXCEPTION 'b60_governance_roles_missing';
 END IF;
 IF EXISTS(SELECT 1 FROM public.bot_notification_policy_current) THEN
  RAISE EXCEPTION 'legacy_policy_pointer_requires_audited_activation_backfill';
 END IF;
END $$;

CREATE TABLE public.bot_notification_policy_approvals(
 approval_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 policy_id uuid NOT NULL,
 policy_version bigint NOT NULL,
 policy_sha256 text NOT NULL CHECK(policy_sha256~'^[0-9a-f]{64}$'),
 approval_evidence_sha256 text NOT NULL CHECK(approval_evidence_sha256~'^[0-9a-f]{64}$'),
 approver_principal text NOT NULL CHECK(length(approver_principal) BETWEEN 1 AND 128),
 approved_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(policy_id,policy_version) REFERENCES public.bot_notification_policy_versions(policy_id,version) ON DELETE RESTRICT,
 UNIQUE(policy_id,policy_version)
);

CREATE TABLE public.bot_notification_policy_activation_events(
 event_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 previous_event_id uuid REFERENCES public.bot_notification_policy_activation_events(event_id) ON DELETE RESTRICT,
 action text NOT NULL CHECK(action IN('ACTIVATE','DEACTIVATE')),
 policy_id uuid,
 policy_version bigint,
 approval_id uuid REFERENCES public.bot_notification_policy_approvals(approval_id) ON DELETE RESTRICT,
 activation_evidence_sha256 text NOT NULL CHECK(activation_evidence_sha256~'^[0-9a-f]{64}$'),
 actor_principal text NOT NULL CHECK(length(actor_principal) BETWEEN 1 AND 128),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 event_sha256 text UNIQUE NOT NULL CHECK(event_sha256~'^[0-9a-f]{64}$'),
 FOREIGN KEY(policy_id,policy_version) REFERENCES public.bot_notification_policy_versions(policy_id,version) ON DELETE RESTRICT,
 CHECK((action='ACTIVATE' AND policy_id IS NOT NULL AND policy_version IS NOT NULL AND approval_id IS NOT NULL)
    OR (action='DEACTIVATE' AND policy_id IS NULL AND policy_version IS NULL AND approval_id IS NULL))
);

ALTER TABLE public.bot_notification_policy_current
 ADD COLUMN activation_event_id uuid NOT NULL,
 ADD COLUMN activation_principal text NOT NULL,
 ADD CONSTRAINT bot_notification_policy_current_event_fk FOREIGN KEY(activation_event_id)
  REFERENCES public.bot_notification_policy_activation_events(event_id) ON DELETE RESTRICT;

CREATE TABLE public.bot_notification_recipient_revocation_events(
 event_id uuid PRIMARY KEY DEFAULT pg_catalog.gen_random_uuid(),
 recipient_id bigint NOT NULL CHECK(recipient_id>0),
 previous_event_id uuid REFERENCES public.bot_notification_recipient_revocation_events(event_id) ON DELETE RESTRICT,
 action text NOT NULL CHECK(action IN('REVOKE','RESTORE')),
 reason_code text NOT NULL CHECK(reason_code IN('ACCESS_REVOKED','ACCOUNT_COMPROMISED','OWNER_REQUEST','FALSE_POSITIVE_RESTORE')),
 evidence_sha256 text NOT NULL CHECK(evidence_sha256~'^[0-9a-f]{64}$'),
 actor_principal text NOT NULL CHECK(length(actor_principal) BETWEEN 1 AND 128),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 event_sha256 text UNIQUE NOT NULL CHECK(event_sha256~'^[0-9a-f]{64}$')
);
CREATE TABLE public.bot_notification_recipient_revocations(
 recipient_id bigint PRIMARY KEY CHECK(recipient_id>0),
 revoked boolean NOT NULL,
 current_event_id uuid UNIQUE NOT NULL REFERENCES public.bot_notification_recipient_revocation_events(event_id) ON DELETE RESTRICT,
 updated_at timestamptz NOT NULL
);
CREATE TABLE public.bot_notification_recipient_quarantines(
 job_id bigint PRIMARY KEY REFERENCES public.bot_notification_jobs(id) ON DELETE RESTRICT,
 revocation_event_id uuid NOT NULL REFERENCES public.bot_notification_recipient_revocation_events(event_id) ON DELETE RESTRICT,
 attempt_token uuid UNIQUE,
 prior_state text NOT NULL CHECK(prior_state IN('pending','sending')),
 possible_in_flight boolean NOT NULL,
 quarantined_at timestamptz NOT NULL,
 reconciler_principal text NOT NULL CHECK(length(reconciler_principal) BETWEEN 1 AND 128)
);

ALTER TABLE public.bot_notification_jobs
 ADD COLUMN quarantine_event_id uuid REFERENCES public.bot_notification_recipient_revocation_events(event_id) ON DELETE RESTRICT,
 ADD COLUMN quarantined_at timestamptz,
 DROP CONSTRAINT bot_notification_jobs_lifecycle_check,
 DROP CONSTRAINT bot_notification_jobs_state_check,
 ADD CONSTRAINT bot_notification_jobs_state_check CHECK(state IN('pending','sending','sent','manual','quarantined')),
 ADD CONSTRAINT bot_notification_jobs_lifecycle_check CHECK(
  (state='pending' AND attempts<max_attempts AND attempt_token IS NULL AND claimed_at IS NULL AND sent_at IS NULL AND manual_reason_code IS NULL AND quarantine_event_id IS NULL AND quarantined_at IS NULL)
  OR (state='sending' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL AND sent_at IS NULL AND manual_reason_code IS NULL AND attempts>=1
      AND ((quarantine_event_id IS NULL AND quarantined_at IS NULL) OR (quarantine_event_id IS NOT NULL AND quarantined_at IS NOT NULL)))
  OR (state='sent' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL AND sent_at IS NOT NULL AND manual_reason_code IS NULL AND attempts>=1
      AND ((quarantine_event_id IS NULL AND quarantined_at IS NULL) OR (quarantine_event_id IS NOT NULL AND quarantined_at IS NOT NULL)))
  OR (state='manual' AND attempt_token IS NOT NULL AND claimed_at IS NOT NULL AND sent_at IS NULL AND manual_reason_code IS NOT NULL AND attempts>=1
      AND ((quarantine_event_id IS NULL AND quarantined_at IS NULL) OR (quarantine_event_id IS NOT NULL AND quarantined_at IS NOT NULL)))
  OR (state='quarantined' AND sent_at IS NULL AND manual_reason_code IS NULL AND quarantine_event_id IS NOT NULL AND quarantined_at IS NOT NULL
      AND attempt_token IS NULL AND claimed_at IS NULL)
 );
CREATE INDEX bot_notification_jobs_recipient_active_idx ON public.bot_notification_jobs(recipient_id,state,id)
 WHERE state IN('pending','sending','quarantined');

CREATE FUNCTION public.bot_b60_append_only_guard() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog AS $$BEGIN RAISE EXCEPTION 'b60_append_only';END$$;
CREATE TRIGGER bot_b60_approval_append_only BEFORE UPDATE OR DELETE ON public.bot_notification_policy_approvals
 FOR EACH ROW EXECUTE FUNCTION public.bot_b60_append_only_guard();
CREATE TRIGGER bot_b60_activation_append_only BEFORE UPDATE OR DELETE ON public.bot_notification_policy_activation_events
 FOR EACH ROW EXECUTE FUNCTION public.bot_b60_append_only_guard();
CREATE TRIGGER bot_b60_revocation_append_only BEFORE UPDATE OR DELETE ON public.bot_notification_recipient_revocation_events
 FOR EACH ROW EXECUTE FUNCTION public.bot_b60_append_only_guard();
CREATE TRIGGER bot_b60_quarantine_append_only BEFORE UPDATE OR DELETE ON public.bot_notification_recipient_quarantines
 FOR EACH ROW EXECUTE FUNCTION public.bot_b60_append_only_guard();

CREATE FUNCTION public.bot_b60_approve_policy(a_policy_id uuid,a_policy_version bigint,a_policy_sha256 text,a_evidence_sha256 text)
RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE p record;v record;v_id uuid;
BEGIN
 IF a_policy_id IS NULL OR a_policy_version IS NULL OR a_policy_sha256!~'^[0-9a-f]{64}$'
 OR a_evidence_sha256!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'invalid_policy_approval';END IF;
 SELECT policy_sha256 INTO p FROM public.bot_notification_policy_versions
  WHERE policy_id=a_policy_id AND version=a_policy_version FOR SHARE;
 IF NOT FOUND OR p.policy_sha256<>a_policy_sha256 THEN RAISE EXCEPTION 'policy_approval_digest_mismatch';END IF;
 SELECT * INTO v FROM public.bot_notification_policy_approvals WHERE policy_id=a_policy_id AND policy_version=a_policy_version;
 IF FOUND THEN
  IF v.policy_sha256=a_policy_sha256 AND v.approval_evidence_sha256=a_evidence_sha256
   AND v.approver_principal=session_user THEN RETURN v.approval_id;END IF;
  RAISE EXCEPTION 'conflicting_policy_approval';
 END IF;
 INSERT INTO public.bot_notification_policy_approvals(policy_id,policy_version,policy_sha256,approval_evidence_sha256,approver_principal)
 VALUES(a_policy_id,a_policy_version,a_policy_sha256,a_evidence_sha256,session_user) RETURNING approval_id INTO v_id;
 RETURN v_id;
END$$;

CREATE FUNCTION public.bot_b60_activate_policy(a_policy_id uuid,a_policy_version bigint,a_approval_id uuid,
 a_expected_event_id uuid,a_evidence_sha256 text) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c record;a record;e record;v_id uuid;v_hash text;v_now timestamptz:=clock_timestamp();v_has_current boolean;
BEGIN
 IF a_evidence_sha256!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'invalid_activation_evidence';END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(530060);
 SELECT * INTO c FROM public.bot_notification_policy_current WHERE singleton FOR UPDATE;
 v_has_current=FOUND;
 IF v_has_current AND c.policy_id=a_policy_id AND c.policy_version=a_policy_version THEN
  SELECT * INTO e FROM public.bot_notification_policy_activation_events
   WHERE event_id=c.activation_event_id AND activation_evidence_sha256=a_evidence_sha256 AND actor_principal=session_user;
  IF FOUND AND e.approval_id=a_approval_id AND e.previous_event_id IS NOT DISTINCT FROM a_expected_event_id THEN RETURN e.event_id;END IF;
 END IF;
 IF (v_has_current AND c.activation_event_id IS DISTINCT FROM a_expected_event_id)
 OR (NOT v_has_current AND a_expected_event_id IS NOT NULL) THEN RAISE EXCEPTION 'stale_activation_head';END IF;
 SELECT x.* INTO a FROM public.bot_notification_policy_approvals x
  WHERE x.approval_id=a_approval_id AND x.policy_id=a_policy_id AND x.policy_version=a_policy_version FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'policy_not_authenticated_approved';END IF;
 IF v_has_current AND c.policy_version>=a_policy_version THEN
  RAISE EXCEPTION 'policy_version_not_monotonic';END IF;
 v_id=pg_catalog.gen_random_uuid();
 v_hash=encode(pg_catalog.sha256(pg_catalog.convert_to(jsonb_build_object('event_id',v_id,'previous_event_id',a_expected_event_id,
  'action','ACTIVATE','policy_id',a_policy_id,'policy_version',a_policy_version,'approval_id',a_approval_id,
  'evidence',a_evidence_sha256,'actor',session_user,'recorded_at',v_now)::text,'UTF8')),'hex');
 INSERT INTO public.bot_notification_policy_activation_events(event_id,previous_event_id,action,policy_id,policy_version,
  approval_id,activation_evidence_sha256,actor_principal,recorded_at,event_sha256)
 VALUES(v_id,a_expected_event_id,'ACTIVATE',a_policy_id,a_policy_version,a_approval_id,a_evidence_sha256,session_user,v_now,v_hash);
 INSERT INTO public.bot_notification_policy_current(singleton,policy_id,policy_version,activated_by,activated_at,activation_event_id,activation_principal)
 VALUES(true,a_policy_id,a_policy_version,1,v_now,v_id,session_user)
 ON CONFLICT(singleton) DO UPDATE SET policy_id=EXCLUDED.policy_id,policy_version=EXCLUDED.policy_version,
  activated_by=EXCLUDED.activated_by,activated_at=EXCLUDED.activated_at,activation_event_id=EXCLUDED.activation_event_id,
  activation_principal=EXCLUDED.activation_principal;
 RETURN v_id;
END$$;

CREATE FUNCTION public.bot_b60_set_recipient_revocation(a_recipient_id bigint,a_action text,
 a_expected_event_id uuid,a_reason_code text,a_evidence_sha256 text) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE c record;j record;v_id uuid;v_hash text;v_now timestamptz:=clock_timestamp();
BEGIN
 IF a_recipient_id IS NULL OR a_recipient_id<=0 OR a_action NOT IN('REVOKE','RESTORE')
 OR a_reason_code NOT IN('ACCESS_REVOKED','ACCOUNT_COMPROMISED','OWNER_REQUEST','FALSE_POSITIVE_RESTORE')
 OR a_evidence_sha256!~'^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'invalid_recipient_revocation';END IF;
 IF (a_action='RESTORE')<>(a_reason_code='FALSE_POSITIVE_RESTORE') THEN RAISE EXCEPTION 'revocation_reason_action_mismatch';END IF;
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('B60_RECIPIENT:'||a_recipient_id::text,530061));
 SELECT * INTO c FROM public.bot_notification_recipient_revocations WHERE recipient_id=a_recipient_id FOR UPDATE;
 IF FOUND AND c.current_event_id IS DISTINCT FROM a_expected_event_id THEN RAISE EXCEPTION 'stale_revocation_head';END IF;
 IF NOT FOUND AND a_expected_event_id IS NOT NULL THEN RAISE EXCEPTION 'stale_revocation_head';END IF;
 IF FOUND AND c.revoked=(a_action='REVOKE') THEN
  SELECT event_id INTO v_id FROM public.bot_notification_recipient_revocation_events
   WHERE event_id=c.current_event_id AND evidence_sha256=a_evidence_sha256 AND reason_code=a_reason_code AND actor_principal=session_user;
  IF FOUND THEN RETURN v_id;END IF;RAISE EXCEPTION 'conflicting_recipient_revocation';
 END IF;
 v_id=pg_catalog.gen_random_uuid();
 v_hash=encode(pg_catalog.sha256(pg_catalog.convert_to(jsonb_build_object('event_id',v_id,'previous_event_id',a_expected_event_id,
  'recipient_id',a_recipient_id,'action',a_action,'reason',a_reason_code,'evidence',a_evidence_sha256,
  'actor',session_user,'recorded_at',v_now)::text,'UTF8')),'hex');
 INSERT INTO public.bot_notification_recipient_revocation_events(event_id,recipient_id,previous_event_id,action,reason_code,
  evidence_sha256,actor_principal,recorded_at,event_sha256)
 VALUES(v_id,a_recipient_id,a_expected_event_id,a_action,a_reason_code,a_evidence_sha256,session_user,v_now,v_hash);
 INSERT INTO public.bot_notification_recipient_revocations VALUES(a_recipient_id,a_action='REVOKE',v_id,v_now)
 ON CONFLICT(recipient_id) DO UPDATE SET revoked=EXCLUDED.revoked,current_event_id=EXCLUDED.current_event_id,updated_at=EXCLUDED.updated_at;
 IF a_action='REVOKE' THEN
  FOR j IN SELECT id,state,attempt_token FROM public.bot_notification_jobs
   WHERE recipient_id=a_recipient_id AND state IN('pending','sending') ORDER BY id FOR UPDATE LOOP
   INSERT INTO public.bot_notification_recipient_quarantines(job_id,revocation_event_id,attempt_token,prior_state,
    possible_in_flight,quarantined_at,reconciler_principal)
   VALUES(j.id,v_id,j.attempt_token,j.state,j.state='sending',v_now,session_user);
   UPDATE public.bot_notification_jobs SET state=CASE WHEN j.state='pending' THEN 'quarantined' ELSE 'sending' END,
    quarantine_event_id=v_id,quarantined_at=v_now
    WHERE id=j.id AND state=j.state;
  END LOOP;
 END IF;
 RETURN v_id;
END$$;

CREATE FUNCTION public.bot_b60_reject_revoked_recipient() RETURNS trigger LANGUAGE plpgsql
SECURITY DEFINER SET search_path=pg_catalog AS $$BEGIN
 PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('B60_RECIPIENT:'||NEW.recipient_id::text,530061));
 IF EXISTS(SELECT 1 FROM public.bot_notification_recipient_revocations r WHERE r.recipient_id=NEW.recipient_id AND r.revoked)
 THEN RAISE EXCEPTION 'notification_recipient_revoked';END IF;RETURN NEW;
END$$;
CREATE TRIGGER bot_b60_reject_revoked_recipient BEFORE INSERT ON public.bot_notification_jobs
 FOR EACH ROW EXECUTE FUNCTION public.bot_b60_reject_revoked_recipient();

CREATE OR REPLACE FUNCTION public.bot_b53_delivery_claim(a_kind text)
RETURNS TABLE(id bigint,kind text,dedupe_key text,payload jsonb,attempts integer,recipient_id bigint,attempt_token uuid)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE v record;v_token uuid;v_claimed timestamptz;
BEGIN
 IF a_kind IS NOT NULL AND a_kind NOT IN('recall','montera_customer','montera_admin','pay_reminder','payout_delayed','winback_promo') THEN RAISE EXCEPTION 'invalid_notification_kind';END IF;
 SELECT j.id,j.kind,j.dedupe_key,j.payload,j.attempts,j.recipient_id INTO v FROM public.bot_notification_jobs j
 WHERE j.state='pending' AND j.attempts<j.max_attempts AND (a_kind IS NULL OR j.kind=a_kind)
 AND NOT EXISTS(SELECT 1 FROM public.bot_notification_recipient_revocations r WHERE r.recipient_id=j.recipient_id AND r.revoked)
 ORDER BY j.attempts,j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1;
 IF NOT FOUND THEN RETURN;END IF;v_token=pg_catalog.gen_random_uuid();v_claimed=clock_timestamp();
 UPDATE public.bot_notification_jobs j SET state='sending',attempts=j.attempts+1,claimed_at=v_claimed,updated_at=v_claimed,
  attempt_token=v_token,manual_reason_code=NULL WHERE j.id=v.id AND j.state='pending';
 IF NOT FOUND THEN RAISE EXCEPTION 'notification_claim_lost';END IF;
 INSERT INTO public.bot_notification_delivery_attempts(job_id,attempt_no,attempt_token,recipient_id,payload_sha256,claimed_at,claimant_principal)
 VALUES(v.id,v.attempts+1,v_token,v.recipient_id,encode(pg_catalog.sha256(pg_catalog.convert_to(v.payload::text,'UTF8')),'hex'),v_claimed,session_user);
 RETURN QUERY SELECT v.id,v.kind,v.dedupe_key,v.payload,v.attempts+1,v.recipient_id,v_token;
END$$;

GRANT USAGE ON SCHEMA public TO obsidian_exchange_bot_governance_owner,obsidian_exchange_bot_policy_approver,
 obsidian_exchange_bot_reconciler_owner,obsidian_exchange_bot_reconciler;
GRANT SELECT ON public.bot_notification_policy_versions,public.bot_notification_policy_approvals,
 public.bot_notification_policy_activation_events,public.bot_notification_policy_current TO obsidian_exchange_bot_governance_owner;
GRANT UPDATE(policy_id) ON public.bot_notification_policy_versions TO obsidian_exchange_bot_governance_owner;
GRANT UPDATE(approval_id) ON public.bot_notification_policy_approvals TO obsidian_exchange_bot_governance_owner;
GRANT INSERT ON public.bot_notification_policy_approvals,public.bot_notification_policy_activation_events TO obsidian_exchange_bot_governance_owner;
GRANT INSERT,UPDATE,DELETE ON public.bot_notification_policy_current TO obsidian_exchange_bot_governance_owner;
GRANT SELECT ON public.bot_notification_recipient_revocations,public.bot_notification_recipient_revocation_events TO obsidian_exchange_bot_reconciler_owner;
GRANT INSERT ON public.bot_notification_recipient_revocation_events,public.bot_notification_recipient_quarantines TO obsidian_exchange_bot_reconciler_owner;
GRANT INSERT,UPDATE ON public.bot_notification_recipient_revocations TO obsidian_exchange_bot_reconciler_owner;
GRANT SELECT(id,state,recipient_id,attempt_token),UPDATE(state,quarantine_event_id,quarantined_at)
 ON public.bot_notification_jobs TO obsidian_exchange_bot_reconciler_owner;
GRANT SELECT(recipient_id,revoked) ON public.bot_notification_recipient_revocations TO obsidian_exchange_bot_delivery_owner;
GRANT SELECT(recipient_id,revoked) ON public.bot_notification_recipient_revocations TO obsidian_exchange_bot_background_owner;
GRANT SELECT(recipient_id,revoked) ON public.bot_notification_recipient_revocations TO obsidian_exchange_bot_reconciler_owner;

ALTER FUNCTION public.bot_b60_append_only_guard() OWNER TO obsidian_exchange_bot_governance_owner;
ALTER FUNCTION public.bot_b60_approve_policy(uuid,bigint,text,text) OWNER TO obsidian_exchange_bot_governance_owner;
ALTER FUNCTION public.bot_b60_activate_policy(uuid,bigint,uuid,uuid,text) OWNER TO obsidian_exchange_bot_governance_owner;
ALTER FUNCTION public.bot_b60_set_recipient_revocation(bigint,text,uuid,text,text) OWNER TO obsidian_exchange_bot_reconciler_owner;
ALTER FUNCTION public.bot_b60_reject_revoked_recipient() OWNER TO obsidian_exchange_bot_reconciler_owner;
REVOKE ALL ON FUNCTION public.bot_b60_append_only_guard(),public.bot_b60_approve_policy(uuid,bigint,text,text),
 public.bot_b60_activate_policy(uuid,bigint,uuid,uuid,text),public.bot_b60_set_recipient_revocation(bigint,text,uuid,text,text),
 public.bot_b60_reject_revoked_recipient() FROM PUBLIC,obsidian_exchange_bot,
 obsidian_exchange_bot_background,obsidian_exchange_bot_delivery,obsidian_exchange_bot_transport;
GRANT EXECUTE ON FUNCTION public.bot_b60_approve_policy(uuid,bigint,text,text),
 public.bot_b60_activate_policy(uuid,bigint,uuid,uuid,text) TO obsidian_exchange_bot_policy_approver;
GRANT EXECUTE ON FUNCTION public.bot_b60_set_recipient_revocation(bigint,text,uuid,text,text)
 TO obsidian_exchange_bot_reconciler;
REVOKE ALL ON public.bot_notification_policy_approvals,public.bot_notification_policy_activation_events,
 public.bot_notification_recipient_revocation_events,public.bot_notification_recipient_revocations,
 public.bot_notification_recipient_quarantines FROM PUBLIC;
COMMIT;
