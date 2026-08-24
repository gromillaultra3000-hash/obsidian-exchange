import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_operator_workflows_have_exact_six_surface_inventory():
    matrix = json.loads((ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    item = next(feature for feature in matrix["features"] if feature["id"] == "OPERATOR_WORKFLOWS")
    assert list(item["cells"]) == matrix["surfaces"]
    assert item["overallStatus"] == "PARTIAL_NOT_ACCEPTED"
    assert item["moneyWriter"] is True and item["privilegedControlPlane"] is True
    assert all(item["cells"][name]["mode"] == "OPERATOR_ONLY"
               for name in ("telegramBot", "miniApp", "admin", "api"))
    assert all(item["cells"][name]["implementation"] == "PARTIAL"
               for name in ("telegramBot", "miniApp", "admin", "api"))
    assert item["cells"]["site"]["mode"] == item["cells"]["native"]["mode"] == "N/A"
    assert "operator workflows" not in matrix["omittedFeatureFamilies"]
    assert "LUMI advisory" not in matrix["omittedFeatureFamilies"]


def test_operator_runtime_hashes_auth_fences_and_review_corrections_are_bound():
    evidence = json.loads((ROOT / "docs/e0-4-operator-workflows-runtime-observation.v1.json").read_text())
    for field in ("productionMutation", "operatorAuthenticationUsed", "operatorWriterExercised",
                  "customerDataObserved", "secretValueObserved"):
        assert evidence[field] is False
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert evidence["runtime"]["admin"]["user"] == "root"
    assert evidence["runtime"]["telegramBot"]["user"] == "root"
    assert evidence["runtime"]["relay"]["user"] == "relay-svc"
    assert evidence["runtime"]["kairos"]["user"] == "kairos-svc"

    pairs = {
        "filamentLogin": ("admin-panel/app/Filament/Pages/Auth/Login.php", "/opt/obsidian-exchange/admin-panel/app/Filament/Pages/Auth/Login.php"),
        "filamentMfaMiddleware": ("admin-panel/app/Http/Middleware/RequireAdminMfa.php", "/opt/obsidian-exchange/admin-panel/app/Http/Middleware/RequireAdminMfa.php"),
        "filamentPanel": ("admin-panel/app/Providers/Filament/AdminPanelProvider.php", "/opt/obsidian-exchange/admin-panel/app/Providers/Filament/AdminPanelProvider.php"),
        "orderResource": ("admin-panel/app/Filament/Resources/OrderResource.php", "/opt/obsidian-exchange/admin-panel/app/Filament/Resources/OrderResource.php"),
        "adminAudit": ("admin-panel/app/Support/AdminAudit.php", "/opt/obsidian-exchange/admin-panel/app/Support/AdminAudit.php"),
        "adminAuditMigration": ("admin-panel/database/migrations/2026_08_08_000003_create_admin_action_audits_table.php", "/opt/obsidian-exchange/admin-panel/database/migrations/2026_08_08_000003_create_admin_action_audits_table.php"),
        "miniApp": ("relay/webapp.html", "/opt/obsidian-exchange/relay/webapp.html"),
        "kairosMain": ("kairos/app/main_v19.py", "/opt/kairos/app/main_v19.py"),
        "kairosFrontend": ("kairos/app/static_frontend/index.html", "/opt/kairos/app/static_frontend/index.html"),
    }
    for name, (checkout, deployed) in pairs.items():
        digest = hashlib.sha256((ROOT / checkout).read_bytes()).hexdigest()
        assert digest == evidence["artifacts"][name]["sha256"]
        assert hashlib.sha256(Path(deployed).read_bytes()).hexdigest() == digest

    deployed_relay = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    deployed_webapp = Path("/opt/obsidian-exchange/relay/webapp.html").read_text()
    assert '@app.post("/internal/admin/force_payout")' in deployed_relay
    for route in ("/api/admin/stats", "/api/admin/block", "/api/admin/force_payout"):
        assert route in deployed_relay and route in deployed_webapp
    reviews = {row["reviewer"]: row for row in evidence["independentReviews"]}
    assert "routes are absent" in reviews["agent:/root/operator_surface_audit"]["rejected"]
    assert "all services run as root" in reviews["agent:/root/operator_security_audit"]["rejected"]
    assert any("four-eyes" in finding for finding in evidence["riskFindings"])
    assert any("same Telegram conversation" in finding for finding in evidence["riskFindings"])
