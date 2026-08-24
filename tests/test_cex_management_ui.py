import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "relay-fastapi" / "main.py").read_text(encoding="utf-8")
WEBAPP = (ROOT / "relay" / "webapp.html").read_text(encoding="utf-8")


def _function(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(item for item in ast.walk(tree)
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == name)
    return ast.get_source_segment(source, node) or ""


def test_disconnect_route_is_owner_scoped_and_explicitly_confirmed():
    body = _function(MAIN, "api_wallet_cex_disconnect")
    assert "_connector_web_user(request)" in body
    assert "principal_for_web_user(web_user['id'])" in body
    assert 'body.get("confirm") != "DISCONNECT"' in body
    assert 'scope="connectors:write"' in body
    assert 'f"/internal/v1/connectors/{source_id}"' in body
    assert "ownerRef" not in body


def test_connector_list_fails_closed_on_schema_drift():
    body = _function(MAIN, "api_wallet_cex_sources")
    assert 'result.get("schemaVersion") != "connector-list.v1"' in body
    assert "not isinstance(items, list)" in body


def test_connect_is_visibly_disabled_without_collecting_credentials():
    assert 'id="cex-connect-disabled" disabled' in WEBAPP
    assert "Новые ключи пока не принимаются" in WEBAPP
    assert "API-ключ" in WEBAPP
    management = WEBAPP[WEBAPP.index("function cexManagementRender"):
                        WEBAPP.index("async function loadWallets")]
    for forbidden in ('name="apiKey"', 'name="apiSecret"', "connectors:connect"):
        assert forbidden not in management


def test_disconnect_ui_requires_confirmation_and_refreshes_only_views():
    body = WEBAPP[WEBAPP.index("async function cexDisconnect"):
                  WEBAPP.index("async function loadWallets")]
    assert "window.confirm(" in body
    assert "JSON.stringify({confirm: 'DISCONNECT'})" in body
    assert "loadCexManagement()" in body and "loadUnifiedPortfolio()" in body
    assert "walletDisconnect(" not in body


def test_event_projection_is_sanitized_and_rendered_without_identifiers():
    body = _function(MAIN, "api_wallet_cex_events")
    assert "_connector_web_user(request)" in body
    assert '"/internal/v1/connector-events"' in body
    assert 'scope="connectors:read"' in body
    assert "retention_days != 90" in body and "max_events != 1000" in body
    renderer = WEBAPP[WEBAPP.index("function cexEventsRender"):
                      WEBAPP.index("async function loadCexEvents")]
    assert "event.providerId" in renderer and "event.type" in renderer and "event.at" in renderer
    for forbidden in ("ownerRef", "accountRef", "credentialRef", "sourceId", "vault"):
        assert forbidden not in renderer
    assert "data.retentionDays" in renderer
    assert "старые записи удаляются автоматически" in WEBAPP
