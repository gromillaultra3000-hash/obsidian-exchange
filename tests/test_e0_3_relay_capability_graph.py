import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = json.loads((ROOT / "docs/e0-3-relay-capability-graph.v1.json").read_text())
SPEC = importlib.util.spec_from_file_location(
    "e0_relay_capability_graph", ROOT / "scripts/e0_relay_capability_graph.py"
)
GRAPH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRAPH)


def canonical_output():
    result = GRAPH.build()
    wire = json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")) + "\n"
    return result,wire.encode()


def test_summary_is_bound_to_exact_current_graph():
    graph,wire = canonical_output()
    assert graph["status"] == SUMMARY["status"] == "EXACT_STATIC_GRAPH"
    assert hashlib.sha256(wire).hexdigest() == SUMMARY["canonicalOutputSha256"]
    assert graph["productionAuthorization"] is SUMMARY["productionAuthorization"] is False
    assert graph["valuesIncluded"] is SUMMARY["valuesIncluded"] is False


def test_closed_counts_imports_objects_and_operations_match():
    graph,_ = canonical_output()
    objects = sorted({obj for edge in graph["edges"] for obj in edge["objects"]})
    operations = sorted({op for edge in graph["edges"] for op in edge["operations"]})
    assert SUMMARY["counts"] == {
        "repositoryImports":len(graph["repositoryImports"]),
        "factoryBindings":len(graph["factoryBindings"]),
        "callEdges":len(graph["edges"]),
        "relationObjects":len(objects),
        "directSqlOrConnectionSites":len(graph["directSqlOrConnectionSites"]),
        "unresolvedMethods":len(graph["unresolvedMethods"]),
    }
    assert graph["repositoryImports"] == graph["calledRepositories"] == SUMMARY["repositoryImports"]
    assert graph["uncalledImportedRepositories"] == []
    assert objects == SUMMARY["relationObjects"]
    assert operations == SUMMARY["operations"]


def test_every_edge_has_static_repository_sql_evidence():
    graph,_ = canonical_output()
    assert graph["directSqlOrConnectionSites"] == []
    assert graph["unresolvedMethods"] == []
    assert len({(edge["caller"],edge["line"],edge["binding"],edge["repository"],edge["method"])
                for edge in graph["edges"]}) == len(graph["edges"])
    for edge in graph["edges"]:
        assert edge["definitions"] >= 1
        assert edge["operations"]
        assert edge["objects"]
        assert (ROOT / edge["evidence"]).exists()


def test_graph_contains_money_writers_and_is_not_least_privilege_evidence():
    graph,_ = canonical_output()
    required = {
        ("payment_transition_store","mark_paid"),
        ("order_creation_store","create"),
        ("order_workflow_store","mark_sent"),
        ("sell_order_store","create"),
        ("sell_settlement_store","settle_vertu"),
    }
    actual = {(edge["repository"],edge["method"]) for edge in graph["edges"]}
    assert required <= actual
    assert SUMMARY["productionAuthorization"] is False
    assert SUMMARY["remainingWork"][0].startswith("use the source-bound Relay writer matrix")


def test_dynamic_sql_surface_is_closed_and_reviewed():
    graph,_ = canonical_output()
    dynamic = {(edge["repository"],edge["method"]) for edge in graph["edges"]
               if edge["dynamicSqlPresent"]}
    assert dynamic == {
        ("ops_store","cleanup_audit"),
        ("order_creation_store","recent_duplicate"),
        ("order_lifecycle_store","claim_work"),
        ("order_read_store","receipt_order_ids"),
        ("order_read_store","authorized_snapshot"),
        ("payment_session_store","latest_provider_invoice_for_authorized_order"),
        ("runtime_schema_store","validate"),
        ("sell_order_store","active_vertu_payouts"),
        ("sell_order_store","cancel_pending"),
        ("sell_settlement_store","claim_notification"),
        ("swap_store","get_by_external_id"),
        ("swap_store","get_by_token"),
    }
