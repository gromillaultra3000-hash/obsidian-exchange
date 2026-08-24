import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-deployed-route-feature-reconciliation.v1.json"
MATRIX = ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json"


def _value():
    return json.loads(EVIDENCE.read_text())


def test_reconciliation_is_read_only_non_accepting_and_hash_bound():
    value = _value()
    assert value["status"] == "IN_PROGRESS"
    assert value["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    for field in ("productionMutation", "credentialsUsed", "secretValuesRead",
                  "customerDataRead", "authenticatedCallsMade",
                  "externalProviderCallsMade", "moneyWritersExercised"):
        assert value[field] is False
    for artifact in value["entrypoints"]:
        path = Path(artifact["path"])
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]


def test_exact_classified_and_unclassified_sets_are_disjoint():
    value = _value()
    classified = value["previouslyClassifiedFamilies"]
    unclassified = [item["id"] for item in value["unclassifiedFamilies"]]
    assert len(classified) == len(set(classified)) == 13
    assert unclassified == [
        "LUMI_CONTROL_PLANE", "KAIROS_AUTONOMOUS_TRADE_CONTROL", "SWAPS",
        "ACCOUNT_AUTH_PROFILE", "PAYMENT_PROVIDER_LIFECYCLE",
        "PAYOUT_SETTLEMENT_RECONCILIATION", "WALLET_RECEIVE_TRANSFER",
        "PUBLIC_MARKET_INFORMATION", "CUSTOMER_ENGAGEMENT",
        "OPERATIONS_MONITORING", "AI_ASSISTANT", "KAIROS_EXCHANGE_DISCOVERY",
    ]
    assert set(classified).isdisjoint(unclassified)
    assert all(item["anchors"] and item["reason"] for item in value["unclassifiedFamilies"])


def test_matrix_records_reconciled_omissions_and_one_next_item():
    value = _value()
    matrix = json.loads(MATRIX.read_text())
    unclassified = [item["id"] for item in value["unclassifiedFamilies"]]
    classified_now = {item["id"] for item in matrix["features"]}
    assert matrix["omittedFeatureFamilies"] == [item for item in unclassified
                                                  if item not in classified_now]
    assert EVIDENCE.relative_to(ROOT).as_posix() in matrix["runtimeEvidence"]
    assert matrix["nextCanonicalItem"].startswith("Return to owner-blocked E0.3")


def test_material_route_anchors_remain_in_deployed_sources():
    relay = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    bot = Path("/opt/obsidian-exchange/bot/main_bot.py").read_text()
    lumi_main = Path("/opt/lumi/lumi/app/main.py").read_text()
    for route in ("/dashboard/swap", "/swap/{token}", "/register",
                  "/payment/callback", "/vertu/payout-callback",
                  "/api/wallet/receive", "/api/wallet/send-signed",
                  "/api/system-status"):
        assert route in relay
    for handler in ("menu_swap", "menu_reviews", "prompt_promo", "rate_sub_toggle"):
        assert handler in bot
    assert "include_router" in lumi_main


def test_completion_claim_is_narrow_and_honest():
    conclusion = _value()["coverageConclusion"]
    assert conclusion["boundedEntryPointScanComplete"] is False
    assert conclusion["allObservedGroupsEitherClassifiedOrRecordedUnclassified"] is False
    assert conclusion["sixSurfaceClassificationComplete"] is False
    assert conclusion["productionAcceptanceProven"] is False
    assert conclusion["e0GateClosed"] is False
    assert len(_value()["independentReviews"]) == 2
    assert all(item["disposition"] == "PARTIAL_NOT_ACCEPTED"
               for item in _value()["independentReviews"])
