import hashlib
import json
from pathlib import Path


ROOT = Path("/root")
EVIDENCE = ROOT / "docs/e0-4-rate-locks-runtime-observation.v1.json"


def sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_deployed_and_proposal_hashes_are_bound():
    evidence = json.loads(EVIDENCE.read_text())
    for item in evidence["deployedSources"]:
        assert sha(item["path"]) == item["sha256"]
    proposal = evidence["proposalBoundary"]
    for path_key, digest_key in (
        ("rateLockSchemaPath", "rateLockSchemaSha256"),
        ("replacementProposalPath", "replacementProposalSha256"),
        ("orderWriterProposalPath", "orderWriterProposalSha256"),
    ):
        assert sha(str(ROOT / proposal[path_key])) == proposal[digest_key]
    assert proposal["deployed"] is False and proposal["acceptanceEffect"] == "NONE"


def test_all_six_surfaces_are_classified_and_only_telegram_implements_feature():
    evidence = json.loads(EVIDENCE.read_text())
    matrix = evidence["surfaceMatrix"]
    assert list(matrix) == ["telegramBot", "site", "miniApp", "admin", "api", "native"]
    assert matrix["telegramBot"]["implementation"] == "IMPLEMENTED"
    assert all(matrix[name]["implementation"] == "NOT_IMPLEMENTED"
               for name in ("site", "miniApp", "admin", "api", "native"))


def test_fee_claim_is_present_but_no_money_path_consumes_fee():
    bot = Path("/opt/obsidian-exchange/bot/main_bot.py").read_text()
    store = Path("/opt/obsidian-exchange/relay/repositories/bot_order_store.py").read_text()
    assert "RATE_LOCK_FEE    = 100.0" in bot
    assert "Комиссия за фиксацию" in bot and "вычтется из суммы" in bot
    finalize = bot[bot.index("async def _finalize_order"):bot.index("# ══════════════════════════════════════════════════════════════════\n# ГАРАНТИРОВАННЫЙ КУРС")]
    assert "_lock[\"fee\"]" not in finalize and "RATE_LOCK_FEE" not in finalize
    assert '"fee"' not in store[store.index("def create_order", store.index("class PostgresBotOrderStore")):]
    evidence = json.loads(EVIDENCE.read_text())
    assert any(item["id"] == "ADVERTISED_FEE_NOT_APPLIED" and item["severity"] == "CRITICAL"
               for item in evidence["criticalFindings"])


def test_acceptance_remains_false_and_observation_is_effect_free():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert len(evidence["independentReviews"]) == 3
    for key in ("productionMutation", "authenticatedCallsMade", "secretValuesRead",
                "customerIdentifiersRead", "externalPriceCallsMade",
                "lockOrOrderWritersExercised", "servicesRestarted"):
        assert evidence[key] is False
    conclusion = evidence["coverageConclusion"]
    assert conclusion["sixSurfacesClassified"] is True
    assert conclusion["moneyAuthorityIdentified"] is True
    assert all(value is False for key, value in conclusion.items()
               if key not in {"sixSurfacesClassified", "moneyAuthorityIdentified"})
