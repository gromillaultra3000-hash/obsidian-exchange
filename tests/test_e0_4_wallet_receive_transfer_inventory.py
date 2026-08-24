import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-wallet-receive-transfer-runtime-observation.v1.json"


def test_hash_bound_deployed_wallet_action_sources():
    evidence = json.loads(EVIDENCE.read_text())
    for item in evidence["deployedEntrypoints"]:
        assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_routes_require_initdata_and_receive_uses_stored_address():
    main = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    start = main.index('@app.get("/api/wallet/dues")')
    area = main[start:main.index("# --- API эндпоинты ---", start)]
    for route in ("/api/wallet/send-request","/api/wallet/transfer-request","/api/wallet/receive","/api/wallet/send-signed"):
        assert route in area
    assert area.count("verify_init_data") == 5
    receive = area[area.index('@app.get("/api/wallet/receive")'):area.index('@app.post("/api/wallet/send-signed")')]
    assert "_wl.address_for(user['id'], 'TON')" in receive
    assert "query_params" not in receive


def test_order_request_is_owner_bound_but_intent_failure_is_ignored():
    source = Path("/opt/obsidian-exchange/relay/core/wallet_send.py").read_text()
    build = source[source.index("def build_request"):]
    for marker in ('int(row["user_id"] or 0) != uid','!= CHAIN','!= "pending"','row["receive_address"]','row["crypto_amount"]'):
        assert marker in build
    assert "remember_intent(uid, sid" in build
    assert "if not remember_intent" not in build and "intent_id=" not in build
    remember = source[source.index("def remember_intent"):source.index("def mark_signed")]
    assert "except Exception" in remember and "return None" in remember


def test_transfer_and_ack_have_no_durable_correlation():
    source = Path("/opt/obsidian-exchange/relay/core/wallet_send.py").read_text()
    transfer = source[source.index("def build_transfer"):source.index("def build_request")]
    assert "client_chosen=True" in transfer and '"network": MAINNET' in transfer
    assert "remember_intent" not in transfer and "request_id" not in transfer
    main = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    ack = main[main.index('@app.post("/api/wallet/send-signed")'):main.index("# --- API эндпоинты ---")]
    assert 'body.get("sell_id")' in ack and '"ok": True' in ack
    for marker in ("txid","boc","request_id","message_hash"):
        assert marker not in ack.lower()


def test_schema_has_no_unique_request_or_lifecycle_fields():
    schema = Path("/opt/obsidian-exchange/deploy/postgres/014_wallet_store.sql").read_text()
    assert "wallet_send_intents" in schema and "signed_at" in schema
    for marker in ("idempotency", "request_id", "expires_at", "txid", "content_hash", "state"):
        assert marker not in schema
    assert "UNIQUE" not in schema[schema.index("CREATE TABLE wallet_send_intents"):]


def test_server_does_not_sign_and_sell_ack_is_not_settlement_truth():
    source = Path("/opt/obsidian-exchange/relay/core/wallet_send.py").read_text()
    assert "PRIVATE" not in source.upper() and "mnemonic" not in source.lower()
    assert "sign(" not in source and "broadcast" not in source.lower()
    guard = Path("/opt/obsidian-exchange/bot/sell_guard.py").read_text()
    assert "verify_sell_deposit" in guard and "claimed_txids" in guard
    assert "confirmations" in guard


def test_six_surfaces_rejected_and_next_family():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert set(evidence["surfaceMatrix"]) == {"telegramBot","site","miniApp","admin","api","native"}
    assert evidence["coverageConclusion"]["customerKeyBoundaryPreserved"] is True
    assert evidence["coverageConclusion"]["productionLifecycleAccepted"] is False
    assert evidence["nextCanonicalItem"].startswith("Classify PUBLIC_MARKET_INFORMATION")
