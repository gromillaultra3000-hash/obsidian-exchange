import hashlib,importlib.util,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
S=json.loads((ROOT/'docs/e0-3-bot-capability-graph.v1.json').read_text())
spec=importlib.util.spec_from_file_location('bot_graph',ROOT/'scripts/e0_bot_capability_graph.py')
G=importlib.util.module_from_spec(spec);spec.loader.exec_module(G)
def test_bot_graph_is_source_bound_and_truthfully_no_go():
 g=G.build();wire=(json.dumps(g,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
 assert hashlib.sha256(wire).hexdigest()==S['canonicalOutputSha256']
 assert g['status']==S['status']=='EXACT_STATIC_GRAPH'
 assert g['productionAuthorization'] is g['valuesIncluded'] is False
 assert g['directSqlOrConnectionSites']==[]
def test_only_declared_static_debt_remains():
 g=G.build();objects={o for e in g['edges'] for o in e['objects']}
 assert S['counts']=={'repositoryImports':22,'factoryBindings':19,'callEdges':183,
  'relationObjects':len(objects),'directSqlOrConnectionSites':0,'unresolvedMethods':0}
 assert g['uncalledImportedRepositories']==S['uncalledImportedRepositories']==[]
 assert g['unresolvedMethods']==S['unresolvedMethods']==[]
 assert {(e['caller'],e['method']) for e in g['edges'] if e['repository']=='bot_order_store'}=={
  ('_finalize_order','create_order'),('ratelock_choose','replace_rate_lock'),
  ('get_active_rate_lock','active_rate_lock'),('handle_webapp','create_order')}
