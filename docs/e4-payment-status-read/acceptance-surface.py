"""Independent AST boundary check against the exact captured installed main."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
baseline = ROOT / 'output/manual/e4-payment-status-read-20260908/baseline/relay-fastapi/main.py'
candidate = ROOT / 'relay-fastapi/main.py'


def functions(path):
    return {node.name: node for node in ast.parse(path.read_text()).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


old, new = functions(baseline), functions(candidate)
changed = sorted(name for name in old.keys() | new.keys()
                 if ast.dump(old.get(name), include_attributes=False) != ast.dump(new.get(name), include_attributes=False))
assert changed == ['_receipt_state', '_session_dead', 'api_order', 'pay'], changed
assert '_mark_order_paid' in old and 'vertu_poll_task' in old
for name in ['api_order', 'pay']:
    code = ast.unparse(new[name])
    assert 'providers.' not in code and '_mark_order_paid' not in code
unchanged = sorted(name for name in old if name not in changed)
report = {'schemaVersion': 'e4-payment-status-read-acceptance-surface.v1', 'result': 'PASS',
    'inputs': [{'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in [candidate, baseline, Path(__file__)]],
    'changedTopLevelHandlersOrHelpers': changed,
    'unchangedTopLevelFunctions': unchanged,
    'unchangedCount': len(unchanged),
    'scope': 'No top-level function added/removed. All callbacks, background workers, money transition helper, auth verifier and unrelated page handlers retain exact installed ASTs. Module-level additive adapter wiring is separately inspected.',
    'limits': 'Source comparison, not a claim that preexisting background work stops on Relay restart.'}
(OUT / 'acceptance-surface.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'result': 'PASS', 'unchangedFunctions': len(unchanged), 'changed': changed}))
