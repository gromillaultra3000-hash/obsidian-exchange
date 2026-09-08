"""Independent source boundary against the exact captured installed main."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
baseline = ROOT / 'output/manual/e4-payment-pending-receipt-20260908/baseline/relay-fastapi/main.py'
candidate = ROOT / 'relay-fastapi/main.py'
old_tree, new_tree = [ast.parse(path.read_text()) for path in (baseline, candidate)]


def dump(node):
    return ast.dump(node, include_attributes=False)


def functions(tree):
    return {node.name: node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


old, new = functions(old_tree), functions(new_tree)
assert set(old) == set(new)
changed = sorted(name for name in old if dump(old[name]) != dump(new[name]))
assert changed == ['pay'], changed
old_tree.body = [node for node in old_tree.body if node is not old['pay']]
new_tree.body = [node for node in new_tree.body if node is not new['pay']]
assert dump(old_tree) == dump(new_tree), 'module/import/wiring outside pay changed'
protected = {'_payment_status_reads.authorized_snapshot', '_payment_status_reads.get_by_token',
    '_payment_status_reads.latest_active_for_authorized_order', 'order_access.verify',
    '_receipt_state', '_session_dead', '_payout_delayed', 'RedirectResponse'}


def calls(node):
    return [dump(call) for call in ast.walk(node) if isinstance(call, ast.Call)
            and ast.unparse(call.func) in protected]


assert calls(old['pay']) == calls(new['pay']), 'read/auth/redirect invocation changed'
for kind in (ast.Import, ast.ImportFrom):
    assert [dump(node) for node in ast.walk(old['pay']) if isinstance(node, kind)] == [
        dump(node) for node in ast.walk(new['pay']) if isinstance(node, kind)], 'pay imports changed'
prior = json.loads((ROOT / 'docs/e4-payment-status-read/ops-release-manifest.json').read_text())
unchanged_dependencies = []
for row in prior['inputs']:
    if row['path'] not in {'relay/repositories/payment_status_read_store.py',
                           'relay/core/order_access.py', 'relay/webapp.html'}:
        continue
    assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
    unchanged_dependencies.append(row)
report = {'schemaVersion': 'e4-payment-pending-receipt-acceptance-surface.v1', 'result': 'PASS',
    'changedTopLevelFunctions': changed, 'unchangedTopLevelFunctions': sorted(name for name in old if name != 'pay'),
    'unchangedCount': len(old) - 1,
    'outsidePayModuleAstIdentical': True, 'protectedReadAuthRedirectCallsIdentical': True,
    'payImportsIdentical': True, 'unchangedDependencies': unchanged_dependencies,
    'scope': 'Only pay presentation changes. API/helpers/callbacks/writers/backgrounds/module wiring and payment adapter/proof/Mini App remain unchanged. No new SQL behavior; no repeated PostgreSQL container is needed.',
    'limits': 'Exact source boundary, not a claim of production deployment or absence of preexisting background work.',
    'inputs': [{'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in [baseline, candidate, Path(__file__),
                   ROOT / 'docs/e4-payment-status-read/ops-release-manifest.json']] + unchanged_dependencies}
(OUT / 'acceptance-surface.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'result': 'PASS', 'unchangedFunctions': len(old)-1, 'changed': changed}))
