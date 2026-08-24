import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MATRIX=json.loads((ROOT/"docs/e0-3-relay-writer-matrix.v1.json").read_text())
SPEC=importlib.util.spec_from_file_location("relay_graph",ROOT/"scripts/e0_relay_capability_graph.py")
GRAPH=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(GRAPH)


def test_matrix_is_bound_to_graph_and_exact_repository_sources():
    graph=GRAPH.build()
    wire=(json.dumps(graph,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    assert hashlib.sha256(wire).hexdigest()==MATRIX["relayGraphSha256"]
    for module,digest in MATRIX["sourceSha256"].items():
        assert hashlib.sha256((ROOT/"relay/repositories"/f"{module}.py").read_bytes()).hexdigest()==digest
    assert MATRIX["productionAuthorization"] is MATRIX["valuesIncluded"] is False


def test_every_and_only_relay_writer_method_is_classified_once():
    graph=GRAPH.build()
    expected={(edge["repository"],edge["method"]) for edge in graph["edges"]
              if set(edge["operations"])-{"SELECT"}}
    actual={tuple(item["id"].split(".",1)) for item in MATRIX["writers"]}
    assert len(MATRIX["writers"])==len(actual)==26
    assert actual==expected


def test_every_writer_has_closed_columns_invariants_and_effect():
    forbidden={"*","ALL","UNKNOWN","TBD"}
    for writer in MATRIX["writers"]:
        assert writer["effect"] and writer["invariants"] and writer["mutations"]
        assert not (set(writer)-{"id","effect","mutations","invariants"})
        for relation,columns in writer["mutations"].items():
            assert relation and columns and len(columns)==len(set(columns))
            assert not (set(columns)&forbidden)
        assert all(value==value.upper() and " " not in value for value in writer["invariants"])


def test_money_transitions_keep_cas_lock_audit_or_ledger_guards():
    writers={item["id"]:set(item["invariants"]) for item in MATRIX["writers"]}
    assert {"ORDER_ROW_LOCK","PENDING_TO_PAID_ONLY","AUDIT_IN_SAME_TRANSACTION"} <= writers["payment_transition_store.mark_paid"]
    assert {"ORDER_ROW_LOCK","PAID_TO_SENT_ONLY","CAS_SINGLE_WINNER"} <= writers["order_workflow_store.mark_sent"]
    assert {"SELL_ROW_LOCK","LEDGER_ABSENCE_REQUIRED","LEDGER_VIP_OUTBOX_SAME_TRANSACTION"} <= writers["sell_settlement_store.settle_vertu"]
    assert "PENDING_TO_CANCELLED_CAS" in writers["sell_order_store.cancel_pending"]


def test_retention_delete_is_bound_to_current_literal_caller():
    entrypoint=(ROOT/"relay-fastapi/main.py").read_text()
    assert "_ops_store.cleanup_audit(90)" in entrypoint
    writer=next(item for item in MATRIX["writers"] if item["id"]=="ops_store.cleanup_audit")
    assert "CALLER_LITERAL_90_DAYS" in writer["invariants"]


def test_next_step_is_acl_design():
    assert MATRIX["remainingWork"][0].startswith("design Relay functions")
