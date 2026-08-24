import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_e0_4_bounded_matrix_is_structurally_complete_and_non_authorizing():
    value = json.loads((ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    surfaces = value["surfaces"]
    assert surfaces == ["telegramBot", "site", "miniApp", "admin", "api", "native"]
    assert value["status"] == "IN_PROGRESS"
    assert value["productionMutation"] is False
    assert value["scope"] == "BOUNDED_TWENTY_FIVE_FEATURE_SLICE"
    assert len(value["features"]) == 25
    assert {item["id"] for item in value["features"]} >= {
        "CUSTOMER_SUPPORT", "REFERRAL_PROGRAM", "DCA_SCHEDULES", "LIMIT_ORDERS",
        "GIFT_VOUCHERS", "EXTERNAL_WALLET_LINKING", "CEX_PORTFOLIO", "OPERATOR_WORKFLOWS",
        "NATIVE_SIGNING", "LUMI_ADVISORY", "SWAPS", "ACCOUNT_AUTH_PROFILE",
        "LUMI_CONTROL_PLANE", "KAIROS_AUTONOMOUS_TRADE_CONTROL",
        "PAYMENT_PROVIDER_LIFECYCLE", "PAYOUT_SETTLEMENT_RECONCILIATION",
        "WALLET_RECEIVE_TRANSFER", "PUBLIC_MARKET_INFORMATION", "CUSTOMER_ENGAGEMENT",
        "OPERATIONS_MONITORING", "AI_ASSISTANT"
    }
    assert "support" not in value["omittedFeatureFamilies"]
    assert "referrals" not in value["omittedFeatureFamilies"]
    assert "DCA" not in value["omittedFeatureFamilies"]
    assert "limit orders" not in value["omittedFeatureFamilies"]
    assert "gifts" not in value["omittedFeatureFamilies"]
    assert "wallet linking" not in value["omittedFeatureFamilies"]
    assert "CEX portfolio" not in value["omittedFeatureFamilies"]
    assert "operator workflows" not in value["omittedFeatureFamilies"]
    assert "native signing" not in value["omittedFeatureFamilies"]
    assert "LUMI advisory" not in value["omittedFeatureFamilies"]
    assert "PUBLIC_MARKET_INFORMATION" not in value["omittedFeatureFamilies"]
    assert "CUSTOMER_ENGAGEMENT" not in value["omittedFeatureFamilies"]
    assert "OPERATIONS_MONITORING" not in value["omittedFeatureFamilies"]
    assert "AI_ASSISTANT" not in value["omittedFeatureFamilies"]
    assert "KAIROS_EXCHANGE_DISCOVERY" not in value["omittedFeatureFamilies"]
    assert value["nextCanonicalItem"].startswith("Return to owner-blocked E0.3 as the first unmet criterion")
    reconciliation = json.loads(
        (ROOT / "docs/e0-4-deployed-route-feature-reconciliation.v1.json").read_text()
    )
    classified_ids = {item["id"] for item in value["features"]}
    assert value["omittedFeatureFamilies"] == [
        item["id"] for item in reconciliation["unclassifiedFamilies"]
        if item["id"] not in classified_ids
    ]
    assert len({item["id"] for item in value["features"]}) == len(value["features"])
    for item in value["features"]:
        assert list(item["cells"]) == surfaces
        for cell in item["cells"].values():
            assert cell["mode"] in value["allowedModes"]
            assert cell["implementation"] in value["allowedImplementationStates"]
            assert cell["reason"].strip()
            assert cell["evidence"]
            for anchor in cell["evidence"]:
                path = anchor.split("#", 1)[0]
                assert (ROOT / path).exists(), anchor


def test_064a_deferral_is_restrictive_not_acceptance():
    value = json.loads((ROOT / "docs/e0-3-bot-b5-3-064a-owner-deferral.v1.json").read_text())
    assert value["status"] == "BLOCKED_OWNER"
    assert value["ownerDeferralDecisionPresent"] is True
    assert value["authenticated064AAcceptancePresent"] is False
    assert value["independentReviewerApprovalPresent"] is False
    for field in ("productionAuthorization", "productionMutationAuthorized",
                  "deploymentAuthorized", "restartAuthorized", "cutoverAuthorized",
                  "telegramDeliveryAuthorized", "ambiguousSendingDispositionAuthorized",
                  "actionAllowed"):
        assert value[field] is False


def test_e0_4_runtime_observations_are_read_only_bounded_and_non_accepting():
    value = json.loads((ROOT / "docs/e0-4-route-runtime-observations.v1.json").read_text())
    assert value["status"] == "IN_PROGRESS"
    assert value["observationClass"] == "READ_ONLY_UNAUTHENTICATED_LOCAL_PRODUCTION"
    for field in ("productionMutation", "authenticationUsed", "postRequestsMade",
                  "telegramMessagesSent", "databaseQueriesMade"):
        assert value[field] is False
    assert {item["feature"] for item in value["featureFindings"]} == {
        "RUB_BUY_CRYPTO", "CRYPTO_SELL_RUB", "CUSTOMER_ORDER_HISTORY",
        "CUSTOMER_SUPPORT", "REFERRAL_PROGRAM"
    }
    assert all(item["acceptance"].startswith("PARTIAL_")
               for item in value["featureFindings"])
    observed = {(item["surface"], item["path"], item["statusCode"])
                for item in value["httpObservations"]}
    assert ("miniApp", "/webapp", 200) in observed
    assert ("api", "/api/history", 403) in observed
    assert ("api", "/api/referral_stats", 403) in observed
    assert "data-tab=support" in value["miniAppDomMarkers"]["absent"]
    equality = value["source"]["checkoutDeploymentEquality"]
    assert equality == {"miniApp": True, "relay": False, "telegramBot": False}
    assert value["independentReview"]["disposition"] == "ACCEPTED_AND_INCORPORATED"
    assert value["independentReview"]["changesMade"] is False


def test_e0_4_authenticated_rehearsal_is_synthetic_and_non_effectful():
    value = json.loads((ROOT / "docs/e0-4-authenticated-synthetic-read-rehearsal.v1.json").read_text())
    assert value["status"] == "IN_PROGRESS"
    assert value["workClass"] == "ISOLATED_NON_PRODUCTION_AUTHENTICATED_READ_REHEARSAL"
    for field in ("productionMutation", "productionCredentialsUsed",
                  "externalNetworkAttempted", "telegramMessagesSent",
                  "postRequestsMade", "moneyWritersExercised"):
        assert value[field] is False
    assert value["isolation"]["backgroundTasksEnabled"] is False
    assert value["isolation"]["appLifespanEntered"] is False
    assert value["test"]["result"] == "PASS"
    assert value["independentReview"]["finalDisposition"] == "ACCEPTED_WITH_NARROWED_CLAIM"


def test_e0_4_artifact_drift_reconciliation_is_bounded_and_non_authorizing():
    value = json.loads((ROOT / "docs/e0-4-artifact-drift-reconciliation.v1.json").read_text())
    assert value["status"] == "IN_PROGRESS"
    assert value["workClass"] == "READ_ONLY_ARTIFACT_DRIFT_RECONCILIATION"
    for field in ("productionMutation", "deploymentAuthorized", "restartAuthorized",
                  "telegramMessagesSent", "databaseQueriesMade"):
        assert value[field] is False
    assert value["runtimeProvenance"]["relay"]["entrypoint"] == \
        "/opt/obsidian-exchange/relay-fastapi/main.py"
    assert value["runtimeProvenance"]["telegramBot"]["entrypoint"] == \
        "/opt/obsidian-exchange/bot/main_bot.py"
    assert {item["component"] for item in value["artifacts"]} == {"relay", "telegramBot"}
    assert all(item["equal"] is False for item in value["artifacts"])
    assert any("DEFERRED_NOTIFICATION_MONEY_WRITER_PROPOSAL" in item["classification"]
               for item in value["artifacts"])
    assert value["securityInterruption"]["secretValueRecorded"] is False
    assert value["securityInterruption"]["status"] == "BLOCKED_OWNER"
    assert len(value["independentReviews"]) == 3
