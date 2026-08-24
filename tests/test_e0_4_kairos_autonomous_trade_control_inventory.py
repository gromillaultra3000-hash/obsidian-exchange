import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-kairos-autonomous-trade-control-runtime-observation.v1.json"
DEPLOYED = Path("/opt/kairos/app")


def static_api_routes():
    tree = ast.parse((DEPLOYED / "main_v19.py").read_text())
    result = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "app"
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
            ):
                continue
            if dec.func.attr in {"get", "post", "delete", "put", "patch"}:
                result.append((dec.func.attr.upper(), dec.args[0].value, node.name))
    return result


def test_hash_bound_deployed_sources_and_exact_api_universe():
    evidence = json.loads(EVIDENCE.read_text())
    for item in evidence["deployedEntrypoints"]:
        deployed = Path(item["path"])
        checkout = ROOT / "kairos/app" / deployed.name
        assert hashlib.sha256(deployed.read_bytes()).hexdigest() == item["sha256"]
        assert deployed.read_bytes() == checkout.read_bytes()
    found = static_api_routes()
    assert len(found) == evidence["exactStaticApiRouteUniverse"]["routes"]
    assert {
        method: sum(route[0] == method for route in found)
        for method in ("GET", "POST", "DELETE")
    } == evidence["exactStaticApiRouteUniverse"]["methods"]


def test_mounted_trade_and_worker_fail_closed_before_legacy_submit():
    main = ast.parse((DEPLOYED / "main_v19.py").read_text())
    engine = ast.parse((DEPLOYED / "kairos_engine.py").read_text())
    functions = {n.name: n for n in engine.body if isinstance(n, ast.ClassDef) for n in n.body if isinstance(n, ast.FunctionDef)}
    trade = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "trade")
    assert any(isinstance(n, ast.Raise) for n in ast.walk(trade))
    locked = functions["_execute_candidate_locked"]
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "create_order" for n in ast.walk(locked))
    legacy = functions["_legacy_execute_candidate_locked"]
    callers = [
        name for name, fn in functions.items()
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_legacy_execute_candidate_locked" for n in ast.walk(fn))
    ]
    assert callers == []
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_execute_inter_exchange" for n in ast.walk(legacy))


def test_unaccepted_authority_and_next_family_are_explicit():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert evidence["authorityBoundary"]["moneyWriterAuthorityObserved"] is False
    assert evidence["authorityBoundary"]["exchangeCreateOrderCodePresent"] is True
    assert evidence["authorityBoundary"]["exchangeCreateOrderReachableFromMountedEntrypoint"] is False
    assert set(evidence["surfaceMatrix"]) == {"telegramBot", "site", "miniApp", "admin", "api", "native"}
    assert evidence["nextCanonicalItem"].startswith("Classify SWAPS")
