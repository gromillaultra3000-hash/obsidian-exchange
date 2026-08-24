import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-payout-settlement-reconciliation-runtime-observation.v1.json"


def test_hash_bound_deployed_payout_sources():
    evidence = json.loads(EVIDENCE.read_text())
    for item in evidence["deployedEntrypoints"]:
        assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_canonical_intent_precedes_signer_and_rejects_payload_drift():
    bot = Path("/opt/obsidian-exchange/bot/main_bot.py").read_text()
    process = bot[bot.index("def process_payout("):bot.index("async def process_payout_async")]
    assert "_payout_store.create_order(" in process
    assert "wallet" not in process.lower() and "sign(" not in process
    store = Path("/opt/obsidian-exchange/relay/repositories/payout_store.py").read_text()
    assert 'f"payout_{oid}"' in store
    assert "payout_intent_payload_mismatch" in store


def test_worker_claims_once_and_exceptions_enter_review_without_retry():
    worker = Path("/opt/obsidian-exchange/payment/payout_worker.py").read_text()
    run = worker[worker.index("def run_once"):worker.index("def _stop")]
    assert run.index("store.claim_next()") < run.index("signer(intent)")
    assert "store.review(intent" in run
    assert run.count("signer(intent)") == 1
    assert "for attempt" not in run and "while" not in run


def test_format_only_completion_bypasses_are_present():
    bot = Path("/opt/obsidian-exchange/bot/main_bot.py").read_text()
    force = bot[bot.index('@router.message(Command("force_payout"))'):bot.index("async def _payout_preflight")]
    assert "normalize_txid" in force and "_order_workflow.mark_sent" in force
    assert "candidates_for" not in force and "confirm_order_txid" not in force
    relay = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    section = relay[relay.index('@app.post("/api/admin/force_payout")'):relay.index('@app.post("/internal/admin/notify_support")')]
    assert section.count("_order_workflow.mark_sent") == 2
    assert "payout_intent" not in section and "chain" not in section


def test_succeeded_reconciles_atomically_but_without_finality_state():
    store = Path("/opt/obsidian-exchange/relay/repositories/reconciliation_store.py").read_text()
    assert "p.state='succeeded'" in store and "o.status='paid'" in store
    for marker in ("payout_reconciliations", "user_vip_volume", "notification_outbox"):
        assert marker in store
    payout = Path("/opt/obsidian-exchange/relay/repositories/payout_store.py").read_text()
    assert "state='succeeded',txid=" in payout
    assert "confirmations" not in payout and "finality" not in payout


def test_notification_and_ledger_ambiguity_are_explicit():
    bot = Path("/opt/obsidian-exchange/bot/main_bot.py").read_text()
    loop = bot[bot.index("async def payout_reconciliation_task"):bot.index("async def credit_referral_bonus")]
    assert "store.retry_notification(item[\"id\"])" in loop
    notifier = Path("/opt/obsidian-exchange/payment/status_notifier.py").read_text()
    assert "if not BOT_TOKEN:\n        return" in notifier
    assert '_notifications.complete(oid, "sent")' in notifier
    signer = Path("/opt/obsidian-exchange/relay/services/payout_signer.py").read_text()
    assert 'if not path.exists():\n        return {"verdict": "absent"' in signer


def test_six_surfaces_rejected_and_next_family():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert set(evidence["surfaceMatrix"]) == {"telegramBot","site","miniApp","admin","api","native"}
    assert evidence["coverageConclusion"]["payoutSettlementAccepted"] is False
    assert evidence["nextCanonicalItem"].startswith("Classify WALLET_RECEIVE_TRANSFER")
