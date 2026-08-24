import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = json.loads((ROOT / "docs/e0-3-remediation-plan.v1.json").read_text())


def test_plan_is_non_production_and_keeps_e03_open():
    assert PLAN["stage"] == "E0.3"
    assert PLAN["productionAuthorization"] is False
    assert PLAN["status"] == "IN_PROGRESS"
    assert PLAN["designReviewed"] is True
    assert PLAN["designOwnerAccepted"] is False
    assert PLAN["implementationDeployed"] is False
    assert PLAN["remainingE03Blockers"]
    assert (ROOT / PLAN["ownerDecision"]).exists()


def test_workstreams_are_independent_and_have_fail_closed_rollback():
    streams = {item["id"]: item for item in PLAN["workstreams"]}
    assert set(streams) == {"secret-bundle-split", "database-role-narrowing"}
    assert all(item["independentlyPlanable"] for item in streams.values())
    assert not any(item["deploymentReady"] for item in streams.values())
    assert "never blindly retry" in streams["secret-bundle-split"]["unknownOutcome"]
    assert "never broaden grants ad hoc" in streams["database-role-narrowing"]["unknownOutcome"]
    assert "revoked" in streams["secret-bundle-split"]["rollback"]


def test_secret_target_excludes_unrelated_consumers():
    stream = next(item for item in PLAN["workstreams"] if item["id"] == "secret-bundle-split")
    bundles = {item["id"]: item for item in stream["targetBundles"]}
    provider = bundles["provider-isolated"]
    assert "exchange-notifier.service" in provider["forbiddenConsumers"]
    assert "obsidian-monitor.service" in provider["forbiddenConsumers"]
    assert bundles["telegram-user-api-offline"]["consumers"] == ["explicit offline operator command only"]
    expected = {"btcpay", "platega", "greenpay", "swapuz", "montera", "lava", "brabus", "vertu", "stormtrade", "xpay", "rspay-qr", "rspay-bt"}
    assert set(provider["providerFamilyAllowlist"]) == expected
    assert not (set(provider["providerFamilyAllowlist"]) & set(provider["forbiddenFamilyIds"]))
    assert {item["family"] for item in stream["providerConsumerProposals"]} == expected
    assert all(item["consumerEvidenceStatus"].startswith("NO_GO") for item in stream["providerConsumerProposals"])
    assert stream["referenceSplitSteps"] != stream["credentialRotationSteps"]
    assert any("dual verification" in step for step in stream["credentialRotationSteps"])


def test_database_target_has_separate_roles_and_safe_order():
    stream = next(item for item in PLAN["workstreams"] if item["id"] == "database-role-narrowing")
    assert len(stream["targetLoginRoles"]) == len(set(stream["targetLoginRoles"])) == 4
    assert stream["serviceOrder"] == ["obsidian_relay_shadow", "obsidian_notifier", "obsidian_relay", "obsidian_bot"]
    assert "obsidian_transition_owner" in stream["offlineRoles"]
    assert any("shadow has no money DML" in rule for rule in stream["policy"])


def test_evidence_never_contains_value_material():
    serialized = json.dumps(PLAN).lower()
    for forbidden in ("postgresql://", "begin private key", "bearer ", "secretvalue", "tokenvalue"):
        assert forbidden not in serialized


def test_owner_decision_is_accountability_only_and_not_deploy_authority():
    decision = (ROOT / PLAN["ownerDecision"]).read_text()
    normalized = " ".join(decision.split())
    assert "Status: ACCEPTED" in decision
    assert "sole accountable principal" in normalized
    assert "they are not accountable owners" in normalized
    assert "does not authorize production deployment or restart" in normalized
    assert {"credential mismatch between endpoints", "permission denial on a money path", "unreconciled queue/payment/payout state"} <= set(PLAN["stopConditions"])
