"""Independent exact-byte proof: only the inline expiry helper/timer changes."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
baseline = ROOT / 'output/manual/e4-payment-expiry-20260908/baseline/relay-fastapi/main.py'
candidate = ROOT / 'relay-fastapi/main.py'
old, new = baseline.read_bytes(), candidate.read_bytes()


def strip(data, marker):
    assert data.count(marker) == 1
    start = data.index(marker)
    end = data.index(b'async function poll()', start)
    return data[:start] + b'// isolated expiry presentation block\n' + data[end:]


assert strip(old, b'function startTimer()') == strip(new, b'function paymentExpiryMs(')


def functions(data):
    return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(data).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


a, b = functions(old), functions(new)
assert a.keys() == b.keys()
assert [name for name in a if a[name] != b[name]] == ['pay']
report = {'schemaVersion': 'e4-payment-expiry-acceptance-surface.v1', 'result': 'PASS',
    'outsideExpiryHelperTimerBytesIdentical': True,
    'unchangedTopLevelFunctions': sorted(name for name in a if name != 'pay'),
    'unchangedCount': len(a)-1,
    'scope': 'Every main.py byte outside the inline expiry helper/timer block is identical: numeric page, auth/read/redirect/serialization, all render functions, poll, APIs, callbacks, workers and module wiring are unchanged.',
    'inputs': [{'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in [baseline, candidate, Path(__file__)]],
    'limits': 'Exact captured-source boundary; no production mutation or customer incidence claim.'}
(OUT / 'acceptance-surface.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'result': 'PASS', 'unchangedFunctions': len(a)-1}))
