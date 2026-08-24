import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-lumi-control-plane-runtime-observation.v1.json"
DEPLOYED = Path("/opt/lumi/lumi/app")

def routes():
    result = []
    for path in sorted((DEPLOYED / "api").glob("*.py")):
        tree = ast.parse(path.read_text())
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets) and isinstance(node.value, ast.Call):
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant): prefix = kw.value.value
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router" and dec.func.attr in {"get", "post", "delete"} and dec.args and isinstance(dec.args[0], ast.Constant):
                        result.append((dec.func.attr.upper(), prefix + dec.args[0].value))
    return result

def test_exact_deployed_route_universe_and_hash():
    evidence = json.loads(EVIDENCE.read_text())
    found = routes()
    assert len(found) == 203
    assert {m: sum(x[0] == m for x in found) for m in ("GET", "POST", "DELETE")} == evidence["exactStaticRouteUniverse"]["methods"]
    main = DEPLOYED / "main.py"
    assert hashlib.sha256(main.read_bytes()).hexdigest() == evidence["deployedEntrypoint"]["sha256"]
    assert main.read_bytes() == (ROOT / "lumi/lumi/app/main.py").read_bytes()

def test_effectful_routes_are_explicit_and_unaccepted():
    evidence = json.loads(EVIDENCE.read_text())
    found = set(routes())
    assert {("POST", "/real-apply/execute"), ("POST", "/real-apply/rollback"), ("DELETE", "/security/vault/secrets/{secretId}"), ("POST", "/provider-runtime/live-call")} <= found
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert evidence["authorityBoundary"]["advisoryOnlyCharterConformance"] is False
    assert evidence["coverageConclusion"]["productionAcceptanceProven"] is False

def test_six_surfaces_and_next_family():
    evidence = json.loads(EVIDENCE.read_text())
    assert set(evidence["surfaceMatrix"]) == {"telegramBot", "site", "miniApp", "admin", "api", "native"}
    assert evidence["nextCanonicalItem"].startswith("Classify KAIROS_AUTONOMOUS_TRADE_CONTROL")
