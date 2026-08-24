import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "docs/secret-reference-members.v1.json").read_text())
STATUSES = {"VERIFIED", "PARTIAL", "UNKNOWN", "MISSING", "DORMANT", "NOT_APPLICABLE"}


def test_snapshot_is_metadata_only_and_honestly_in_progress():
    assert DATA["secretValuesStoredOrEmitted"] is False
    assert DATA["reviewerSawCredentialValues"] is False
    assert DATA["credentialMaterialHandledByPrivilegeVerifier"] is True
    assert DATA["coverageStatus"] == "IN_PROGRESS"
    assert DATA["ownerAssignmentsAccepted"] is True
    assert (ROOT / DATA["ownerDecisionEvidence"]).exists()
    assert set(DATA["statusVocabulary"]) == STATUSES
    serialized = json.dumps(DATA)
    for forbidden in ("postgresql://", "BEGIN PRIVATE KEY", "seed phrase", "api_key="):
        assert forbidden not in serialized


def test_shared_bundle_has_expected_secret_member_names():
    sources = {item["id"]: item for item in DATA["sources"]}
    app = set(sources["obsidian-app-env"]["members"])
    required = {"BOT_TOKEN", "BTCPAY_API_KEY", "PLATEGA_SECRET", "RELAY_SECRET",
                "INTERNAL_ADMIN_SECRET", "TG_API_HASH", "RSPAY_API_SECRET"}
    assert required <= app
    assert "SHARED_BUNDLE" in sources["obsidian-app-env"]["flags"]
    assert "authorizedConsumers" not in sources["obsidian-app-env"]
    assert len(sources["obsidian-app-env"]["effectiveConsumers"]) == 4
    assert sources["callback-handler-env"]["status"] == "MISSING"


def test_logical_shared_token_and_shadow_keys_keep_correct_boundaries():
    credentials = {item["id"]: item for item in DATA["logicalCredentials"]}
    token = credentials["kairos-lumi-service-token"]
    assert token["member"] == "LUMI_KAIROS_TOKEN"
    assert len(token["distribution"]) == 2
    assert "atomic" in token["rotationRequirement"]
    sources = {item["reference"]: item for item in DATA["sources"]}
    assert all("LUMI_KAIROS_TOKEN" in sources[path]["members"] for path in token["distribution"])
    assert {"KAIROS_VAULT_KEY_FILE", "KAIROS_VAULT_FILE"} <= set(sources["/etc/kairos/security.env"]["members"])
    assert credentials["kairos-shadow-request-key"]["proposedAccountableOwner"] != credentials["lumi-shadow-response-key"]["proposedAccountableOwner"]


def test_every_secret_record_has_lifecycle_statuses_from_closed_vocabulary():
    for item in DATA["sources"] + DATA["logicalCredentials"]:
        for field in ("accessStatus", "rotationStatus", "revocationStatus", "expiryStatus"):
            assert item[field] in STATUSES


def test_postgres_service_bindings_are_exact_and_staged_refs_are_visible():
    bindings = {item["service"]: item for item in DATA["postgresBindings"]}
    assert bindings["relay-fastapi.service"]["databaseRole"] == "obsidian_app"
    assert bindings["exchange-bot.service"]["databaseRole"] == "obsidian_app"
    assert bindings["exchange-notifier.service"]["databaseRole"] == "obsidian_app"
    assert bindings["obsidian-monitor.service"]["databaseRole"] == "obsidian_readonly"
    assert bindings["support-bot.service"]["databaseRole"] == "obsidian_readonly"
    assert bindings["admin-panel.service"]["databaseRole"] == "obsidian_readonly"
    assert bindings["obsidian-payout-worker.service"]["databaseRole"] == "obsidian_payout"
    assert bindings["relay-shadow.service"]["databaseRole"] == "obsidian_app"
    assert bindings["relay-shadow.service"]["roleObservationStatus"] == "DORMANT"
    assert all(item["stagedReference"].endswith(".staged.env") for item in bindings.values())


def test_dangerous_legacy_references_are_never_silently_omitted():
    refs = {item["id"]: item for item in DATA["prohibitedOrDormantReferences"]}
    assert refs["bot-usdt-private-key"]["disposition"] == "FORBIDDEN_IN_BOT"
    assert refs["legacy-payout-seed"]["disposition"] == "FORBIDDEN_IN_RUNTIME"
    assert refs["legacy-cex-env"]["presenceStatus"] == "MISSING"
    assert refs["callback-telegram-token"]["presenceStatus"] == "MISSING"
    assert all(item["valueInspected"] is False for item in refs.values())


def test_app_members_are_partitioned_into_accountable_families():
    source = next(item for item in DATA["sources"] if item["id"] == "obsidian-app-env")
    families = DATA["credentialFamilies"]
    family_members = [name for family in families for name in family["envNames"]]
    assert set(family_members) == set(source["members"])
    assert len(family_members) == len(set(family_members))
    assert all(family["proposedAccountableOwner"] for family in families)
    assert all(family["desiredConsumers"] and family["effectiveConsumers"] for family in families)
    assert {"rspay-qr", "rspay-bt"} <= {family["id"] for family in families}


def test_repo_anchors_for_roles_and_member_names_exist():
    grants = (ROOT / "deploy/postgres/runtime_privileges.sql").read_text()
    assert "TO obsidian_app" in grants
    assert "TO obsidian_readonly" in grants
    assert "TO obsidian_payout" in grants
    source = "\n".join(p.read_text(errors="ignore") for p in [
        ROOT / "bot/main_bot.py", ROOT / "relay-fastapi/main.py",
        ROOT / "kairos/app/main_v19.py", ROOT / "lumi/lumi/app/main.py",
    ])
    for name in ("BOT_TOKEN", "INTERNAL_ADMIN_SECRET", "LUMI_KAIROS_TOKEN"):
        assert name in source


def test_manifest_has_no_value_bearing_fields_or_secret_shaped_strings():
    forbidden_fields = {"value", "currentValue", "secretValue", "hash", "fingerprint", "ciphertext", "dsn", "passwordValue", "tokenValue"}
    patterns = [
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"\bBearer\s+[A-Za-z0-9._~-]+", re.I),
        re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@", re.I),
        re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        re.compile(r"\b[0-9a-fA-F]{64,}\b"),
    ]

    def walk(value):
        if isinstance(value, dict):
            assert not (set(value) & forbidden_fields)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)
        elif isinstance(value, str):
            assert not any(pattern.search(value) for pattern in patterns)

    walk(DATA)
