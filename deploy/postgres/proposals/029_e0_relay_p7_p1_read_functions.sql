-- E0.3 PROPOSAL ONLY. Run only after 028 in disposable PostgreSQL 17.
-- Production-equivalent bodies for P7 runtime metadata and P1 public aggregates.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='obsidian_relay_metadata_owner') THEN
    CREATE ROLE obsidian_relay_metadata_owner NOLOGIN NOSUPERUSER NOCREATEDB
      NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
END $$;
ALTER ROLE obsidian_relay_metadata_owner NOLOGIN PASSWORD NULL NOSUPERUSER
  NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
REVOKE ALL ON SCHEMA public FROM obsidian_relay_metadata_owner;
GRANT USAGE ON SCHEMA public TO obsidian_relay_metadata_owner;

-- The metadata owner deliberately receives no business relation privilege.
-- pg_catalog is used because information_schema.columns hides relations from a
-- role that cannot SELECT them, making that view unsuitable for this boundary.
CREATE OR REPLACE FUNCTION public.relay_runtime_schema_validate_shared()
RETURNS TABLE(missing_relation text,missing_columns text[])
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
  WITH required(relation_name,column_name) AS (VALUES
    ('alert_throttle','key'),('alert_throttle','last_sent'),
    ('alert_watermark','key'),('alert_watermark','value'),
    ('system_flags','key'),('system_flags','value'),('system_flags','updated_at'),
    ('audit_log','id'),('audit_log','event'),('audit_log','details'),
    ('audit_log','created_at'),
    ('provider_health','provider'),('provider_health','avg_response_time'),
    ('provider_health','failed_count'),('provider_health','last_checked'),
    ('provider_health','is_healthy'),('provider_health','status'),
    ('provider_health','blocker'),
    ('provider_attempts','provider'),('provider_attempts','ts'),
    ('provider_attempts','success'),
    ('wallet_links','user_id'),('wallet_links','chain'),
    ('wallet_links','address'),('wallet_links','verified_at'),
    ('wallet_send_intents','id'),('wallet_send_intents','user_id'),
    ('wallet_send_intents','chain'),('wallet_send_intents','sell_id'),
    ('wallet_send_intents','from_address'),('wallet_send_intents','to_address'),
    ('wallet_send_intents','amount'),('wallet_send_intents','marker'),
    ('wallet_send_intents','created_at'),('wallet_send_intents','signed_at'),
    ('payment_transition_audit','id'),('payment_transition_audit','order_id'),
    ('payment_transition_audit','provider'),('payment_transition_audit','action'),
    ('payment_transition_audit','from_status'),('payment_transition_audit','to_status'),
    ('payment_transition_audit','evidence'),('payment_transition_audit','created_at'),
    ('payment_notification_outbox','id'),('payment_notification_outbox','order_id'),
    ('payment_notification_outbox','recipient_id'),('payment_notification_outbox','payload'),
    ('payment_notification_outbox','state'),('payment_notification_outbox','attempts'),
    ('payment_notification_outbox','created_at'),('payment_notification_outbox','claimed_at'),
    ('payment_notification_outbox','sent_at'),('payment_notification_outbox','updated_at'),
    ('payout_reconciliations','order_id'),('payout_reconciliations','intent_id'),
    ('payout_reconciliations','txid'),('payout_reconciliations','referral_btc'),
    ('payout_reconciliations','vip_rub'),('payout_reconciliations','reconciled_at'),
    ('notification_outbox','id'),('notification_outbox','topic'),
    ('notification_outbox','aggregate_id'),('notification_outbox','recipient_id'),
    ('notification_outbox','payload'),('notification_outbox','state'),
    ('notification_outbox','attempts'),('notification_outbox','created_at'),
    ('notification_outbox','claimed_at'),('notification_outbox','sent_at'),
    ('notification_outbox','updated_at'),
    ('client_address_notes','user_id'),('client_address_notes','currency'),
    ('client_address_notes','network'),('client_address_notes','address'),
    ('client_address_notes','label'),('client_address_notes','hidden'),
    ('client_address_notes','updated_at'),
    ('payout_shadow','order_id'),('payout_shadow','decided_at'),
    ('payout_shadow','verdict'),('payout_shadow','detail'),
    ('payout_shadow','provider'),('payout_shadow','circuit_action'),
    ('payout_shadow','would_auto_pay'),('payout_shadow','rub_amount'),
    ('payout_shadow','currency'),('payout_shadow','outcome'),
    ('payout_shadow','outcome_at'),
    ('order_lifecycle_work','id'),('order_lifecycle_work','kind'),
    ('order_lifecycle_work','order_id'),('order_lifecycle_work','session_token'),
    ('order_lifecycle_work','provider'),('order_lifecycle_work','provider_invoice_id'),
    ('order_lifecycle_work','user_id'),('order_lifecycle_work','currency'),
    ('order_lifecycle_work','rub_amount'),('order_lifecycle_work','order_status'),
    ('order_lifecycle_work','has_receipt'),('order_lifecycle_work','detail'),
    ('order_lifecycle_work','state'),('order_lifecycle_work','attempts'),
    ('order_lifecycle_work','created_at'),('order_lifecycle_work','claimed_at'),
    ('order_lifecycle_work','completed_at'),('order_lifecycle_work','updated_at'),
    ('payout_intents','id'),('payout_intents','order_id'),('payout_intents','idempotency_key'),
    ('payout_intents','state'),('payout_intents','source'),('payout_intents','requested_by'),
    ('payout_intents','rub_amount'),('payout_intents','crypto_amount'),
    ('payout_intents','currency'),('payout_intents','network'),
    ('payout_intents','destination'),('payout_intents','attempts'),
    ('payout_intents','txid'),('payout_intents','error_code'),
    ('payout_intents','created_at'),('payout_intents','claimed_at'),
    ('payout_intents','finished_at'),('payout_intents','updated_at'),
    ('payout_intent_audit','id'),('payout_intent_audit','order_id'),
    ('payout_intent_audit','actor'),('payout_intent_audit','action'),
    ('payout_intent_audit','from_state'),('payout_intent_audit','to_state'),
    ('payout_intent_audit','evidence'),('payout_intent_audit','txid'),
    ('payout_intent_audit','created_at'),
    ('referral_payout_intents','id'),('referral_payout_intents','user_id'),
    ('referral_payout_intents','idempotency_key'),('referral_payout_intents','state'),
    ('referral_payout_intents','crypto_amount'),('referral_payout_intents','currency'),
    ('referral_payout_intents','network'),('referral_payout_intents','destination'),
    ('referral_payout_intents','attempts'),('referral_payout_intents','txid'),
    ('referral_payout_intents','error_code'),('referral_payout_intents','created_at'),
    ('referral_payout_intents','claimed_at'),('referral_payout_intents','finished_at'),
    ('referral_payout_intents','updated_at'),
    ('referral_payout_intent_audit','id'),('referral_payout_intent_audit','intent_id'),
    ('referral_payout_intent_audit','actor'),('referral_payout_intent_audit','action'),
    ('referral_payout_intent_audit','from_state'),('referral_payout_intent_audit','to_state'),
    ('referral_payout_intent_audit','evidence'),('referral_payout_intent_audit','txid'),
    ('referral_payout_intent_audit','created_at'),
    ('sell_settlement_ledger','sell_id'),('sell_settlement_ledger','user_id'),
    ('sell_settlement_ledger','rub_amount'),('sell_settlement_ledger','payout_provider'),
    ('sell_settlement_ledger','payout_ref'),('sell_settlement_ledger','payout_status'),
    ('sell_settlement_ledger','settled_at'),
    ('sell_settlement_outbox','id'),('sell_settlement_outbox','sell_id'),
    ('sell_settlement_outbox','recipient_id'),('sell_settlement_outbox','rub_amount'),
    ('sell_settlement_outbox','state'),('sell_settlement_outbox','attempts'),
    ('sell_settlement_outbox','created_at'),('sell_settlement_outbox','claimed_at'),
    ('sell_settlement_outbox','sent_at'),('sell_settlement_outbox','updated_at'),
    ('order_receipts','order_id'),('order_receipts','path'),
    ('order_receipts','filename'),('order_receipts','content_type'),
    ('order_receipts','created_at'),('order_receipts','dispute_opened_at'),
    ('order_receipts','sha256'),
    ('orders','order_id'),('orders','user_id'),('orders','username'),
    ('orders','currency'),('orders','rub_amount'),('orders','crypto_address'),
    ('orders','status'),('orders','created_at'),('orders','updated_at'),
    ('orders','network'),('orders','agreed_rate'),('orders','agreed_crypto_amount'),
    ('orders','agreed_at'),('orders','paid_btc_tx'),('orders','web_user_id'),
    ('orders','rub_volume_counted'),('orders','verification_requested'),
    ('orders','montera_invoice_id'),('orders','receipt_sent_at'),
    ('orders','receipt_deadline'),
    ('sell_orders','id'),('sell_orders','user_id'),('sell_orders','currency'),
    ('sell_orders','crypto_amount'),('sell_orders','rub_amount'),
    ('sell_orders','sbp_phone'),('sell_orders','receive_address'),
    ('sell_orders','status'),('sell_orders','tx_hash'),('sell_orders','created_at'),
    ('sell_orders','updated_at'),('sell_orders','payout_method'),
    ('sell_orders','payout_bank'),('sell_orders','payout_details'),
    ('sell_orders','payout_name'),('sell_orders','payout_provider'),
    ('sell_orders','payout_ref'),('sell_orders','payout_status'),
    ('sent_notifications','order_id'),('sent_notifications','event')
  ), missing AS (
    SELECT r.relation_name,r.column_name FROM required r
    WHERE NOT EXISTS (
      SELECT 1 FROM pg_catalog.pg_namespace n
      JOIN pg_catalog.pg_class c ON c.relnamespace=n.oid
      JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid
      WHERE n.nspname='public' AND c.relname=r.relation_name
        AND c.relkind IN ('r','p') AND a.attname=r.column_name
        AND a.attnum>0 AND NOT a.attisdropped
    )
  )
  SELECT relation_name,array_agg(column_name ORDER BY column_name)
  FROM missing GROUP BY relation_name ORDER BY relation_name
