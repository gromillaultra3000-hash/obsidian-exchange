"""Regression checks for the P0 authorization and webhook fixes."""
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]


spec = importlib.util.spec_from_file_location("oe_auth", ROOT / "relay-fastapi/auth.py")
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)

assert not auth.is_web_admin(None, {123})
assert not auth.is_web_admin({"email": "admin@example.com", "telegram_id": None}, {123})
assert not auth.is_web_admin({"email": "notadmin@example.com", "telegram_id": 456}, {123})
assert auth.is_web_admin({"email": "user@example.com", "telegram_id": "123"}, {123})

spec = importlib.util.spec_from_file_location("trocador", ROOT / "relay/providers/trocador.py")
trocador = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trocador)

assert trocador.verified_trocador_status({"Status": "finished"}) == "finished"
assert trocador.verified_trocador_status({"status": " WAITING "}) == "waiting"
assert trocador.verified_trocador_status({"Status": "attacker-controlled"}) is None
assert trocador.verified_trocador_status({"error": "network"}) is None
assert trocador.verified_trocador_status({}) is None
assert trocador.safe_trocador_transition("waiting", "finished") == "finished"
assert trocador.safe_trocador_transition("confirming", "sending") == "sending"
assert trocador.safe_trocador_transition("sending", "sending") == "sending"
assert trocador.safe_trocador_transition("sending", "waiting") is None
assert trocador.safe_trocador_transition("confirming", "new") is None
assert trocador.safe_trocador_transition("finished", "waiting") is None
assert trocador.safe_trocador_transition("refunded", "finished") is None

main_source = (ROOT / "relay-fastapi/main.py").read_text()
assert '"admin" not in email' not in main_source
assert "await asyncio.to_thread(TrocadorProvider().get_status" in main_source
assert 'data.get(\'status\') or data.get(\'Status\')' not in main_source
assert 'audit_log("swap_page_opened", f"token={token}' not in main_source
assert 'audit_log("web_swap_created", f"token={token}' not in main_source
assert 'audit_log("payment_page_opened", f"token={token}' not in main_source
swap_page_source = main_source.split("async def swap_page", 1)[1].split(
    "async def trocador_webhook", 1
)[0]
assert "verified_trocador_status(info)" in swap_page_source
assert "safe_trocador_transition(status, new_status)" in swap_page_source
server_stats_source = main_source.split("async def api_server_stats", 1)[1].split(
    "# ---", 1
)[0]
assert "require_admin(request)" in server_stats_source
assert 'host=os.getenv("RELAY_BIND_HOST", "127.0.0.1")' in main_source
assert 'uvicorn.run(app, host="0.0.0.0"' not in main_source
assert 'fake_tx = f"manual_' not in main_source
workflow_source = (ROOT / "relay/repositories/order_workflow_store.py").read_text()
assert '_order_workflow.mark_sent(order_id, data.get("txid"))' in main_source
assert "normalize_txid(txid, row[0])" in workflow_source
assert "status='paid' AND (paid_btc_tx IS NULL OR paid_btc_tx='')" in workflow_source
assert '/dashboard/profile/2fa/qr.png' not in main_source
assert 'qr_data_uri = "data:image/png;base64,"' in main_source
totp_page_source = main_source.split("async def dashboard_2fa_page", 1)[1].split(
    '@app.post("/dashboard/profile/2fa/enable")', 1
)[0]
assert 'response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"' in totp_page_source
assert 'response.headers["Referrer-Policy"] = "no-referrer"' in totp_page_source

totp_template = (ROOT / "relay-fastapi/templates/dashboard_2fa.html").read_text()
assert "qr.png?secret=" not in totp_template
assert 'src="{{ qr_data_uri }}"' in totp_template

bot_source = (ROOT / "bot/main_bot.py").read_text()
force_source = bot_source.split("async def cmd_force_payout", 1)[1].split(
    "async def _payout_preflight", 1
)[0]
assert 'status != "paid"' in force_source
assert "normalize_txid(txid, currency)" in force_source
assert '_order_workflow.mark_sent(oid, txid)' in force_source
assert 'transition["action"] != "transitioned"' in force_source
worker_source = bot_source.split("async def worker_enter_tx", 1)[1].split(
    "# ═", 1
)[0]
assert "normalize_txid(tx, currency)" in worker_source
assert "status IN ('paid','pending')" not in worker_source
assert '_order_workflow.mark_sent(order_id, tx)' in worker_source
assert 'transition["action"] != "transitioned"' in worker_source

user_source = (ROOT / "admin-panel/app/Models/User.php").read_text()
assert "return true;" not in user_source
assert "return $this->is_admin === true;" in user_source
assert "'is_admin'," not in user_source.split("protected $fillable", 1)[1].split("];", 1)[0]
assert "'totp_secret'," not in user_source.split("protected $fillable", 1)[1].split("];", 1)[0]

laravel_login = (ROOT / "admin-panel/app/Filament/Pages/Auth/Login.php").read_text()
assert "verifyKey(" in laravel_login
assert "session()->regenerate();" in laravel_login
assert "PENDING_TTL_SECONDS = 300" in laravel_login
assert "canAccessPanel(Filament::getCurrentPanel())" in laravel_login
assert "verifyKeyNewer(" in laravel_login
assert "claimTotpTimestamp" in laravel_login
assert "orWhere('totp_last_used_timestamp', '<', $timestamp)" in laravel_login
laravel_mfa_middleware = (ROOT / "admin-panel/app/Http/Middleware/RequireAdminMfa.php").read_text()
assert "Filament::auth()->logout();" in laravel_mfa_middleware
assert "$request->session()->invalidate();" in laravel_mfa_middleware
laravel_audit = (ROOT / "admin-panel/app/Support/AdminAudit.php").read_text()
assert "SENSITIVE_FIELDS" in laravel_audit
assert "getChanges()" in laravel_audit
assert "getAttributes())" in laravel_audit
assert "request()->all" not in laravel_audit

print("Security P0 regression checks passed.")
