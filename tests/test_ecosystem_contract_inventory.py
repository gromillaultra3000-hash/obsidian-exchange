import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "ecosystem-contracts.v1.json"


def _load():
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_current_inventory_has_exact_components_and_required_edges():
    inventory = _load()
    assert inventory["schema"] == "obsidian-ecosystem-contracts.v1"
    assert {item["id"] for item in inventory["components"]} == {"wallet-relay", "exchange", "kairos", "lumi"}
    edge_ids = [item["id"] for item in inventory["edges"]]
    assert len(edge_ids) == len(set(edge_ids))
    assert set(edge_ids) == {"client-wallet-relay", "wallet-exchange-in-process", "relay-kairos-market",
        "relay-kairos-connectors-read", "relay-kairos-disconnect", "relay-kairos-connect-dormant",
        "relay-kairos-shadow-dormant", "kairos-lumi-register", "kairos-lumi-advisory",
        "operator-kairos-control", "operator-lumi-control", "market-providers-kairos",
        "kairos-cex-engine-dormant", "exchange-payment-providers", "exchange-payout-signer"}


def test_every_edge_closes_auth_data_effect_and_failure_semantics():
    for edge in _load()["edges"]:
        for field in ["authentication", "authorization", "allowedData", "forbiddenData", "stateEffect", "failureSemantics"]:
            assert edge[field], (edge["id"], field)
    connector_edges = [edge for edge in _load()["edges"] if edge["id"].startswith("relay-kairos-connect")]
    assert all("browser ownerRef" in edge["forbiddenData"] for edge in connector_edges)


def test_private_keys_and_credentials_do_not_cross_server_edges():
    inventory = _load()
    assert all(component["canHoldUserPrivateKeys"] is False for component in inventory["components"])
    wallet = next(item for item in inventory["components"] if item["id"] == "wallet-relay")
    kairos = next(item for item in inventory["components"] if item["id"] == "kairos")
    assert wallet["effectiveProcessMoneyWriteCapability"] is True
    assert kairos["effectiveProcessMoneyWriteCapability"] is True
    assert kairos["currentlyReachableMoneyWriter"] is False
    lumi = next(edge for edge in inventory["edges"] if edge["id"] == "kairos-lumi-advisory")
    assert lumi["stateEffect"] == "ADVISORY_ONLY"
    assert {"seed", "private key", "CEX credential", "account id", "wallet address", "raw balance", "money intent"} <= set(lumi["forbiddenData"])
    connect = next(edge for edge in inventory["edges"] if edge["id"] == "relay-kairos-connect-dormant")
    assert any("raw apiKey and apiSecret" in item for item in connect["allowedData"])
    assert "immediate KAIROS vault sealing" in " ".join(connect["allowedData"])
    assert "no enabled product producer" in connect["failureSemantics"]
    shadow = next(edge for edge in inventory["edges"] if edge["id"] == "relay-kairos-shadow-dormant")
    assert "shared Relay service identity" in shadow["authentication"]
    assert "shadow:write" in shadow["authentication"]


def test_inventory_matches_selected_source_anchors():
    relay = (ROOT / "relay-fastapi" / "main.py").read_text(encoding="utf-8")
    identity = (ROOT / "relay" / "core" / "kairos_service_identity.py").read_text(encoding="utf-8")
    kairos = (ROOT / "kairos" / "app" / "main_v19.py").read_text(encoding="utf-8")
    lumi = (ROOT / "lumi" / "lumi" / "app" / "main.py").read_text(encoding="utf-8")
    bridge = (ROOT / "kairos" / "app" / "lumi_bridge.py").read_text(encoding="utf-8")
    connector = (ROOT / "kairos" / "app" / "connector_service.py").read_text(encoding="utf-8")
    for route in ["/api/wallet/cex-sources", "/api/wallet/cex-events", "/api/wallet/portfolio", "/api/wallet/market"]:
        assert route in relay
    for token in ["X-OE-Nonce", "X-OE-Principal", "X-OE-Scope", "Ed25519PrivateKey"]:
        assert token in identity
    for route, scope in [("/internal/v1/connectors", "connectors:read"), ("/internal/v1/connectors/", "connectors:write")]:
        assert route in kairos and scope in kairos
    assert "/internal/v1/connectors:connect" in kairos
    assert "/internal/v1/shadow-decisions" in kairos and "shadow:write" in kairos
    assert '_KAIROS_SERVICE_PATHS = frozenset({"/conflict/resolve", "/integration/hosts/register"})' in lumi
    assert 'verdict["combinedVerdict"] = verdict.get("verdict")' in bridge
    assert "apiKey" in connector and "apiSecret" in connector and ".vault.put(" in connector
    disconnect = relay[relay.index('@app.delete("/api/wallet/cex-sources/{source_id}")'):relay.index('@app.get("/api/wallet/portfolio")')]
    assert 'body.get("confirm") != "DISCONNECT"' in disconnect
    assert "verify_csrf" not in disconnect


def test_current_markdown_has_no_superseded_runtime_claims():
    text = (ROOT / "docs" / "ecosystem-contracts.md").read_text(encoding="utf-8")
    assert "ecosystem-contracts.v1.json" in text
    for stale in ["В приложении нет authentication/authorization middleware", "CORS разрешает `*`",
                  "secrets в исходном виде", "protected endpoints disabled", "Exchange API/Wallet | `relay-fastapi` | root"]:
        assert stale not in text
