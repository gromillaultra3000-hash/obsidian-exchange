import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "operational-ownership.v1.json"
POLICY_STATES = {"VERIFIED", "PARTIAL", "UNKNOWN", "NOT_APPLICABLE"}


def _load():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def test_registry_has_unique_complete_sections_and_never_inspected_values():
    data = _load()
    assert data["schema"] == "obsidian-operational-ownership.v1"
    assert data["secretValuesInspected"] is False
    assert data["coverageStatus"] == "IN_PROGRESS"
    assert data["ownerAssignmentsAccepted"] is True
    assert (ROOT / data["ownerDecisionEvidence"]).exists()
    assert data["openControlGaps"]
    for section in ["dataStores", "secretReferences", "moneyWriters"]:
        items = data[section]
        assert items
        ids = [item["id"] for item in items]
        assert len(ids) == len(set(ids))
        assert all(item["accountableOwner"] and item["accountableOwner"] != "unassigned" for item in items)
        assert all(item["evidence"] for item in items)


def test_every_datastore_has_explicit_lifecycle_and_existing_evidence():
    for store in _load()["dataStores"]:
        assert store["classification"] and store["runtimePrincipals"]
        for policy in ["retention", "deletion", "backup"]:
            assert store[policy]["status"] in POLICY_STATES
            assert store[policy]["rule"]
        for evidence in store["evidence"]:
            assert (ROOT / evidence).exists(), (store["id"], evidence)


def test_secret_registry_contains_references_not_values_and_names_consumers():
    serialized = json.dumps(_load()["secretReferences"], sort_keys=True)
    for forbidden in ["BEGIN PRIVATE KEY", "postgresql://", "sk_live_", "Bearer "]:
        assert forbidden not in serialized
    for secret in _load()["secretReferences"]:
        assert secret["valueInspected"] is False
        assert secret["reference"] and secret["authorizedConsumers"] and secret["rotationOwner"]


def test_money_writer_registry_exposes_shared_root_and_dormant_capabilities():
    writers = {item["id"]: item for item in _load()["moneyWriters"]}
    assert "SHARED_FULL_SCHEMA_DML" in writers["relay-money-workflows"]["flags"]
    assert {"ROOT_PRINCIPAL", "OVERLAPS_RELAY"} <= set(writers["bot-money-workflows"]["flags"])
    assert writers["isolated-payout-executor"]["credentialRole"] == "obsidian_payout"
    assert writers["kairos-cex-engine"]["reachability"] == "DORMANT_NO_PRODUCT_ROUTE"
    assert "OVERPRIVILEGED_APP_CREDENTIAL_TEMPLATE" in writers["relay-shadow-producer"]["flags"]


def test_independent_shadow_private_keys_are_not_grouped_under_one_owner():
    secrets = {item["id"]: item for item in _load()["secretReferences"]}
    request = secrets["kairos-shadow-request-key"]
    response = secrets["lumi-shadow-response-key"]
    assert request["accountableOwner"] != response["accountableOwner"]
    assert request["authorizedConsumers"] == ["kairos"]
    assert response["authorizedConsumers"] == ["lumi"]


def test_registry_matches_current_runtime_definition_anchors():
    privileges = (ROOT / "deploy" / "postgres" / "runtime_privileges.sql").read_text(encoding="utf-8")
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in privileges
    assert "UPDATE (\n  state, attempts, txid, error_code" in privileges
    units = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "deploy" / "systemd").glob("*.conf"))
    for reference in ["/etc/obsidian-exchange/app.env", "/etc/obsidian-exchange/support.env", "/etc/obsidian-exchange/admin.env"]:
        assert reference in units
    shadow = (ROOT / "deploy" / "relay-shadow.service").read_text(encoding="utf-8")
    assert "postgres/app.active.env" in shadow
