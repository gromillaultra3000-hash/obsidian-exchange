import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
B=json.loads((ROOT/'docs/e0-3-bot-connection-budget.v1.json').read_text())

def test_budget_arithmetic_and_headroom():
 pg=B['postgresObservation']; runtime=B['enforcedRuntimeBound']; decision=B['decision']
 assert pg['ordinaryClientCapacity']==pg['maxConnections']-pg['reservedConnections']-pg['superuserReservedConnections']==97
 assert runtime['defaultExecutorWorkers']==min(32,B['topology']['hostLogicalCpus']+4)==6
 assert runtime['maximumBotClientConnections']==runtime['processes']*(runtime['defaultExecutorWorkers']+runtime['synchronousEventLoopSlots'])*runtime['connectionsPerCallingThread']==7
 assert decision['connectionLimit']==10 and decision['operationalHeadroom']==3
 assert decision['ordinaryCapacityAfterBotLimit']==87
 assert pg['ordinaryClientCapacity']>=2*decision['connectionLimit']

def test_budget_is_nonproduction_and_fails_closed_on_topology_change():
 assert B['productionAuthorization'] is B['implementationDeployed'] is False
 assert B['status']=='MEASURED_ENVELOPE_NOT_DEPLOYED'
 stops=' '.join(B['stopConditions'])
 assert 'process count' in stops and 'CPU count' in stops
 assert 'retain or nest' in stops and 'connection pool' in stops
 assert B['topology']['osPrincipal']=='root'

def test_repository_sources_have_no_implicit_pool_and_bot_no_custom_executor():
 repositories='\n'.join(p.read_text() for p in (ROOT/'relay/repositories').glob('*.py'))
 bot=(ROOT/'bot/main_bot.py').read_text()
 assert 'psycopg_pool' not in repositories and 'ConnectionPool' not in repositories
 assert 'set_default_executor' not in bot and 'ThreadPoolExecutor' not in bot
