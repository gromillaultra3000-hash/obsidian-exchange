import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/e0-4-account-auth-profile-runtime-observation.v1.json"


def test_hash_bound_deployed_auth_sources():
    evidence = json.loads(EVIDENCE.read_text())
    for item in evidence["deployedEntrypoints"]:
        deployed = Path(item["path"])
        assert hashlib.sha256(deployed.read_bytes()).hexdigest() == item["sha256"]


def test_positive_password_cookie_csrf_and_edge_throttle_controls_are_present():
    auth = Path("/opt/obsidian-exchange/relay-fastapi/auth.py").read_text()
    main = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    nginx = Path("/etc/nginx/sites-available/obsidian-exchange.org").read_text()
    assert "bcrypt.hashpw" in auth and "bcrypt.checkpw" in auth
    for marker in ("httponly=True", "secure=True", "samesite='lax'"):
        assert marker in auth
    assert "secrets.compare_digest" in auth
    for route in ("/dashboard/profile/2fa/enable", "/dashboard/profile/2fa/disable", "/dashboard/profile/password"):
        start = main.index(route)
        assert "verify_csrf" in main[start:start + 1800]
    assert "location = /login" in nginx and "limit_req zone=login" in nginx
    assert "location = /register" in nginx and "limit_req zone=register" in nginx
    for path in ("/dashboard/profile/password", "/dashboard/profile/2fa/disable", "/auth/telegram/callback"):
        assert f"location = {path}" not in nginx
    freshness = Path("/opt/obsidian-exchange/relay/core/telegram_freshness.py").read_text()
    assert "age >= -future_skew" in freshness


def test_telegram_binding_is_state_changing_get_without_csrf_or_step_up():
    main = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    start = main.index('@app.get("/auth/telegram/callback")')
    body = main[start:main.index("# --- \u041b\u0438\u0447\u043d\u044b\u0439 \u043a\u0430\u0431\u0438\u043d\u0435\u0442: \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430", start)]
    assert "auth.link_telegram" in body
    assert "verify_csrf" not in body
    assert "verify_password" not in body and "verify_totp_code" not in body
    assert "nonce" not in body and "state" not in body


def test_password_and_totp_changes_do_not_revoke_existing_sessions():
    main = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    section = main[main.index('@app.post("/dashboard/profile/2fa/enable")'):main.index('@app.get("/auth/telegram/callback")')]
    assert "set_password_hash" in section and "enable_totp" in section and "disable_totp" in section
    assert "destroy_session" not in section
    assert "revoke" not in section


def test_plaintext_session_totp_and_replayable_step_shape_are_explicit():
    schema = (ROOT / "deploy/postgres/002_web_auth.sql").read_text()
    auth = Path("/opt/obsidian-exchange/relay-fastapi/auth.py").read_text()
    assert "token TEXT PRIMARY KEY" in schema
    assert "csrf_token TEXT NOT NULL" in schema
    assert "totp_secret TEXT" in schema
    step = auth[auth.index("def make_totp_step_token"):auth.index("def verify_telegram_login_widget")]
    assert "hexdigest()[:16]" in step
    assert "time.time() - int(ts) > 300" in step
    assert "nonce" not in step and "consume" not in step
    widget = auth[auth.index("def verify_telegram_login_widget"):]
    assert "time.time() - auth_date > 86400" in widget
    assert "future_skew" not in widget


def test_six_surfaces_unaccepted_and_next_family():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert set(evidence["surfaceMatrix"]) == {"telegramBot", "site", "miniApp", "admin", "api", "native"}
    assert evidence["coverageConclusion"]["productionAcceptanceProven"] is False
    assert evidence["nextCanonicalItem"].startswith("Classify PAYMENT_PROVIDER_LIFECYCLE")
