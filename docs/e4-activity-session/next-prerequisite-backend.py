"""Exact installed read-class/handler mismatch; no app import or database calls."""
import ast
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
LIVE = Path('/opt/obsidian-exchange')
baseline_main = ROOT / 'output/manual/e4-activity-session-20260908/baseline/relay-fastapi/main.py'
candidate_main = ROOT / 'relay-fastapi/main.py'
order_path = LIVE / 'relay/repositories/order_read_store.py'
session_path = LIVE / 'relay/repositories/payment_session_store.py'
live_sources = {path: path.read_text() for path in [order_path, session_path]}
assert (ROOT / 'output/manual/e4-activity-session-20260908/baseline/relay/repositories/order_read_store.py').read_bytes() == order_path.read_bytes()
database_attempts = []


class NoDatabase:
    def __getattr__(self, name):
        database_attempts.append(name)
        raise AssertionError('database access forbidden')


def classes(source):
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Assign))
             or isinstance(node, ast.ImportFrom) and node.module == '__future__']
    context = {'db_runtime': NoDatabase(), 'os': SimpleNamespace(getenv=lambda *args: '')}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<exact-installed-read-store>', 'exec'), context)
    return context


orders = classes(live_sources[order_path])
sessions = classes(live_sources[session_path])


class SyntheticHTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code, self.detail = status_code, detail


def handler(source, name, context):
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    node.decorator_list = []
    code = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(code, '<exact-api-handler>', 'exec'), context)
    return context[name], hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()


results = []
for kind in ['SQLite', 'Postgres']:
    order_store = orders[kind + 'OrderReadStore']('synthetic-unused-path')
    session_store = sessions[kind + 'PaymentSessionStore']('synthetic-unused-path')
    assert not hasattr(order_store, 'authorized_snapshot')
    assert not hasattr(session_store, 'get_by_token')
    for origin, source in [('baseline', baseline_main.read_text()), ('candidate', candidate_main.read_text())]:
        for name, args in [('api_order', (42,)), ('pay', ('synthetic_opaque_session',))]:
            log_errors = []
            ctx = {'Request': object, 'HTTPException': SyntheticHTTPException,
                'verify_init_data': lambda _: {'id': 42}, '_order_reads': order_store,
                '_payment_sessions': session_store,
                'logger': SimpleNamespace(error=lambda value: log_errors.append(value))}
            function, function_digest = handler(source, name, ctx)
            request = SimpleNamespace(headers={}, query_params={}, client=SimpleNamespace(host='synthetic-local'))
            try:
                asyncio.run(function(*args, request))
            except AttributeError as error:
                assert name == 'api_order' and 'authorized_snapshot' in str(error)
                outcome = {'errorType': type(error).__name__, 'error': str(error),
                    'handlerMapsToHttp500': False, 'unhandledAtHandlerBoundary': True}
            except SyntheticHTTPException as error:
                assert name == 'pay' and error.status_code == 500
                assert len(log_errors) == 1 and 'get_by_token' in log_errors[0]
                outcome = {'errorType': 'HTTPException', 'statusCode': error.status_code,
                    'caughtCause': log_errors[0], 'handlerMapsToHttp500': True}
            else:
                raise AssertionError('expected installed contract mismatch was not reproduced')
            results.append({'backendClass': kind, 'main': origin, 'handler': name,
                'handlerAstSha256': function_digest, 'outcome': outcome,
                'databaseCalls': len(database_attempts), 'realIdentityUsed': False})
assert database_attempts == []
for kind in ['SQLite', 'Postgres']:
    for name in ['api_order', 'pay']:
        pair = [item for item in results if item['backendClass'] == kind and item['handler'] == name]
        assert pair[0]['handlerAstSha256'] == pair[1]['handlerAstSha256']
        assert pair[0]['outcome'] == pair[1]['outcome']
