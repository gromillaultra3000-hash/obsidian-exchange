import hashlib
import json
from pathlib import Path

ROOT = Path('/root')
EVIDENCE = ROOT / 'docs/e0-4-customer-engagement-runtime-observation.v1.json'

def _text(path): return Path(path).read_text(encoding='utf-8')

def test_deployed_hashes_match():
    data=json.loads(EVIDENCE.read_text())
    for item in data['deployedEntrypoints']:
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['sha256']

def test_default_marketing_has_no_recorded_affirmative_consent():
    schema=_text('/opt/obsidian-exchange/deploy/postgres/011_user_profiles.sql')
    profiles=_text('/opt/obsidian-exchange/relay/repositories/user_profile_store.py')
    assert 'broadcast_enabled BOOLEAN NOT NULL DEFAULT true' in schema
    assert 'consent' not in schema.lower() and 'broadcast_enabled' not in profiles

def test_broadcast_paths_bypass_preference():
    bot=_text('/opt/obsidian-exchange/bot/main_bot.py')
    manual=bot[bot.index('async def cmd_broadcast'):bot.index('@router.message(Command("stats"))')]
    feature=bot[bot.index('async def feature_broadcast(target_id'):bot.index('_BROADCAST_INTERVAL')]
    assert 'active_customer_ids(days=30)' in manual and 'broadcast_user_ids' not in manual
    assert 'order_customer_ids()' in feature and 'broadcast_user_ids' not in feature
    reads=_text('/opt/obsidian-exchange/relay/repositories/order_read_store.py')
    assert 'def active_customer_ids' in reads
    assert '"SELECT user_id FROM orders WHERE user_id>0 "' in reads and 'GROUP BY user_id' in reads

def test_rate_alert_is_explicit_but_not_global_suppression():
    bot=_text('/opt/obsidian-exchange/bot/main_bot.py')
    assert 'callback_data="rate_sub_toggle"' in bot and '_engagement.toggle_rate(uid)' in bot
    assert 'MIN_INTERVAL    = 86400' in bot and 'CHANGE_THRESHOLD = 0.05' in bot

def test_first_rate_toggle_inverts_default_true():
    schema=_text('/opt/obsidian-exchange/deploy/postgres/020_legacy_runtime.sql')
    store=_text('/opt/obsidian-exchange/relay/repositories/engagement_store.py')
    assert 'enabled BOOLEAN DEFAULT true' in schema
    assert 'INSERT INTO rate_subscriptions(user_id)' in store and 'SET enabled=NOT enabled' in store

def test_durable_jobs_are_deduped_but_stuck_sending_has_no_recovery():
    store=_text('/opt/obsidian-exchange/relay/repositories/bot_notification_store.py')
    schema=_text('/opt/obsidian-exchange/deploy/postgres/023_bot_notification_jobs.sql')
    assert 'UNIQUE(kind,dedupe_key)' in schema and "state IN('pending','sending','sent')" in schema
    assert "SET state='sending',attempts=attempts+1" in store
    assert 'lease' not in store.lower() and 'dead_letter' not in store.lower()

def test_job_payload_retains_payment_bearer_without_expiry_or_purge():
    store=_text('/opt/obsidian-exchange/relay/repositories/bot_notification_store.py')
    schema=_text('/opt/obsidian-exchange/deploy/postgres/023_bot_notification_jobs.sql')
    abandoned=store[store.index('def queue_due_abandoned'):store.index('def queue_due_payout_delays')]
    assert 'session_token=row["session_token"]' in abandoned
    assert 'expires_at' not in schema and 'deleted' not in schema and 'purge' not in store.lower()

def test_winback_creates_money_discount_without_broadcast_preference():
    store=_text('/opt/obsidian-exchange/relay/repositories/bot_notification_store.py')
    body=store[store.index('def queue_due_winbacks'):store.index('# Single-candidate methods')]
    assert 'INSERT INTO promo_codes' in body and "event='winback_promo'" in body
    assert 'broadcast_enabled' not in body

