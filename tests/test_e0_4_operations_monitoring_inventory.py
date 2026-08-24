import hashlib
import json
from pathlib import Path

ROOT=Path('/root')
EVIDENCE=ROOT/'docs/e0-4-operations-monitoring-runtime-observation.v1.json'
def text(path): return Path(path).read_text(encoding='utf-8')

def test_deployed_hashes_match():
    data=json.loads(EVIDENCE.read_text())
    for item in data['deployedEntrypoints']:
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['sha256']

def test_effective_unit_is_active_root_and_has_no_watchdog():
    data=json.loads(EVIDENCE.read_text())['runtimeObservation']
    unit=text('/etc/systemd/system/obsidian-monitor.service')
    assert data['active'] and data['enabled'] and data['principal']=='root'
    assert 'User=root' in unit and 'Restart=always' in unit and 'WatchdogSec' not in unit
    assert '/opt/obsidian-exchange/monitoring/monitor.py' in text('/etc/systemd/system/obsidian-monitor.service.d/runtime-paths.conf')

def test_check_errors_can_become_false_green():
    monitor=text('/opt/obsidian-exchange/monitoring/monitor.py')
    assert monitor.count('issues = []')>=4
    assert 'except Exception as e:\n        logger.error("check_stuck_orders error: %s", e)' in monitor
    assert 'if all_issues:' in monitor and 'logger.info("All checks passed")' in monitor

def test_alert_delivery_has_no_durable_lifecycle():
    monitor=text('/opt/obsidian-exchange/monitoring/monitor.py')
    body=monitor[monitor.index('async def send_alert'):monitor.index('async def check_stuck_orders')]
    assert 'client.post' in body and 'resp.status_code != 200' in body
    for term in ('outbox','idempotency','ambiguous','acknowledged','escalation'):
        assert term not in body.lower()

def test_public_status_is_one_provider_green_without_freshness():
    relay=text('/opt/obsidian-exchange/relay-fastapi/main.py')
    body=relay[relay.index('@app.get("/api/system-status")'):relay.index('# --- Обработчики ошибок ---')]
    assert '"operational" if healthy_count > 0 else "degraded"' in body
    assert '_reporting.today_status_counts()' in body
    assert all(term not in body for term in ('observed_at','as_of','freshness','payout_worker','backup'))
    web=text('/opt/obsidian-exchange/relay/webapp.html')
    assert 'Все системы работают — платежи принимаются' in web

def test_monitoring_scope_excludes_effect_writers_but_records_blur():
    data=json.loads(EVIDENCE.read_text())
    assert data['authorityBoundary']['controlExclusion'].startswith('Dispute opening')
    relay=text('/opt/obsidian-exchange/relay-fastapi/main.py')
    assert 'async def dispute_watch_task' in relay and 'async def payout_shadow_task' in relay
    assert 'run_once' in relay and 'record_pending' in relay and 'sync_outcomes' in relay
    bot=text('/opt/obsidian-exchange/bot/main_bot.py')
    assert 'asyncio.create_task(auto_check_payments())' in bot
    auto=bot[bot.index('async def auto_check_payments'):bot.index('async def swap_status_monitor')]
    assert 'payout_circuit.freeze' in auto and 'process_payout_async' in auto
    router=text('/opt/obsidian-exchange/relay/services/smart_router.py')
    assert 'def record_outcome' in router and 'is_healthy' in router and 'in_cooldown' in router
    assert data['coverageConclusion']['monitoringAuthorityAccepted'] is False

def test_backup_check_is_age_and_size_not_restore_proof():
    bot=text('/opt/obsidian-exchange/bot/main_bot.py')
    body=bot[bot.index('async def verify_backups'):bot.index('# ---------- МОНИТОРИНГ SSL')]
    assert "glob.glob('/root/backups/*.tar.gz')" in body
    assert 'os.path.getmtime' in body and 'os.path.getsize' in body
    assert 'restore' not in body.lower() and 'decrypt' not in body.lower()
    smoke=text('/opt/obsidian-exchange/deploy/postgres/backup_restore_smoke.py')
    runbook=text('/opt/obsidian-exchange/docs/postgresql-cutover-runbook.md')
    assert 'temporary' in smoke.lower() or 'mkdtemp' in smoke
    assert 'backup_restore_smoke.py' in runbook
    backup=text('/etc/systemd/system/kairos-shadow-backup.service')
    verify=text('/etc/systemd/system/kairos-shadow-verify.service')
    assert 'shadow' in backup.lower() and 'shadow' in verify.lower()
    assert 'postgres' not in backup.lower() and 'postgres' not in verify.lower()

def test_raw_audit_ssl_false_pass_and_custody_blur_are_explicit():
    relay=text('/opt/obsidian-exchange/relay-fastapi/main.py')
    assert 'str(data)' in relay and 'audit_log' in relay and 'email' in relay
    assert '_ops_store.cleanup_audit(90)' in relay
    bot=text('/opt/obsidian-exchange/bot/main_bot.py')
    ssl=bot[bot.index('async def ssl_healthcheck'):bot.index('@router.message(Command("approve"))')]
    assert 'result.stderr.decode()' in ssl and 'notAfter=' in ssl
    assert 'returncode' not in ssl and 'if not match' not in ssl
    balance=bot[bot.index('async def balance_monitor'):bot.index('@router.message(Command("testpost"))')]
    assert "os.getenv('USDT_PRIVATE_KEY')" in balance and 'PrivateKey(' in balance

def test_six_surfaces_non_acceptance_and_exact_matrix_progression():
    data=json.loads(EVIDENCE.read_text())
    assert data['acceptance']=='PARTIAL_NOT_ACCEPTED'
    assert set(data['surfaceMatrix'])=={'telegramBot','site','miniApp','admin','api','native'}
    assert all(not value for value in data['observationSafety'].values())
    matrix=json.loads((ROOT/'docs/e0-4-feature-status-surface-matrix.v1.json').read_text())
    ids=[row['id'] for row in matrix['features']]
    assert len(ids)==len(set(ids))==25
    row=next(row for row in matrix['features'] if row['id']=='OPERATIONS_MONITORING')
    assert row['overallStatus']=='PARTIAL_NOT_ACCEPTED'
    assert row['moneyWriter'] is False and row['moneyAdjacent'] is True and row['effectWriterExcluded'] is True
    assert set(row['cells'])=={'telegramBot','site','miniApp','admin','api','native'}
    assert matrix['omittedFeatureFamilies']==[]
    assert matrix['nextCanonicalItem'].startswith('Return to owner-blocked E0.3')
