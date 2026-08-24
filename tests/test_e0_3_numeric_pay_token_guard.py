import ast
from pathlib import Path


ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/"relay-fastapi/main.py").read_text())


def test_numeric_pay_fallback_requires_bounded_proof_before_session_lookup():
 pay=next(node for node in TREE.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
          and node.name=="pay")
 body=ast.get_source_segment((ROOT/"relay-fastapi/main.py").read_text(),pay)
 numeric=body.index("if token.isdigit():")
 guard=body.index('request.query_params.get("proof", "")',numeric)
 denial=body.index("raise HTTPException(status_code=404)",guard)
 lookup=body.index("latest_active_for_authorized_order",numeric)
 assert numeric < guard < denial < lookup
 assert "order_access.verify" in body[numeric:lookup]
 assert "authorized_snapshot" in body[numeric:lookup]
 assert "PaymentService" not in body
 assert "_payment_sessions.get_by_token(token)" in body