def test_personal_winback_is_not_recipient_bound_and_is_logged():
    promos=_text('/opt/obsidian-exchange/relay/repositories/promo_admin_store.py')
    bot=_text('/opt/obsidian-exchange/bot/main_bot.py')
    validate=promos[promos.index('def validate_for_user'):promos.index('def active')]
    assert 'promo_uses' in validate and 'target_user' not in validate
    assert 'logger.info(f"winback: промо {code} → user {uid} (order {oid})")' in bot

def test_review_publication_lacks_separate_consent_and_finalize_owner():
    bot=_text('/opt/obsidian-exchange/bot/main_bot.py')
    engagement=_text('/opt/obsidian-exchange/relay/repositories/engagement_store.py')
    final=bot[bot.index('async def finalize_review(order_id)'):bot.index('# ---------- ОБМЕН ----------')]
    assert 'REVIEWS_CHANNEL_ID' in final and 'publication_consent' not in final
    assert 'def finalize_review(self,order_id)' in engagement

def test_promo_order_consumption_is_atomic_but_not_full_lifecycle():
    store=_text('/opt/obsidian-exchange/relay/repositories/bot_order_store.py')
    assert 'INSERT INTO promo_uses' in store and 'uses_count=uses_count+1' in store
    assert 'promo_used' in store and 'agreed_rate' in store

def test_fifth_exchange_uses_legacy_status_without_entitlement_claim():
    engagement=_text('/opt/obsidian-exchange/relay/repositories/engagement_store.py')
    bot=_text('/opt/obsidian-exchange/bot/main_bot.py')
    reconciliation=_text('/opt/obsidian-exchange/relay/repositories/reconciliation_store.py')
    assert "status='completed'" in engagement
    assert "status='sent'" in reconciliation
    body=bot[bot.index('async def _finalize_rub_amount'):bot.index('@router.callback_query(F.data.startswith("amtpreset_"))')]
    assert 'amount = max(amount - 1000, MIN_AMOUNT)' in body and 'claim' not in body.lower()

def test_promo_admin_and_schema_lack_finite_upper_bounds():
    bot=_text('/opt/obsidian-exchange/bot/main_bot.py')
    schema=_text('/opt/obsidian-exchange/deploy/postgres/013_promos.sql')
    command=bot[bot.index('async def cmd_addpromo'):bot.index('@router.message(Command("promos"))')]
    assert 'float(parts[2])' in command and 'isfinite' not in command
    assert 'discount_percent>=0' in schema and 'discount_percent<=' not in schema

def test_review_skip_and_store_finalization_are_not_owner_bound():
    bot=_text('/opt/obsidian-exchange/bot/main_bot.py')
    engagement=_text('/opt/obsidian-exchange/relay/repositories/engagement_store.py')
    skip=bot[bot.index('async def skip_review_comment'):bot.index('@router.message(Review.comment)')]
    assert 'finalize_review(order_id)' in skip and 'callback.from_user.id' not in skip
    assert 'def comment_review(self,order_id,comment)' in engagement
    assert 'def finalize_review(self,order_id)' in engagement

def test_six_surfaces_and_non_acceptance():
    data=json.loads(EVIDENCE.read_text())
    assert data['acceptance']=='PARTIAL_NOT_ACCEPTED'
    assert set(data['surfaceMatrix'])=={'telegramBot','site','miniApp','admin','api','native'}
    assert data['coverageConclusion']['consentLifecycleAccepted'] is False
    assert data['coverageConclusion']['loyaltyMoneyAuthorityAccepted'] is False
    assert all(not v for v in data['observationSafety'].values())

def test_matrix_has_exact_customer_engagement_row_and_next_omissions():
    matrix=json.loads((ROOT/'docs/e0-4-feature-status-surface-matrix.v1.json').read_text())
    ids=[item['id'] for item in matrix['features']]
    assert len(ids)==len(set(ids))==25
    row=next(item for item in matrix['features'] if item['id']=='CUSTOMER_ENGAGEMENT')
    assert row['overallStatus']=='PARTIAL_NOT_ACCEPTED' and row['moneyWriter'] is True
    assert set(row['cells'])=={'telegramBot','site','miniApp','admin','api','native'}
    assert matrix['omittedFeatureFamilies']==[]
    assert matrix['nextCanonicalItem'].startswith('Return to owner-blocked E0.3')
