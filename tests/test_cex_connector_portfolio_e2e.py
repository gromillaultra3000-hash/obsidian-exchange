"""Hermetic Relay -> KAIROS connector/portfolio lifecycle.

The fixture exercises the real signed service boundary and encrypted connector
store.  Provider permission and balance replies are synthetic, so the test
cannot contact Bybit or mutate production state.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = ROOT / "kairos"
RELAY_ROOT = ROOT / "relay"
# KAIROS must precede Relay because Relay also has a legacy ``app.py`` while
# KAIROS imports its package as ``app.*``.  Relay remains available for
# ``core.*`` imports at the next search position.
for path in (RELAY_ROOT, KAIROS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.connector_balance_worker import refresh_bybit_balance
from app.connector_permission_worker import verify_bybit_connector
from app.connector_service import ConnectRequest, ConnectorService
from app.connector_store import ConnectorStore
from app.relay_identity import ReplayStore, load_public_keys, verify_relay_request
from app.secret_vault import KairosSecretVault
import app.connector_store as connector_store_module
from core import kairos_service_identity
from core.unified_portfolio import aggregate


NOW = datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)
API_KEY = "synthetic-testnet-key"
API_SECRET = "synthetic-testnet-secret"


class _InProcessResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"in-process KAIROS returned {self.status_code}")

    def json(self):
        return self._payload


def _permission_payload() -> dict:
    return {
        "retCode": 0,
        "time": int(NOW.timestamp() * 1000),
        "result": {
            "apiKey": API_KEY,
            "userID": "424242",
            "parentUid": "0",
            "isMaster": True,
            "readOnly": 1,
            "ips": ["192.0.2.10"],
            "permissions": {"ContractTrade": ["Position"], "Spot": []},
        },
    }


def _balance_payload() -> dict:
    return {
        "retCode": 0,
        "time": int(NOW.timestamp() * 1000),
        "result": {"list": [{"coin": [{
            "coin": "USDT",
            "walletBalance": "12.3400",
            "availableToWithdraw": "12.3400",
            "locked": "0",
        }]}]},
    }


def _lane(portfolio: dict, lane_id: str) -> dict:
    return next(item for item in portfolio["lanes"] if item["id"] == lane_id)


def test_connect_list_portfolio_disconnect_preserves_non_cex_lanes(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signing_file = tmp_path / "relay-signing.key"
    principal_file = tmp_path / "relay-principal.key"
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    signing_file.write_text(base64.urlsafe_b64encode(private_raw).decode(), encoding="ascii")
    principal_file.write_text(base64.urlsafe_b64encode(b"p" * 32).decode(), encoding="ascii")
    (public_dir / "relay-v1.pub").write_text(
        base64.urlsafe_b64encode(public_raw).decode().rstrip("="), encoding="ascii")

    vault_key = tmp_path / "vault.key"
    vault_key.write_bytes(base64.urlsafe_b64encode(b"v" * 32))
    store = ConnectorStore(
        tmp_path / "connectors.json",
        KairosSecretVault(tmp_path / "vault.enc", vault_key),
    )
    monkeypatch.setattr(
        connector_store_module.secrets, "token_urlsafe",
        lambda _: "deterministic_source_identifier_1234567890",
    )
    monkeypatch.setenv("KAIROS_RELAY_PUBLIC_KEYS_DIR", str(public_dir))
    monkeypatch.setenv("KAIROS_RELAY_REPLAY_FILE", str(tmp_path / "replay.json"))
    monkeypatch.setenv("RELAY_KAIROS_PRIVATE_KEY_FILE", str(signing_file))
    monkeypatch.setenv("RELAY_KAIROS_PRINCIPAL_KEY_FILE", str(principal_file))
    monkeypatch.setenv("KAIROS_URL", "http://127.0.0.1:8000")

    def in_process_request(method, url, *, headers, data, timeout, allow_redirects):
        assert timeout == 5.0
        assert allow_redirects is False
        parsed = urlsplit(url)
        body = data or b""
        required_scope = "connectors:read" if method == "GET" else "connectors:write"
        verified_principal = verify_relay_request(
            method=method, path=parsed.path, query=parsed.query, body=body,
            headers=headers, public_keys=load_public_keys(public_dir),
            replay_store=ReplayStore(tmp_path / "replay.json"),
            required_scope=required_scope,
            now_epoch=int(headers["X-OE-Timestamp"]),
        )
        service = ConnectorService(store)
        if method == "POST" and parsed.path == "/internal/v1/connectors:connect":
            item = service.connect(
                owner_ref=verified_principal,
                request=ConnectRequest.model_validate(json.loads(body)),
            )
            return _InProcessResponse(
                202, {"schemaVersion": "connector-operation.v1", "item": item})
        if method == "GET" and parsed.path == "/internal/v1/connectors":
            return _InProcessResponse(200, {
                "schemaVersion": "connector-list.v1",
                "items": store.list_for_owner(verified_principal),
            })
        if method == "GET" and parsed.path == "/internal/v1/connector-events":
            return _InProcessResponse(200, {
                "schemaVersion": "connector-events.v1",
                "items": store.events_for_owner(verified_principal),
            })
        prefix = "/internal/v1/connectors/"
        if method == "DELETE" and parsed.path.startswith(prefix):
            item = service.disconnect(
                owner_ref=verified_principal, source_id=parsed.path[len(prefix):])
            return _InProcessResponse(
                200, {"schemaVersion": "connector-operation.v1", "item": item})
        return _InProcessResponse(404, {"detail": "Not found"})

    monkeypatch.setattr(kairos_service_identity.requests, "request", in_process_request)
    principal = kairos_service_identity.principal_for_web_user(77)

    created = kairos_service_identity.signed_request(
        "POST", "/internal/v1/connectors:connect",
        principal=principal, scope="connectors:write",
        payload={
            "providerId": "bybit",
            "idempotencyKey": "fixture_0123456789abcdef",
            "credential": {"apiKey": API_KEY, "apiSecret": API_SECRET},
        },
    )
    source_id = created["item"]["source"]["sourceId"]
    assert created["item"]["source"]["state"] == "PENDING_PROOF"

    verify_bybit_connector(
        store=store, owner_ref=principal, source_id=source_id,
        fetch=lambda **_: _permission_payload(), now=NOW)
    refresh_bybit_balance(
        store=store, owner_ref=principal, source_id=source_id,
        fetch=lambda **_: _balance_payload(), now=NOW)

    listed = kairos_service_identity.signed_get(
        "/internal/v1/connectors", principal=principal, scope="connectors:read")
    assert listed["schemaVersion"] == "connector-list.v1"
    assert listed["items"][0]["balances"][0]["total"] == "12.3400"

    wallets = [{"chain": "BTC", "address": "bc1-fixture", "status": "OK", "balance": "0.5"}]
    orders = [
        {"status": "sent", "created_at": "2026-08-10T21:00:00+00:00"},
        {"status": "pending", "created_at": "2026-08-10T20:00:00+00:00"},
    ]
    before = aggregate(
        wallets=wallets, exchange_orders=orders, cex_items=listed["items"],
        cex_available=True, observed_at=NOW)
    assert _lane(before, "verified_exchanges")["sources"][0]["balances"][0]["total"] == "12.3400"

    revoked = kairos_service_identity.signed_request(
        "DELETE", f"/internal/v1/connectors/{source_id}",
        principal=principal, scope="connectors:write")
    assert revoked["item"]["source"]["state"] == "REVOKED"
    assert revoked["item"]["balances"] == []
    assert revoked["item"]["balanceCheckedAt"] is None

    after_list = kairos_service_identity.signed_get(
        "/internal/v1/connectors", principal=principal, scope="connectors:read")
    events = kairos_service_identity.signed_get(
        "/internal/v1/connector-events", principal=principal, scope="connectors:read")
    after = aggregate(
        wallets=wallets, exchange_orders=orders, cex_items=after_list["items"],
        cex_available=True, observed_at=NOW)

    assert _lane(after, "verified_exchanges")["sources"][0]["balances"] == []
    assert _lane(after, "wallets") == _lane(before, "wallets")
    assert _lane(after, "obsidian_exchange") == _lane(before, "obsidian_exchange")
    assert _lane(after, "obsidian_exchange")["sources"][0]["activity"] == {
        "orderCount": 2,
        "successfulOrderCount": 1,
        "latestOrderAt": "2026-08-10T21:00:00+00:00",
    }
    assert [event["type"] for event in reversed(events["items"])] == [
        "CONNECT_REQUESTED", "PERMISSION_VERIFIED", "BALANCE_REFRESHED",
        "DISCONNECT_REQUESTED", "DISCONNECTED",
    ]
    assert all(set(event) == {"providerId", "type", "state", "at", "category"}
               for event in events["items"])
    public_material = json.dumps(
        {"created": created, "listed": listed, "before": before,
         "revoked": revoked, "after": after, "events": events}, sort_keys=True)
    assert API_KEY not in public_material
    assert API_SECRET not in public_material
    assert "vault://" not in public_material
    assert principal not in public_material
    assert source_id not in json.dumps(events, sort_keys=True)
