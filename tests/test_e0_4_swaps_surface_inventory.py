import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-swaps-runtime-observation.v1.json"


def test_hash_bound_deployed_swap_sources():
    evidence = json.loads(EVIDENCE.read_text())
    for item in evidence["deployedEntrypoints"]:
        deployed = Path(item["path"])
        assert hashlib.sha256(deployed.read_bytes()).hexdigest() == item["sha256"]


def test_active_swap_submit_precedes_local_persistence():
    relay = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    bot = Path("/opt/obsidian-exchange/bot/main_bot.py").read_text()
    for source, start, end in (
        (relay, "async def dashboard_swap_submit", "# --- Личный кабинет: рефералы"),
        (bot, "async def process_swap_address", "@router.message(Command(\"history\"))"),
    ):
        body = source[source.index(start):source.index(end, source.index(start))]
        assert body.index("create_swap(") < body.index("_swap_store.create(")


def test_swapuz_unknown_status_is_not_fail_closed_or_forward_only():
    provider = Path("/opt/obsidian-exchange/relay/providers/swapuz.py").read_text()
    relay = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    bot = Path("/opt/obsidian-exchange/bot/main_bot.py").read_text()
    assert 'return {"status": "unknown"}' in provider
    assert 'f"status_{status_code}"' in provider
    swap_page = relay[relay.index("async def swap_page"):relay.index("@app.post(\"/trocador/webhook\")")]
    monitor = bot[bot.index("async def swap_status_monitor"):bot.index("@router.message(Command(\"history\"))", bot.index("async def swap_status_monitor"))]
    assert "safe_trocador_transition" not in swap_page.split("else:", 1)[0]
    assert "safe_trocador_transition" not in monitor


def test_six_surfaces_unaccepted_authority_and_next_family():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert evidence["authorityBoundary"]["providerOrderCreatedBeforeDurableIntent"] is True
    assert evidence["authorityBoundary"]["persistedImmutableIntentBeforeSubmit"] is False
    assert evidence["authorityBoundary"]["ambiguousSubmitRecoveryAccepted"] is False
    assert set(evidence["surfaceMatrix"]) == {"telegramBot", "site", "miniApp", "admin", "api", "native"}
    assert evidence["nextCanonicalItem"].startswith("Classify ACCOUNT_AUTH_PROFILE")
