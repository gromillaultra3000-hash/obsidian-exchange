import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = json.loads((ROOT / "docs/e0-3-unit-environment-allowlist.v1.json").read_text())
DB = json.loads((ROOT / "docs/e0-3-db-capability-manifest.v1.json").read_text())

def test_artifacts_are_in_progress_metadata_only_and_non_production():
    assert ENV["status"] == DB["status"] == "IN_PROGRESS"
    assert ENV["valuesIncluded"] is False
    assert ENV["productionAuthorization"] is DB["productionAuthorization"] is False
    assert ENV["implementationDeployed"] is False

def test_exact_unit_set_and_app_consumers():
    expected = {"relay-fastapi.service","exchange-bot.service","exchange-notifier.service","obsidian-monitor.service","admin-panel.service","support-bot.service","obsidian-payout-worker.service","relay-shadow.service","kairos.service","lumi.service","callback-handler.service"}
    assert {u["id"] for u in ENV["units"]} == expected
    assert set(ENV["sources"]["app-env"]["effectiveConsumers"]) == {"relay-fastapi.service","exchange-bot.service","exchange-notifier.service","obsidian-monitor.service"}

def test_unrelated_units_never_target_provider_or_signer_families():
    units = {u["id"]: u for u in ENV["units"]}
    for unit in ("exchange-notifier.service","obsidian-monitor.service"):
        assert "all-provider-families" in units[unit]["forbiddenFamilies"]
    assert "all-app-env-families" in units["obsidian-payout-worker.service"]["forbiddenFamilies"]
    assert "USDT_PRIVATE_KEY" in units["exchange-bot.service"]["forbiddenFamilies"]

def test_postgres_sources_are_exact_and_staged_are_not_runtime_consumers():
    pg = ENV["postgresEnvironmentSources"]
    assert {x["role"] for x in pg} == {"obsidian_app","obsidian_readonly","obsidian_payout"}
    assert all(x["systemdOptional"] and x["operationalRequired"] for x in pg)
    assert len(ENV["stagedReferences"]) == 6
    assert all(item["runtimeConsumers"] == [] for item in ENV["stagedReferences"])
    assert all(item["expiryStatus"] == item["deletionStatus"] == "UNKNOWN" for item in ENV["stagedReferences"])

def test_notifier_method_and_target_surface_is_exact():
    notifier = next(s for s in DB["services"] if s["id"] == "exchange-notifier.service")
    assert notifier["status"] == "DISPOSABLE_ACL_REHEARSED_NOT_DEPLOYED"
    assert {m["id"].split(".")[-1] for m in notifier["activeMethods"]} == {"pending","complete","ensure_review"}
    assert len(notifier["targetFunctions"]) == 3
    assert all(item["status"] == "DISPOSABLE_REHEARSAL_ONLY" for item in notifier["targetFunctions"])
    assert notifier["directRelationPrivileges"] == []
    assert "all direct table DML" in notifier["negativeCapabilities"]

def test_shadow_is_no_db_until_dedicated_entrypoint_exists():
    shadow = next(s for s in DB["services"] if s["id"] == "relay-shadow.service")
    assert shadow["targetRole"] == "NOLOGIN_NO_DB_CREDENTIAL"
    assert shadow["entrypoint"] == "relay-fastapi/main.py"
    assert shadow["status"].startswith("NO_GO")
    assert shadow["targetLogin"] is shadow["targetConnect"] is False
    assert shadow["directRelationPrivileges"] == []
    assert any("all 43 read plus all 26 writer bodies" in item for item in DB["globalNoGo"])
    assert "bot caller-to-method graph is unassessed" in DB["globalNoGo"]

def test_every_unit_environment_reference_resolves_and_matches_repo_templates():
    source_ids = set(ENV["sources"]) | {item["id"] for item in ENV["postgresEnvironmentSources"]}
    units = {item["id"]: item for item in ENV["units"]}
    expected = {
        "relay-fastapi.service":["app-env","runtime-env","pg-app-active"],
        "exchange-bot.service":["app-env","runtime-env","pg-app-active"],
        "exchange-notifier.service":["app-env","runtime-env","pg-notifier-active"],
        "obsidian-monitor.service":["app-env","runtime-env","pg-monitor-active"],
        "admin-panel.service":["admin-env","runtime-env","pg-admin-active"],
        "support-bot.service":["support-env","runtime-env","pg-support-active"],
        "obsidian-payout-worker.service":["payout-env","pg-payout-active"],
        "relay-shadow.service":["app-env","runtime-env","pg-app-active"],
        "kairos.service":["kairos-security","kairos-runtime"],
        "lumi.service":["lumi-security"],
        "callback-handler.service":["callback-env"],
    }
    assert {unit: units[unit]["environmentFiles"] for unit in units} == expected
    assert all(ref in source_ids for refs in expected.values() for ref in refs)
    templates = "\n".join(path.read_text() for path in (ROOT / "deploy").rglob("*.conf"))
    templates += "\n" + (ROOT / "deploy/relay-shadow.service").read_text()
    templates += "\n" + (ROOT / "deploy/systemd/callback-handler.service").read_text()
    for source in ENV["sources"].values():
        if source["path"].startswith("/etc/obsidian-exchange/") and source["path"] != "/etc/obsidian-exchange/payout-worker.env":
            assert source["path"] in templates or source["id"] in {"kairos-security","kairos-runtime","lumi-security"}

def test_notifier_manifest_is_grounded_in_current_caller_and_sql():
    caller = (ROOT / "payment/status_notifier.py").read_text()
    calls = set(re.findall(r"_(?:notifications|engagement)\.([a-z_]+)\(", caller))
    assert calls == {"pending", "complete", "ensure_review"}
    assert "payout_candidates(" not in caller
    status_store = (ROOT / "relay/repositories/status_notification_store.py").read_text()
    engagement = (ROOT / "relay/repositories/engagement_store.py").read_text()
    for token in ("FROM orders", "sent_notifications", "UPDATE gift_vouchers"):
        assert token in status_store
    assert "INSERT INTO reviews" in engagement
    shadow_unit = (ROOT / "deploy/relay-shadow.service").read_text()
    assert "relay-fastapi/main.py" in shadow_unit
    assert "postgres/app.active.env" in shadow_unit
    assert "RELAY_BACKGROUND_TASKS_ENABLED=0" in shadow_unit

def test_provider_paths_are_explicit_and_kairos_members_are_not_claimed_observed():
    providers = set(ENV["familyGroups"]["provider-families"])
    targets = {item["family"]: item for item in ENV["targetBundles"]}
    assert providers <= set(targets)
    assert all("<" not in targets[family]["path"] for family in providers)
    assert ENV["sources"]["kairos-runtime"]["observedMembersStatus"] == "UNKNOWN"
    assert "expectedGeneratedMembers" in ENV["sources"]["kairos-runtime"]

def test_no_value_material_or_false_deployment_claims():
    serialized = json.dumps([ENV, DB]).lower()
    for forbidden in ("postgresql://","begin private key","bearer ","secretvalue","tokenvalue","fingerprint"):
        assert forbidden not in serialized
    forbidden_fields = {"value", "secretValue", "currentValue", "dsn", "hash", "fingerprint", "ciphertext"}
    def walk(item):
        if isinstance(item, dict):
            assert not (set(item) & forbidden_fields)
            for nested in item.values(): walk(nested)
        elif isinstance(item, list):
            for nested in item: walk(nested)
    walk([ENV, DB])
