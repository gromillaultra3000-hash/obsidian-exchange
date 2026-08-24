import hashlib, json
from pathlib import Path
ROOT=Path('/root'); E=ROOT/'docs/e0-4-kairos-exchange-discovery-runtime-observation.v1.json'
def t(p): return Path(p).read_text(encoding='utf-8')
def test_hashes():
 d=json.loads(E.read_text());
 for x in d['deployedEntrypoints']: assert hashlib.sha256(Path(x['path']).read_bytes()).hexdigest()==x['sha256']
def test_auth_and_routes():
 s=t('/opt/kairos/app/main_v19.py'); assert 'len(configured) < 32' in s and 'secrets.compare_digest' in s
 for r in ('/api/exchange-registry/discover','/api/exchange-registry/{exchange_id}','/api/exchange-registry/{exchange_id}/build-draft'): assert r in s
def test_local_not_external_discovery():
 r=t('/opt/kairos/app/exchange_registry.py'); b=t('/opt/kairos/app/adapter_builder.py')
 assert all(x in r for x in ('"bybit"','"okx"','"kucoin"','"rapira"','ALIASES'))
 for x in ('import httpx','import requests','import urllib','import aiohttp','import ccxt'): assert x not in b
 assert 'liveExecutionEnabled": False' in b and '"withdrawal": "forbidden"' in b
def test_integrity_and_input_gaps():
 r=t('/opt/kairos/app/exchange_registry.py'); m=t('/opt/kairos/app/main_v19.py')
 assert 'except Exception:\n            return {"version": 1, "items": {}}' in r
 assert 'value[:64] or "unknown"' in r and 'tmp = self.path.with_suffix(".tmp")' in r
 cls=m[m.index('class ExchangeDiscoverIn'):m.index('@app.get("/api/exchange-registry")')]
 assert 'name: str' in cls and 'max_length' not in cls and 'pattern=' not in cls
def test_no_activation_boundary():
 m=t('/opt/kairos/app/main_v19.py'); a=t('/opt/kairos/app/adapter_builder.py')
 route=m[m.index('@app.post("/api/exchange-registry/discover")'):m.index('_start_cfg =')]
 for x in ('ConnectorService(','connect(','create_order','apiKey','secret_vault'): assert x not in route
 assert 'path": str(path)' in a
def test_adjacent_ready_status_overstates_proof_and_chat_is_effectful():
 m=t('/opt/kairos/app/main_v19.py')
 chat=m[m.index('@app.post("/api/chat")'):m.index('@app.get("/api/memory")')]
 assert 'REGISTRY.register' in chat and 'BUILDER.build_draft' in chat
 test=m[m.index('@app.post("/api/exchanges/test")'):m.index('class ExchangeDiscoverIn')]
 assert test.index('raise HTTPException(409') < test.index('status="READY"')
 assert 'load_markets' in test and 'fetch_balance' in test
 assert 'status="READY"' in test and 'spotTradePermission="read_trade_key_present"' in test
 assert 'create_order' not in test and 'fetch_permissions' not in test
def test_matrix():
 e=json.loads(E.read_text()); assert e['acceptance']=='PARTIAL_NOT_ACCEPTED' and set(e['surfaceMatrix'])=={'telegramBot','site','miniApp','admin','api','native'}
 assert e['authorityBoundary']['effectWriter'] is True and e['authorityBoundary']['moneyWriter'] is False
 assert e['observedEffectCallers']==['POST /api/chat'] and 'unconditional 409' in e['dormantUnreachableWriterSources'][0]
 assert e['coverageConclusion']['e0_4Complete'] is False
 assert any('post-expansion closure rescan' in x for x in e['limitations'])
 m=json.loads((ROOT/'docs/e0-4-feature-status-surface-matrix.v1.json').read_text()); ids=[x['id'] for x in m['features']]
 assert len(ids)==len(set(ids))==25 and m['omittedFeatureFamilies']==[]
 row=next(x for x in m['features'] if x['id']=='KAIROS_EXCHANGE_DISCOVERY'); assert row['overallStatus']=='PARTIAL_NOT_ACCEPTED' and row['effectWriter'] is True
 assert any('post-expansion closure rescan' in x for x in m['limitations'])
 assert m['nextCanonicalItem'].startswith('Return to owner-blocked E0.3 as the first unmet criterion')