$$;

CREATE OR REPLACE FUNCTION public.relay_reporting_public_stats()
RETURNS TABLE(exchanges_today bigint,exchanges_total bigint,
              volume_24h numeric(20,2),volume_total numeric(20,2))
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
  SELECT count(o.order_id) FILTER(WHERE o.created_at>=CURRENT_DATE),
         count(o.order_id),
         COALESCE(sum(o.rub_amount) FILTER(
           WHERE o.created_at>transaction_timestamp()-interval '1 day'),0)::numeric(20,2),
         COALESCE(sum(o.rub_amount),0)::numeric(20,2)
  FROM public.orders o WHERE o.status='sent'
$$;

CREATE OR REPLACE FUNCTION public.relay_reporting_reserves(p_positive_only boolean DEFAULT false)
RETURNS TABLE(currency text,amount numeric(30,12))
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF p_positive_only IS NULL THEN RAISE EXCEPTION 'positive_only_required'; END IF;
  RETURN QUERY SELECT r.currency,r.amount::numeric(30,12) FROM public.reserves r
    WHERE NOT p_positive_only OR r.amount>0 ORDER BY r.currency LIMIT 64;
END $$;

CREATE OR REPLACE FUNCTION public.relay_reporting_site_stats()
RETURNS TABLE(total bigint,completed bigint,attempted bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
  SELECT count(o.order_id),
         count(o.order_id) FILTER(WHERE o.status IN ('paid','sent')),
         count(o.order_id) FILTER(WHERE o.status IN ('paid','sent','failed'))
  FROM public.orders o
$$;

CREATE OR REPLACE FUNCTION public.relay_reporting_today_status_counts()
RETURNS TABLE(total bigint,pending bigint,completed bigint,expired bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog SET TimeZone='UTC' AS $$
  SELECT count(o.order_id),
         count(o.order_id) FILTER(WHERE o.status='pending'),
         count(o.order_id) FILTER(WHERE o.status IN ('paid','sent')),
         count(o.order_id) FILTER(WHERE o.status='expired')
  FROM public.orders o
  WHERE o.created_at>=CURRENT_DATE AND o.created_at<CURRENT_DATE+interval '1 day'
$$;

ALTER FUNCTION public.relay_runtime_schema_validate_shared() OWNER TO obsidian_relay_metadata_owner;
ALTER FUNCTION public.relay_reporting_public_stats() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_reporting_reserves(boolean) OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_reporting_site_stats() OWNER TO obsidian_relay_owner;
ALTER FUNCTION public.relay_reporting_today_status_counts() OWNER TO obsidian_relay_owner;

GRANT SELECT(order_id,status,created_at,rub_amount) ON public.orders TO obsidian_relay_owner;
GRANT SELECT(currency,amount) ON public.reserves TO obsidian_relay_owner;

REVOKE ALL ON FUNCTION public.relay_runtime_schema_validate_shared() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_reporting_public_stats() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_reporting_reserves(boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_reporting_site_stats() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.relay_reporting_today_status_counts() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.relay_runtime_schema_validate_shared() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_reporting_public_stats() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_reporting_reserves(boolean) TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_reporting_site_stats() TO obsidian_relay;
GRANT EXECUTE ON FUNCTION public.relay_reporting_today_status_counts() TO obsidian_relay;

DO $$
BEGIN
  IF has_table_privilege('obsidian_relay_metadata_owner','public.orders','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.sell_orders','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.sent_notifications','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.alert_throttle','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.alert_watermark','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.order_receipts','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.system_flags','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.audit_log','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.provider_health','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.provider_attempts','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.wallet_links','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.wallet_send_intents','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.payment_transition_audit','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.payment_notification_outbox','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.payout_reconciliations','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.notification_outbox','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.client_address_notes','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.payout_shadow','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.order_lifecycle_work','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.payout_intents','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.payout_intent_audit','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.referral_payout_intents','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.referral_payout_intent_audit','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.sell_settlement_ledger','SELECT')
     OR has_table_privilege('obsidian_relay_metadata_owner','public.sell_settlement_outbox','SELECT') THEN
    RAISE EXCEPTION 'metadata_owner_business_select';
  END IF;
  IF has_table_privilege('obsidian_relay','public.orders','SELECT')
     OR has_table_privilege('obsidian_relay','public.reserves','SELECT') THEN
    RAISE EXCEPTION 'relay_direct_public_read';
  END IF;
END $$;
