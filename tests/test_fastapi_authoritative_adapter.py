import ast
from pathlib import Path


root = Path(__file__).resolve().parents[1]
source = (root / "relay-fastapi" / "main.py").read_text("utf-8")
tree = ast.parse(source)

assert "def db_conn(" not in source
assert "_ensure_orders_columns" not in source
assert "sqlite3.connect" not in source
assert not any(
    isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and node.func.attr in {"execute", "executemany", "executescript"}
    for node in ast.walk(tree)
), "FastAPI adapter still executes authoritative SQL"

functions = {node.name: ast.get_source_segment(source, node) for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
assert "_runtime_schema.validate()" in functions["lifespan"]
assert "_ops_store.cleanup_audit(90)" in functions["_session_cleanup_loop"]
assert "_reporting.admin_analytics()" in functions["analytics_data"]
assert "_sell_store.vertu_payout_by_ref(ref)" in functions["vertu_payout_callback"]
assert "_sell_store.active_vertu_payouts(" in functions["_vertu_payout_sweep"]

print("FastAPI authoritative adapter checks: OK")
