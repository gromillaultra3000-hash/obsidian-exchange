import glob
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECOMPOSITION = json.loads((ROOT / "docs/e0-3-bot-b5-1-writer-decomposition.v1.json").read_text())


def _generated_methods():
    spec = importlib.util.spec_from_file_location(
        "bot_matrix", ROOT / "scripts/e0_bot_method_capability_matrix.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()["methods"]


def test_b51_is_exact_remaining_writer_set():
    methods = _generated_methods()
    writers = {x["id"] for x in methods if x["capabilityClass"] == "WRITER_OR_SCHEMA"}
    rehearsed = set()
    for path in glob.glob(str(ROOT / "docs/e0-3-bot-b[1-4]*-rehearsal.v1.json")):
        rehearsed.update(json.loads(Path(path).read_text()).get("methodCoverage", []))
    shared = {
        x["id"]
        for x in json.loads((ROOT / "docs/e0-3-relay-writer-matrix.v1.json").read_text())["writers"]
    }
    packages = DECOMPOSITION["orderedPackages"]
    declared = [method for package in packages for method in package["methods"]]
    assert len(declared) == len(set(declared)) == 39
    assert set(declared) == writers - rehearsed - shared
    assert not set(declared) & rehearsed
    assert not set(declared) & shared


def test_b51_packages_bind_existing_capability_contracts_and_risk_classes():
    capabilities = set()
    for path in (ROOT / "docs").glob("e0-3-bot-*-capabilities.v1.json"):
        capabilities.update(x["id"] for x in json.loads(path.read_text())["capabilities"])
    packages = DECOMPOSITION["orderedPackages"]
    assert [x["id"] for x in packages] == [
        "B5.2_RESIDUAL_IDENTITY_SUPPORT_CONFIG_WRITERS",
        "B5.3_BOT_NOTIFICATION_QUEUE_WRITERS",
        "B5.4_ORDER_CREATION_WRITER",
        "B5.5_AUTOMATION_AND_GIFT_WRITERS",
        "B5.6_STATUS_NOTIFICATION_COMPLETION_WRITER",
        "B5.7_RECONCILIATION_OUTBOX_LIFECYCLE_WRITERS",
        "B5.8_PAYOUT_INTENT_CREATION_WRITERS",
        "B5.9_SELL_CLAIM_RELEASE_REJECT_WRITERS",
        "B5.10_PAYOUT_CHAIN_EVIDENCE_AND_RECOVERY_WRITERS",
        "B5.11_MONEY_FINALIZATION_WRITERS",
    ]
    assert {method for package in packages for method in package["methods"]} <= capabilities
    assert all(package["risk"] in {"CONSEQUENTIAL_WRITE", "OUTBOX_WRITE", "MONEY_WRITE", "MONEY_OR_VALUE_WRITE", "MONEY_AND_OUTBOX_WRITE"} for package in packages)


def test_b51_is_non_production_inventory_only():
    assert DECOMPOSITION["status"] == "VERIFIED"
    assert DECOMPOSITION["productionAuthorization"] is False
    assert DECOMPOSITION["implementationDeployed"] is False
    assert DECOMPOSITION["rollout"] == "None; decomposition evidence only."
    assert DECOMPOSITION["nextPrerequisite"].startswith("B5.2 residual")
