import hashlib
import json
from pathlib import Path

ROOT=Path('/root')
EVIDENCE=ROOT/'docs/e0-4-ai-assistant-runtime-observation.v1.json'
def text(path): return Path(path).read_text(encoding='utf-8')

def test_deployed_hashes_match():
    data=json.loads(EVIDENCE.read_text())
    for item in data['deployedEntrypoints']:
        assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['sha256']

def test_customer_ai_is_public_loopback_text_only_without_tools():
    main=text('/opt/obsidian-exchange/relay-fastapi/main.py')
    ai=text('/opt/obsidian-exchange/relay-fastapi/ai_support.py')
    web=text('/opt/obsidian-exchange/relay/webapp.html')
    route=main[main.index('@app.post("/api/ai-ask")'):main.index('@app.get("/admin/analytics/data")')]
    assert 'get_web_user' not in route and 'verify_init_data' not in route
    assert 'http://localhost:11434/api/generate' in ai and 'qwen2:1.5b' in ai
    for forbidden in ('order_store','payment','payout','wallet','tool','broadcast','lumi','kairos'):
        assert forbidden not in ai.lower()
    assert web.count('.textContent =')>2 and "fetch('/api/ai-ask'" in web

def test_prompt_truth_conflicts_are_explicit():
    ai=text('/opt/obsidian-exchange/relay-fastapi/ai_support.py')
    main=text('/opt/obsidian-exchange/relay-fastapi/main.py')
    assert 'Минимум: 1000 ₽' in ai and "MIN_AMOUNT = float(os.getenv('MIN_AMOUNT', 2000))" in main
    assert 'Реферальная программа: 0.5% от каждого обмена реферала' in ai
    assert "REFERRAL_BONUS_PERCENT = float(os.getenv('REFERRAL_BONUS_PERCENT', 10))" in main

def test_input_error_and_stream_contract_are_not_strict():
    main=text('/opt/obsidian-exchange/relay-fastapi/main.py')
    ai=text('/opt/obsidian-exchange/relay-fastapi/ai_support.py')
    web=text('/opt/obsidian-exchange/relay/webapp.html')
    route=main[main.index('@app.post("/api/ai-ask")'):main.index('@app.get("/admin/analytics/data")')]
    assert 'str(body.get("question", ""))[:500]' in route
    assert 'f"Ошибка: {e}"' in route
    stream=ai[ai.index('else:\n        async def gen()'):]
    assert 'raise_for_status' not in stream and 'except Exception:\n                                pass' in stream
    client=web[web.index('async function sendAiQuestion'):web.index('// Валидация крипто-адреса')]
    assert "dec.decode(value).split('\\n')" in client
    assert 'resp.ok' not in client and 'resp.headers' not in client

def test_privacy_copy_and_no_sensitive_input_warning():
    web=text('/opt/obsidian-exchange/relay/webapp.html')
    panel=web[web.index('🤖 Спросить AI-помощника'):web.index('<div class="panel" id="panel-admin">')]
    assert 'данные не передаются' in panel
    for warning in ('seed','private key','приватн','чек','реквизит','персональ'):
        assert warning not in panel.lower()

def test_edge_rate_limit_is_generic_not_ai_admission():
    nginx=text('/etc/nginx/sites-available/obsidian-exchange.org')
    conf=text('/etc/nginx/nginx.conf')
    assert 'location /api/' in nginx and 'limit_req zone=api burst=15 nodelay' in nginx
    assert 'zone=api:10m rate=30r/m' in conf
    assert 'ai-ask' not in nginx and 'limit_conn' not in nginx

def test_model_manifest_present_but_runtime_access_not_proven():
    manifest=json.loads(text('/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library/qwen2/1.5b'))
    assert manifest['schemaVersion']==2 and any(layer['mediaType']=='application/vnd.ollama.image.model' for layer in manifest['layers'])
    unit=text('/etc/systemd/system/ollama.service')
    assert 'User=ollama' in unit and 'ExecStart=/usr/local/bin/ollama serve' in unit
    data=json.loads(EVIDENCE.read_text())
    assert data['runtimeObservation']['modelRuntimeReady'] is False

def test_scope_does_not_conflate_lumi_or_kairos():
    data=json.loads(EVIDENCE.read_text())
    assert data['scopeBoundary']['included'].startswith('The customer-facing Relay')
    assert 'KAIROS' in data['scopeBoundary']['excluded'] and 'LUMI' in data['scopeBoundary']['excluded']
    assert data['coverageConclusion']['moneyWriterPresent'] is False
    assert data['coverageConclusion']['advisoryAuthorityAccepted'] is False

def test_telegram_has_no_model_handler_and_admin_insights_are_deterministic():
    bot=text('/opt/obsidian-exchange/bot/main_bot.py')
    assert '/api/ai-ask' not in bot and 'OLLAMA_URL' not in bot and 'qwen2:1.5b' not in bot
    admin=text('/opt/obsidian-exchange/relay-fastapi/templates/admin_analytics.html')
    assert 'AI-инсайты' in admin and 'renderInsights' in admin
    for marker in ('/api/ai-ask','OLLAMA_URL','qwen2:1.5b','/api/generate'):
        assert marker not in admin

def test_six_surfaces_and_matrix_progression():
    data=json.loads(EVIDENCE.read_text())
    assert data['acceptance']=='PARTIAL_NOT_ACCEPTED'
    assert set(data['surfaceMatrix'])=={'telegramBot','site','miniApp','admin','api','native'}
    assert all(not value for value in data['observationSafety'].values())
    matrix=json.loads((ROOT/'docs/e0-4-feature-status-surface-matrix.v1.json').read_text())
    ids=[row['id'] for row in matrix['features']]
    assert len(ids)==len(set(ids))==25
    row=next(row for row in matrix['features'] if row['id']=='AI_ASSISTANT')
    assert row['overallStatus']=='PARTIAL_NOT_ACCEPTED' and row['moneyWriter'] is False
    assert row['moneyAdjacent'] is True and row['effectWriterExcluded'] is True
    assert set(row['cells'])=={'telegramBot','site','miniApp','admin','api','native'}
    assert matrix['omittedFeatureFamilies']==[]
    assert matrix['nextCanonicalItem'].startswith('Return to owner-blocked E0.3')
