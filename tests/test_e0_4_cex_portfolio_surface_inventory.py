import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cex_portfolio_has_exact_six_surface_inventory_and_bounded_observation():
    matrix = json.loads((ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    item = next(feature for feature in matrix["features"] if feature["id"] == "CEX_PORTFOLIO")
    assert list(item["cells"]) == matrix["surfaces"]
    assert item["overallStatus"] == "PARTIAL_NOT_ACCEPTED"
    assert item["moneyWriter"] is False and item["credentialLifecycle"] is True
    assert all(item["cells"][name]["mode"] == "REQUIRED"
               for name in ("telegramBot", "site", "miniApp", "api", "native"))
    assert item["cells"]["admin"]["mode"] == "OPERATOR_ONLY"
    assert item["cells"]["telegramBot"]["implementation"] == "NOT_IMPLEMENTED"
    assert item["cells"]["native"]["implementation"] == "NOT_IMPLEMENTED"
    assert all(item["cells"][name]["implementation"] == "PARTIAL"
               for name in ("site", "miniApp", "admin", "api"))
    assert "CEX portfolio" not in matrix["omittedFeatureFamilies"]
    assert "LUMI advisory" not in matrix["omittedFeatureFamilies"]

    evidence = json.loads((ROOT / "docs/e0-4-cex-portfolio-runtime-observation.v1.json").read_text())
    for field in ("productionMutation", "authenticatedCustomerAction", "customerDataObserved",
                  "credentialMaterialObserved", "externalProviderCalled", "connectorWriterExercised"):
        assert evidence[field] is False
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert evidence["runtime"]["connectorStore"]["present"] is False
    assert evidence["runtime"]["connectorRefresh"] == {"configured": True, "intervalSeconds": 300}
    assert {row["statusCode"] for row in evidence["unauthenticatedProbes"]
            if row["path"] != "/webapp"} == {401, 403}
    assert evidence["surfaceFindings"]["telegramBot"]["implementation"] == "NOT_IMPLEMENTED"


def test_cex_runtime_hashes_and_truthfulness_landmines_remain_bound():
    evidence = json.loads((ROOT / "docs/e0-4-cex-portfolio-runtime-observation.v1.json").read_text())
    pairs = {
        "kairosMain": ("kairos/app/main_v19.py", "/opt/kairos/app/main_v19.py"),
        "connectorStore": ("kairos/app/connector_store.py", "/opt/kairos/app/connector_store.py"),
        "connectorBalanceWorker": ("kairos/app/connector_balance_worker.py", "/opt/kairos/app/connector_balance_worker.py"),
        "bybitBalanceTransport": ("kairos/app/bybit_balance_transport.py", "/opt/kairos/app/bybit_balance_transport.py"),
        "bybitTestnetTransport": ("kairos/app/bybit_testnet_transport.py", "/opt/kairos/app/bybit_testnet_transport.py"),
        "unifiedPortfolio": ("relay/core/unified_portfolio.py", "/opt/obsidian-exchange/relay/core/unified_portfolio.py"),
        "relayServiceIdentity": ("relay/core/kairos_service_identity.py", "/opt/obsidian-exchange/relay/core/kairos_service_identity.py"),
        "miniApp": ("relay/webapp.html", "/opt/obsidian-exchange/relay/webapp.html"),
    }
    for name, (checkout, deployed) in pairs.items():
        digest = hashlib.sha256((ROOT / checkout).read_bytes()).hexdigest()
        assert digest == evidence["artifacts"][name]["sha256"]
        assert hashlib.sha256(Path(deployed).read_bytes()).hexdigest() == digest

    relay = evidence["artifacts"]["relayMain"]
    assert hashlib.sha256((ROOT / "relay-fastapi/main.py").read_bytes()).hexdigest() == relay["checkoutSha256"]
    assert hashlib.sha256(Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_bytes()).hexdigest() == relay["deployedSha256"]
    assert relay["checkoutEqualsDeployed"] is False

    main = (ROOT / "relay-fastapi/main.py").read_text()
    portfolio = main[main.index("async def api_wallet_portfolio"):main.index("async def api_wallet_market")]
    aggregate = (ROOT / "relay/core/unified_portfolio.py").read_text()
    balance = (ROOT / "kairos/app/bybit_balance_transport.py").read_text()
    assert "cex_available = isinstance(cex_result, dict)" in portfolio
    assert 'cex_result.get("items", [])' in portfolio
    assert 'schemaVersion") != "connector-list.v1"' not in portfolio
    assert '"EMPTY" if not cex_sources' in aggregate
    assert "server_ms" in balance and "timedelta" not in balance
    assert any("negative" in finding for finding in evidence["riskFindings"])
    assert any("CSRF" in finding for finding in evidence["riskFindings"])
    assert {review["disposition"] for review in evidence["independentReviews"]} == {
        "ACCEPTED_PARTIAL_NOT_ACCEPTED", "REJECTED_ACCEPTANCE_FINDINGS_INCORPORATED"}
