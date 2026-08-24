import ast
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/e0_4_build_owner_auth_candidate.py"


def test_candidate_build_is_exact_bounded_and_excludes_notification_writer(tmp_path):
    out = tmp_path / "candidate"
    result = subprocess.run([
        sys.executable, str(BUILDER),
        "--relay-base", "/opt/obsidian-exchange/relay-fastapi/main.py",
        "--relay-source", str(ROOT / "relay-fastapi/main.py"),
        "--bot-base", "/opt/obsidian-exchange/bot/main_bot.py",
        "--bot-source", str(ROOT / "bot/main_bot.py"),
        "--output-dir", str(out),
    ], check=True, text=True, capture_output=True)
    evidence = json.loads(result.stdout)
    assert evidence["productionMutation"] is False
    artifacts = {item["component"]: item for item in evidence["artifacts"]}
    assert artifacts["relay"]["candidateSha256"] == "cdd840fe11ff1726d0aa20e7a5fd9016867821f82d8eca9c1de42bd02daa04f3"
    assert artifacts["bot"]["candidateSha256"] == "ec7f39fa93a744aa88910b5c0373cdeabec4ff4486c73e5cd16a255455f54c78"
    assert artifacts["order_read_store"]["candidateSha256"] == "54b73860ad154c9e86c4c00092779037fc0bba2edba230f5cbb6d8c29cd50c21"
    assert artifacts["payment_session_store"]["candidateSha256"] == "94836d4549d5255acea6d878b51de6e7fba150a47b126c892f4fe4e6942f6409"
    assert artifacts["receipt_store"]["candidateSha256"] == "fe6703df36f739cdcbd01e37d04eea28c7149186bd2e5fd1133e18ea31a8b960"
    assert artifacts["engagement_store"]["candidateSha256"] == "0668f07dfad22612a1add32a01c051762a0ab1f670e74d43317d35f66edc9057"
    relay = (out / "relay-fastapi/main.py").read_text()
    bot = (out / "bot/main_bot.py").read_text()
    ast.parse(relay)
    ast.parse(bot)
    assert "authorized_snapshot" in relay
    assert "latest_active_for_authorized_order" in relay
    assert "order_access.verify" in relay
    assert "finalize_review(order_id, callback.from_user.id)" in bot
    assert 'params={"key": RELAY_SECRET,' in bot
    assert "order_access.issue(order_id, message.from_user.id)" in bot
    assert "_render_hardened_notification" not in bot
    assert "_notification_receipt_sha256" not in bot
    assert "ThreadPoolExecutor" not in relay
    assert "OBSIDIAN_SKIP_DOTENV" not in relay
    assert (out / "relay/core/order_access.py").exists()
    for name in ("order_read_store.py", "payment_session_store.py", "receipt_store.py",
                 "engagement_store.py"):
        ast.parse((out / "relay/repositories" / name).read_text())


def test_candidate_builder_rejects_unreviewed_input_digest(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("# drift\n" + (ROOT / "bot/main_bot.py").read_text())
    result = subprocess.run([
        sys.executable, str(BUILDER),
        "--relay-base", "/opt/obsidian-exchange/relay-fastapi/main.py",
        "--relay-source", str(ROOT / "relay-fastapi/main.py"),
        "--bot-base", "/opt/obsidian-exchange/bot/main_bot.py",
        "--bot-source", str(bad),
        "--output-dir", str(tmp_path / "candidate"),
    ], text=True, capture_output=True)
    assert result.returncode != 0
    assert "checkout source digest mismatch" in result.stderr
