import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-payment-provider-lifecycle-runtime-observation.v1.json"


def test_hash_bound_deployed_payment_sources():
    evidence = json.loads(EVIDENCE.read_text())
    for item in evidence["deployedEntrypoints"]:
        assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_submit_precedes_session_persistence_and_retries_are_present():
    source = Path("/opt/obsidian-exchange/relay/services/payment_service.py").read_text()
    create = source[source.index("def create_session"):source.index("def get_session")]
    assert create.index("provider.create_invoice") < create.index("sessions.create_invoice")
    assert "max_retries = 3" in create and "for attempt in range(max_retries)" in create
    assert "time.sleep(2.5)" in create and "self._escalate" in create
    assert "UNKNOWN" not in create and "reconcile" not in create


def test_numeric_hosted_payment_route_redirects_without_owner_authority():
    source = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    start = source.index('@app.get("/pay/{token}"')
    route = source[start:source.index("# Новый формат", start)]
    assert "token.isdigit()" in route
    assert "latest_active_for_order(order_id)" in route
    assert "RedirectResponse(f\"/pay/{session['session_token']}\"" in route
    assert "require_web_user" not in route and "token_matches_order" not in route


def test_callbacks_authenticate_but_do_not_require_exact_attempt_binding():
    source = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    for route in ("/montera/webhook", "/lava/webhook", "/brabus/webhook", "/stormtrade/webhook", "/xpay/webhook", "/rspay/webhook"):
        assert f'@app.post("{route}")' in source
    assert "webhook_secret" in source and "hmac.compare_digest" in source
    callback_area = source[source.index('@app.post("/greenpay/webhook")'):source.index('@app.post("/payment/callback")')]
    assert "_mark_order_paid" in callback_area
    calls = [line for line in callback_area.splitlines() if "_mark_order_paid(" in line]
    assert len(calls) == 7
    assert all("session_token=" not in line and "invoice" not in line and "amount" not in line for line in calls)


def test_transition_store_is_pending_only_but_session_match_is_not_required():
    source = Path("/opt/obsidian-exchange/relay/repositories/payment_transition_store.py").read_text()
    assert "FOR UPDATE" in source
    assert 'row["status"] != "pending"' in source
    assert "payment_notification_outbox" in source
    assert "session_token: str | None = None" in source
    assert source.index("UPDATE orders SET status") < source.index("if session_token")


def test_payout_guard_can_confirm_when_amount_evidence_is_unavailable():
    source = Path("/opt/obsidian-exchange/relay/services/payout_guard.py").read_text()
    amount = source[source.index("def _amount_mismatch"):source.index("def verify_payment_settled")]
    assert "if paid is None:" in amount and "return None" in amount
    assert "if expected is None:" in amount
    verify = source[source.index("def verify_payment_settled"):]
    assert verify.index("mismatch = _amount_mismatch") < verify.index('return {"verdict": "confirmed"')


def test_payload_logging_and_six_surface_rejection_are_explicit():
    main = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    assert "str(data)" in main
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert set(evidence["surfaceMatrix"]) == {"telegramBot", "site", "miniApp", "admin", "api", "native"}
    assert evidence["coverageConclusion"]["providerLifecycleAccepted"] is False
    assert evidence["nextCanonicalItem"].startswith("Classify PAYOUT_SETTLEMENT_RECONCILIATION")
