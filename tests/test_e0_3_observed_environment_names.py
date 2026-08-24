import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBS = json.loads((ROOT / "docs/e0-3-observed-environment-names.v1.json").read_text())

def effective(unit):
    record = OBS["effectiveUnits"][unit]
    names = set(record["inline"])
    for source in record["files"]:
        names.update(OBS["sources"][source])
    return names

def test_observation_is_names_only_and_complete_for_declared_sources():
    assert OBS["secretValuesPersistedOrEmitted"] is False
    assert OBS["observationAggregateStatus"] == "NO_GO_EXPECTED_CALLBACK_MISSING"
    assert OBS["systemdChainsDerivedByObserver"] is True
    assert set(OBS["effectiveUnits"]) == {"relay-fastapi.service","exchange-bot.service","exchange-notifier.service","obsidian-monitor.service","admin-panel.service","support-bot.service","obsidian-payout-worker.service","relay-shadow.service","kairos.service","lumi.service","callback-handler.service"}
    assert all(names == sorted(set(names)) for names in OBS["sources"].values())

def test_reset_eliminates_legacy_files_and_required_missing_is_no_go():
    assert OBS["effectiveUnits"]["obsidian-monitor.service"]["eliminatedSourceIds"] == ["legacy-monitor-env"]
    assert OBS["effectiveUnits"]["kairos.service"]["eliminatedSourceIds"] == ["kairos-security", "legacy-kairos-env"]
    assert OBS["effectiveUnits"]["lumi.service"]["eliminatedSourceIds"] == ["legacy-lumi-env", "lumi-security"]
    assert OBS["effectiveUnits"]["callback-handler.service"]["status"].startswith("NO_GO")

def test_exact_effective_sets_expose_overrides_and_forbidden_names():
    assert "DATABASE_URL" in effective("relay-fastapi.service")
    assert "PAYOUT_SEED" in effective("exchange-bot.service")
    assert "WALLET_PAYOUT_PASSWORD" in effective("exchange-bot.service")
    assert OBS["effectiveUnits"]["exchange-bot.service"]["inlineEmptyNames"] == ["PAYOUT_SEED", "WALLET_PAYOUT_PASSWORD"]
    assert "BTCPAY_API_KEY" in effective("exchange-notifier.service")
    assert "BTCPAY_API_KEY" in effective("obsidian-monitor.service")
    assert "KAIROS_OPERATOR_TOKEN" not in effective("lumi.service")
    assert "LUMI_KAIROS_TOKEN" in effective("kairos.service") & effective("lumi.service")

def test_observed_sources_match_proposed_unit_chains():
    design = json.loads((ROOT / "docs/e0-3-unit-environment-allowlist.v1.json").read_text())
    proposed = {item["id"]: item["environmentFiles"] for item in design["units"]}
    observed = {unit: record["files"] for unit, record in OBS["effectiveUnits"].items()}
    assert observed == proposed

def test_artifact_has_no_value_material():
    serialized = json.dumps(OBS).lower()
    for forbidden in ("postgresql://","begin private key","bearer ","=actual-secret", "fingerprint"):
        assert forbidden not in serialized

def test_postgres_member_sets_are_frozen_exactly():
    expected = {
        "pg-notifier-active":{"DATABASE_URL","ENGAGEMENT_POSTGRES_ENABLED","STATUS_NOTIFICATION_POSTGRES_ENABLED"},
        "pg-monitor-active":{"DATABASE_URL","LEGACY_RUNTIME_POSTGRES_ENABLED","REPORTING_POSTGRES_ENABLED"},
        "pg-support-active":{"ADMIN_CONFIG_POSTGRES_ENABLED","DATABASE_URL"},
        "pg-admin-active":{"EXCHANGE_DATABASE_URL","EXCHANGE_DB_CONNECTION","EXCHANGE_DB_SSLMODE"},
        "pg-payout-active":{"DATABASE_URL","PAYOUT_POSTGRES_ENABLED"},
    }
    for source, members in expected.items(): assert set(OBS["sources"][source]) == members
    app = set(OBS["sources"]["pg-app-active"])
    expected_app = {"DATABASE_URL","ADDRESS_BOOK_POSTGRES_ENABLED","ADMIN_CONFIG_POSTGRES_ENABLED","ALERT_POSTGRES_ENABLED","BOT_NOTIFICATION_POSTGRES_ENABLED","BOT_ORDER_POSTGRES_ENABLED","DCA_POSTGRES_ENABLED","ENGAGEMENT_POSTGRES_ENABLED","GIFT_POSTGRES_ENABLED","LEGACY_RUNTIME_POSTGRES_ENABLED","LIMIT_ORDER_POSTGRES_ENABLED","OPERATIONAL_READ_POSTGRES_ENABLED","OPS_POSTGRES_ENABLED","ORDER_LIFECYCLE_POSTGRES_ENABLED","ORDER_POSTGRES_ENABLED","ORDER_READ_POSTGRES_ENABLED","ORDER_WORKFLOW_POSTGRES_ENABLED","PAYMENT_POSTGRES_ENABLED","PAYMENT_SESSION_POSTGRES_ENABLED","PAYOUT_POSTGRES_ENABLED","PROMO_ADMIN_POSTGRES_ENABLED","PROVIDER_HEALTH_POSTGRES_ENABLED","RECEIPT_POSTGRES_ENABLED","RECONCILIATION_POSTGRES_ENABLED","REPORTING_POSTGRES_ENABLED","SELL_ORDER_POSTGRES_ENABLED","SELL_SETTLEMENT_POSTGRES_ENABLED","SHADOW_PAYOUT_POSTGRES_ENABLED","STATUS_NOTIFICATION_POSTGRES_ENABLED","SUPPORT_POSTGRES_ENABLED","SWAP_POSTGRES_ENABLED","USER_PROFILE_POSTGRES_ENABLED","WALLET_STORE_POSTGRES_ENABLED","WEB_AUTH_POSTGRES_ENABLED"}
    assert app == expected_app
    for source in expected:
        assert OBS["sourceStates"][source] == "OBSERVED_NAMES_ONLY"
    assert OBS["sourceStates"]["pg-app-active"] == "OBSERVED_NAMES_ONLY"
    assert "DATABASE_URL" not in set(OBS["sources"]["app-env"]) | set(OBS["sources"]["runtime-env"])
    assert "EXCHANGE_DATABASE_URL" not in set(OBS["sources"]["admin-env"]) | set(OBS["sources"]["runtime-env"])
