#!/usr/bin/env python3
"""Fail-closed readiness gate for the keyless E1 read-only CEX surface."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


VERSIONS = {
    "connector-list.v1": "connector-list.v1.json",
    "connector-events.v1": "connector-events.v1.json",
    "unified-portfolio.v1": "unified-portfolio.v1.json",
}
SOURCE_STATES = {
    "PENDING_PROOF", "READ_ONLY_VERIFIED", "DEGRADED", "BLOCKED",
    "REVOKING", "REVOKED",
}
LANE_STATES = {"EMPTY", "AVAILABLE", "DEGRADED", "UNAVAILABLE"}
EVENT_TYPES = {
    "CONNECT_REQUESTED", "PERMISSION_VERIFIED", "BALANCE_REFRESHED",
    "DATA_DEGRADED", "ACCESS_BLOCKED", "DISCONNECT_REQUESTED", "DISCONNECTED",
}
FORBIDDEN_EVENT_KEYS = {
    "ownerRef", "sourceId", "accountRef", "credentialRef", "credential",
    "apiKey", "apiSecret", "vaultRef",
}
PORTFOLIO_BALANCE_KEYS = {
    "assetId", "network", "total", "available", "locked", "state",
    "asOf", "observedAt", "errorCode",
}


def _exact(value, keys, label, errors):
    if not isinstance(value, dict) or set(value) != set(keys):
        errors.append(f"{label}: exact fields differ")
        return False
    return True


def _load(path: Path, errors):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path}: unreadable fixture ({type(exc).__name__})")
        return {}


def _validate_fixtures(contract_dir: Path, errors):
    fixtures = {version: _load(contract_dir / name, errors)
                for version, name in VERSIONS.items()}
    connector = fixtures["connector-list.v1"]
    if _exact(connector, {"schemaVersion", "sources"}, "connector-list", errors):
        if connector["schemaVersion"] != "connector-list.v1" or not isinstance(connector["sources"], list):
            errors.append("connector-list: version/sources invalid")
        for item in connector.get("sources", []):
            if not _exact(item, {"source", "revision", "permissionCheckedAt", "lastErrorCode",
                                 "credentialPresent", "revokedAt", "balanceCheckedAt", "balances"},
                          "connector item", errors):
                continue
            source = item["source"]
            if not _exact(source, {"sourceId", "kind", "custodyDomain", "providerId",
                                   "accountRef", "state"}, "connector source", errors):
                continue
            if source["kind"] != "CEX_ACCOUNT" or source["custodyDomain"] != "CEX_CUSTODY" \
                    or source["state"] not in SOURCE_STATES:
                errors.append("connector source: custody/state invariant failed")
            if not isinstance(item["balances"], list):
                errors.append("connector item: balances is not a list")
            for balance in item["balances"] if isinstance(item["balances"], list) else []:
                if not _exact(balance, {"schemaVersion", "sourceId", "custodyDomain"}
                                      | PORTFOLIO_BALANCE_KEYS, "connector balance", errors):
                    continue
                if balance["schemaVersion"] != "portfolio-balance.v1" \
                        or balance["custodyDomain"] != "CEX_CUSTODY":
                    errors.append("connector balance: version/custody differs")

    events = fixtures["connector-events.v1"]
    if _exact(events, {"schemaVersion", "retentionDays", "maxStoredEvents", "events"},
              "connector-events", errors):
        if events["schemaVersion"] != "connector-events.v1" \
                or events["retentionDays"] != 90 or events["maxStoredEvents"] != 1000:
            errors.append("connector-events: frozen retention/version differs")
        for event in events.get("events", []):
            if not _exact(event, {"providerId", "type", "state", "at", "category"},
                          "connector event", errors):
                continue
            if event["type"] not in EVENT_TYPES or event["state"] not in SOURCE_STATES:
                errors.append("connector event: type/state invalid")
            if FORBIDDEN_EVENT_KEYS & set(event):
                errors.append("connector event: private identifier exposed")

    portfolio = fixtures["unified-portfolio.v1"]
    if _exact(portfolio, {"schemaVersion", "observedAt", "complete", "issues", "lanes"},
              "unified-portfolio", errors):
        lanes = portfolio.get("lanes")
        expected = [
            ("wallets", "SELF_CUSTODY"),
            ("obsidian_exchange", "OBSIDIAN_OPERATIONAL"),
            ("verified_exchanges", "CEX_CUSTODY"),
        ]
        actual = [(lane.get("id"), lane.get("custodyDomain"))
                  for lane in lanes] if isinstance(lanes, list) else []
        if portfolio["schemaVersion"] != "unified-portfolio.v1" or actual != expected:
            errors.append("unified-portfolio: version/custody lane order differs")
        for lane in lanes if isinstance(lanes, list) else []:
            if not _exact(lane, {"id", "custodyDomain", "state", "sources"},
                          "portfolio lane", errors) or lane.get("state") not in LANE_STATES:
                errors.append("portfolio lane: fields/state invalid")
                continue
            for source in lane.get("sources", []):
                common = {"sourceId", "kind", "custodyDomain", "providerId", "state", "balances"}
                expected_keys = common
                if source.get("kind") == "OBSIDIAN_EXCHANGE":
                    expected_keys = common | {"activity"}
                elif source.get("kind") == "CEX_ACCOUNT":
                    expected_keys = common | {"permissionCheckedAt", "balanceCheckedAt", "lastErrorCode"}
                if not _exact(source, expected_keys, "portfolio source", errors):
                    continue
                if source.get("custodyDomain") != lane.get("custodyDomain"):
                    errors.append("portfolio source: custody crosses lane")
                for balance in source.get("balances", []):
                    _exact(balance, PORTFOLIO_BALANCE_KEYS, "portfolio balance", errors)
    return fixtures


def _validate_sources(root: Path, kairos_root: Path, fixtures, errors):
    paths = {
        "relay_main": root / "relay-fastapi/main.py",
        "portfolio": root / "relay/core/unified_portfolio.py",
        "webapp": root / "relay/webapp.html",
        "kairos_main": kairos_root / "app/main_v19.py",
        "store": kairos_root / "app/connector_store.py",
    }
    source = {}
    for name, path in paths.items():
        try:
            source[name] = path.read_text(encoding="utf-8")
        except OSError:
            errors.append(f"{name}: source missing")
            source[name] = ""
    for version in VERSIONS:
        if version == "unified-portfolio.v1":
            if f'SCHEMA_VERSION = "{version}"' not in source["portfolio"]:
                errors.append(f"portfolio source does not freeze {version}")
        elif version not in source["kairos_main"] or version not in source["relay_main"]:
            errors.append(f"service sources do not agree on {version}")
    webapp = source["webapp"]
    management = webapp[webapp.find('id="cex-connect-disabled"'):webapp.find("async function loadWallets")]
    if 'id="cex-connect-disabled" disabled' not in webapp:
        errors.append("Mini App connect control is not disabled")
    for forbidden in ("connectors:connect", 'name="apiKey"', 'name="apiSecret"'):
        if forbidden in management:
            errors.append(f"Mini App exposes deferred credential ingress: {forbidden}")
    if "retention_days != 90 or max_events != 1000" not in source["relay_main"]:
        errors.append("Relay does not fail closed on retention drift")
    if "EVENT_RETENTION_DAYS = 90" not in source["store"] or "MAX_EVENTS = 1000" not in source["store"]:
        errors.append("KAIROS retention constants differ")
    if not re.search(r'@app\.get\("/api/wallet/portfolio"\)', source["relay_main"]):
        errors.append("authenticated portfolio route missing")


def _validate_keyless_state(path: Path, errors):
    if not path.exists():
        return
    data = _load(path, errors)
    items = data.get("items") if isinstance(data, dict) else None
    events = data.get("events", []) if isinstance(data, dict) else None
    if not isinstance(items, dict) or items:
        errors.append("production connector store is not keyless/empty")
    if not isinstance(events, list) or events:
        errors.append("production connector event history is not empty")
    raw = json.dumps(data, sort_keys=True)
    if any(token in raw for token in ("credentialRef", "apiKey", "apiSecret", "vault://")):
        errors.append("production connector store contains credential material")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/root"))
    parser.add_argument("--kairos-root", type=Path)
    parser.add_argument("--state", type=Path, default=Path("/var/lib/kairos/connectors.json"))
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    kairos_root = args.kairos_root or args.root / "kairos"
    contract_dir = args.root / "contracts/e1-readonly"
    errors = []
    fixtures = _validate_fixtures(contract_dir, errors)
    _validate_sources(args.root, kairos_root, fixtures, errors)
    if args.production:
        _validate_keyless_state(args.state, errors)
    if errors:
        print("E1 READ-ONLY: NO-GO")
        for error in errors:
            print(f"- {error}")
        return 1
    print("E1 READ-ONLY: GO")
    print("schemas=3 connect=disabled credentials=absent retention=90d/1000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
