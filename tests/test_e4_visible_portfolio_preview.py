import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "preview" / "e4-visible-portfolio-preview"
INDEX = (PREVIEW / "index.html").read_text(encoding="utf-8")
SCRIPT = (PREVIEW / "assets" / "preview.js").read_text(encoding="utf-8")
OVERVIEW = json.loads((PREVIEW / "api" / "v1" / "overview.json").read_text(encoding="utf-8"))
NGINX = (ROOT / "deploy" / "nginx" / "obsidian-exchange.org").read_text(encoding="utf-8")
BOT = (ROOT / "bot" / "main_bot.py").read_text(encoding="utf-8")
RELEASE = (ROOT / "deploy" / "e4_visible_portfolio_preview_release.sh").read_text(encoding="utf-8")
ROLLBACK = (ROOT / "deploy" / "e4_visible_portfolio_preview_rollback.sh").read_text(encoding="utf-8")
CAPTURE = (ROOT / "deploy" / "e4_visible_portfolio_preview_capture_preimage.sh").read_text(encoding="utf-8")
PORTFOLIO = (PREVIEW / "portfolio" / "portfolio.js").read_text(encoding="utf-8")


def test_preview_contract_is_explicitly_non_executable():
    assert OVERVIEW["schemaVersion"] == "e4-visible-portfolio-preview.v1"
    assert OVERVIEW["mode"] == "PREVIEW"
    for key in ("executable", "quote", "orderCreation", "custodyAction"):
        assert OVERVIEW[key] is False
    assert [item["domain"] for item in OVERVIEW["portfolio"]["lanes"]] == [
        "SELF_CUSTODY", "OBSIDIAN_OPERATIONAL", "CEX_CUSTODY"]
    market = OVERVIEW["market"]
    assert market["status"] == "INDICATIVE_SNAPSHOT"
    assert market["snapshotId"].startswith("kairos-okx-")
    assert market["maxAgeSeconds"] > 0
    assert {quote["asset"] for quote in market["quotes"]} == {"BTC", "ETH", "LTC"}


def test_preview_has_no_writer_or_identity_surface():
    combined = INDEX + SCRIPT + json.dumps(OVERVIEW, ensure_ascii=False)
    for forbidden in (
        "/api/create_order", "/pay/", "/swap/", "/wallet/", "/sell/", "/admin/",
        "sendData", "localStorage", "TON_CONNECT", "initData", "providerUrl",
    ):
        assert forbidden not in combined
    assert "credentials: 'omit'" in SCRIPT
    assert "snapshot устарел" in SCRIPT
    assert "market.observedAt" in SCRIPT
    assert "ageMs < 0" in SCRIPT
    assert "window.setTimeout" in SCRIPT
    assert "renderMarket(null)" in SCRIPT
    assert "<form" not in INDEX


def test_preview_is_isolated_static_nginx_location_and_bot_entrypoint():
    assert "location = /preview" in NGINX
    assert "location ^~ /preview/" in NGINX
    assert "alias /opt/obsidian-exchange/releases/e4-visible-portfolio-preview/current/;" in NGINX
    assert "return 405;" in NGINX
    exact_location = re.search(r"location = /preview \{(?P<body>.*?)\n    \}", NGINX, re.S)
    assert exact_location is not None
    assert "$request_method !~ ^(GET|HEAD)$" in exact_location.group("body")
    location = re.search(r"location \^~ /preview/ \{(?P<body>.*?)\n    \}", NGINX, re.S)
    assert location is not None
    assert "proxy_pass" not in location.group("body")
    assert 'Command("preview")' in BOT
    assert 'f"{PUBLIC_RELAY}/preview/"' in BOT
    assert 'f"{PUBLIC_RELAY}/preview/portfolio/"' in BOT


def test_preview_rollout_preserves_a_deterministic_rollback_path():
    assert 'previous="$release_base/previous"' in RELEASE
    assert 'previous_preview_release=' in RELEASE
    assert 'nginx.conf.preimage' in ROLLBACK
    assert 'bot.main_bot.py.preimage' in ROLLBACK
    assert 'systemctl reload nginx' in ROLLBACK
    assert 'systemctl restart exchange-bot.service' in ROLLBACK
    assert 'nginx.conf.preimage' in CAPTURE
    assert 'bot.main_bot.py.preimage' in CAPTURE
    assert 'previous-preview-release' in CAPTURE


def test_account_portfolio_requires_explicit_owner_scoped_read_only_request():
    assert 'href="/preview/portfolio/"' in INDEX
    assert "addEventListener('click'" in PORTFOLIO
    assert "'/api/wallet/portfolio'" in PORTFOLIO
    assert "cache: 'no-store'" in PORTFOLIO
    assert "X-Telegram-Init-Data" in PORTFOLIO
    assert "unified-portfolio.v1" in PORTFOLIO
    assert "lane.id === shape[index][0]" in PORTFOLIO
    assert "stale ? 'DEGRADED'" in PORTFOLIO
    assert "credentials: tg && tg.initData ? 'omit' : 'same-origin'" in PORTFOLIO
    for forbidden in ("localStorage", "sendData", "/api/create_order", "/pay/", "/sell/", "/admin/"):
        assert forbidden not in PORTFOLIO
