import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _method_body(path, class_name, method_name):
    text = path.read_text()
    tree = ast.parse(text)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name == class_name)
    method = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and node.name == method_name)
    return ast.get_source_segment(text, method)


def test_candidate_postgres_methods_have_default_off_execute_only_function_adapters():
    selected = [
        ("order_read_store.py", "PostgresOrderReadStore", "authorized_snapshot", "orders"),
        ("payment_session_store.py", "PostgresPaymentSessionStore", "get_by_token", "payment_sessions"),
        ("payment_session_store.py", "PostgresPaymentSessionStore", "latest_for_authorized_order", "payment_sessions"),
        ("payment_session_store.py", "PostgresPaymentSessionStore", "latest_active_for_authorized_order", "payment_sessions"),
        ("payment_session_store.py", "PostgresPaymentSessionStore", "latest_provider_invoice_for_authorized_order", "payment_sessions"),
        ("receipt_store.py", "PostgresReceiptStore", "authorized_state", "order_receipts"),
        ("engagement_store.py", "PostgresEngagementStore", "comment_review", "reviews"),
        ("engagement_store.py", "PostgresEngagementStore", "finalize_review", "reviews"),
    ]
    relay_methods = 0
    bot_methods = 0
    for filename, cls, method, relation in selected:
        body = _method_body(ROOT / "relay/repositories" / filename, cls, method)
        assert relation in body
        if cls.startswith("PostgresEngagement"):
            assert "BOT_B3_ENGAGEMENT_ACL_ADAPTER_ENABLED" in body
            assert f"bot_b3_{method}" in body
            bot_methods += 1
        else:
            assert "RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED" in body
            assert "public.relay_" in body
            relay_methods += 1
    assert relay_methods == 6 and bot_methods == 2

    relay_acl = (ROOT / "deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
    relay_functions = (ROOT / "deploy/postgres/proposals/032_e0_relay_p3_authorized_order_reads.sql").read_text()
    bot_acl = (ROOT / "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql").read_text()
    bot_functions = (ROOT / "deploy/postgres/proposals/042_e0_bot_b3_1_engagement_non_money_writers.sql").read_text()
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA public" in relay_acl
    assert "TO obsidian_relay" in relay_functions and "GRANT EXECUTE" in relay_functions
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA public" in bot_acl
    assert "TO obsidian_exchange_bot" in bot_functions and "GRANT EXECUTE" in bot_functions
