-- REHEARSAL ONLY. Pre-v2-submit rollback; run with autocommit.
DROP INDEX CONCURRENTLY IF EXISTS public.bot_notification_evidence_v2_provider_message_unique;
DROP INDEX CONCURRENTLY IF EXISTS public.bot_notification_evidence_v2_provider_request_unique;
DROP INDEX CONCURRENTLY IF EXISTS public.bot_notification_jobs_v2_pending_idx;