live_evidence = []
for path, source in live_sources.items():
    live_evidence.append({'path': str(path), 'sha256': hashlib.sha256(source.encode()).hexdigest(),
        'classes': [{'name': node.name, 'declaredMethods': [method.name for method in node.body
            if isinstance(method, ast.FunctionDef)]} for node in ast.parse(source).body if isinstance(node, ast.ClassDef)]})
report = {'schemaVersion': 'e4-installed-payment-read-contract-reproduction.v1',
    'result': 'PREEXISTING_INSTALLED_CONTRACT_MISMATCH_REPRODUCED',
    'method': 'Read installed Python source files only; execute exact class/function ASTs with a database object that raises on any use and an empty synthetic environment. Execute exact baseline/candidate api_order and pay handlers with synthetic signed-owner result/request. No application import, HTTP request, database, real auth secret, provider, wallet or service action.',
    'inputs': [{'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in [candidate_main, baseline_main]],
    'installedSourceEvidence': live_evidence,
    'reproduction': results,
    'databaseAttempts': database_attempts,
    'handlersUnchangedByCurrentSlice': True,
    'productionDataAccessed': False,
    'limitations': ['Exact disk source and isolated handler execution are verified; already-loaded production process objects and real user incidence were not inspected.',
        'api_order raises AttributeError at its handler boundary; no real ASGI response was requested. pay explicitly maps the missing method to HTTP500.']}
backend_out = OUT / 'next-prerequisite-backend.json'
backend_out.write_text(json.dumps(report, indent=2) + '\n')
next_report = {'schemaVersion': 'e4-installed-payment-read-contract-next-prerequisite.v1',
    'recordedAt': datetime.now(timezone.utc).isoformat(),
    'reviewer': 'Codex independent acceptance /root/receipt_acceptance',
    'result': 'REPRODUCED_REMAINING_PREREQUISITE',
    'nextCanonicalItem': 'E4 / PAYMENT_STATUS_RUNTIME_READ_CONTRACT / restore installed owner-scoped read methods required by payment status and page handlers',
    'canonicalCriterion': 'E4 coherent payment journey and understandable status/evidence on monetary paths',
    'backendEvidence': {'path': 'docs/e4-activity-session/next-prerequisite-backend.json',
        'sha256': hashlib.sha256(backend_out.read_bytes()).hexdigest()},
    'observed': 'The retained installed order_read_store classes lack authorized_snapshot; api_order calls it before any repository/provider work and leaves AttributeError unhandled. Installed payment_session_store classes lack get_by_token; the opaque-token pay handler calls it first and maps AttributeError to HTTP500. Both exact baseline and current-candidate handlers reproduce the same result with synthetic inputs and zero database calls.',
    'currentSliceDisposition': 'Pre-existing installed read-contract mismatch, independent of the activity-session change. Current slice adds a separate compatible activity view and preserves these installed dependencies byte-for-byte; no broader repository replacement is folded in.',
    'boundedImplementation': 'Restore only the owner-scoped read contracts needed by payment status/page handlers, including retained runtime-dependency compatibility and synthetic authorized/foreign/unknown subject tests. Preserve ownership checks, read-only behavior and existing money/status transition boundaries; do not replace unrelated repository behavior or use unauthenticated snapshot fallbacks.',
    'limitations': ['No production authenticated request or customer incident was observed; evidence is exact installed-source reproduction with synthetic identity and no database/provider call.',
        'Missing-method failures prevent these isolated handlers from reaching later logic; this evidence does not claim a payment was lost, repeated or marked paid.',
        'The next repair must inspect its immediate receipt/session dependencies before rollout; no financial operation, credential, signature or earlier-gate authority is inferred.']}
(OUT / 'next-prerequisite.json').write_text(json.dumps(next_report, indent=2) + '\n')
print(json.dumps({'result': report['result'], 'cases': len(results), 'databaseCalls': 0,
    'nextCanonicalItem': next_report['nextCanonicalItem']}))
