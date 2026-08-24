import hashlib
import json
from pathlib import Path

ROOT = Path("/root")
EVIDENCE = ROOT / "docs/e0-4-public-market-information-runtime-observation.v1.json"


def _text(path):
    return Path(path).read_text(encoding="utf-8")


def test_evidence_hashes_bind_current_deployed_sources():
    data = json.loads(EVIDENCE.read_text())
    for item in data["deployedEntrypoints"]:
        assert hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_backend_fallback_erases_provenance_and_reaches_public_api():
    calc = _text("/opt/obsidian-exchange/relay/utils/exchange_calc.py")
    main = _text("/opt/obsidian-exchange/relay-fastapi/main.py")
    assert "_FALLBACK_RATES" in calc and 'return cache["rate"] or _FALLBACK_RATES[coin]' in calc
    assert '@app.get("/api/rates")' in main and '"ts": int(time.time())' in main
    route = main[main.index('@app.get("/api/rates")'):main.index("# Монету сверх исторической тройки")]
    assert 'result = {"BTC": btc, "LTC": ltc, "USDT": usdt, "ts": int(time.time())}' in route
    for field in ('"source"', '"source_ts"', '"fallback"', '"stale"'):
        assert field not in route


def test_same_rate_helper_is_money_adjacent_not_read_only():
    bot = _text("/opt/obsidian-exchange/bot/main_bot.py")
    relay = _text("/opt/obsidian-exchange/relay-fastapi/main.py")
    assert "async def limit_order_watcher" in bot
    watcher = bot[bot.index("async def limit_order_watcher"):bot.index("async def", bot.index("async def limit_order_watcher") + 10)]
    assert "get_cached_rate(cur)" in watcher and "triggered =" in watcher
    assert "exchange_calc.get_rate_with_markup(currency, amount)" in relay
    assert "exchange_calc.get_sell_rate(currency)" in relay


def test_sources_are_sequential_without_validation_or_quorum():
    calc = _text("/opt/obsidian-exchange/relay/utils/exchange_calc.py")
    body = calc[calc.index("def get_cached_rate"):calc.index("def get_rate_with_markup")]
    assert "api.coingecko.com" in body and "api.binance.com" in body
    assert "raise_for_status" not in body and "deviation" not in body and "confidence" not in body


def test_mini_app_has_divergent_direct_and_backend_paths():
    web = _text("/opt/obsidian-exchange/relay/webapp.html")
    assert "api.coingecko.com/api/v3/simple/price" in web
    assert "api.coingecko.com/api/v3/coins/bitcoin/market_chart" in web
    assert "fetch('/api/rates')" in web
    assert 'id="btc-ch">+2.4%</div>' in web
    failure = web[web.index("async function fetchRates()"):web.index("function showRates(data)")]
    assert "btc-ch" not in failure and "ltc-ch" not in failure and "usdt-ch" not in failure


def test_commercial_export_and_manual_override_are_not_safe_authority():
    main = _text("/opt/obsidian-exchange/relay-fastapi/main.py")
    bot = _text("/opt/obsidian-exchange/bot/main_bot.py")
    assert '@app.get("/rates.xml")' in main and 'f"<maxamount>{int(MAX_AMOUNT)} RUB</maxamount>' in main
    assert '@app.get("/api/reserves")' in main and "Курируемые резервы" in main
    command = bot[bot.index('Command("setrate")'):bot.index('Command("setreserve")')]
    assert "_btc_cache" in command and "_RATE_CACHE" not in command


def test_route_inventory_and_persisted_quote_boundary_are_explicit():
    data = json.loads(EVIDENCE.read_text())
    assert {"GET /", "GET /rates", "GET /widget", "GET /rates.xml", "GET /api/reserves", "GET /api/stats/public"} <= set(data["publicRoutes"])
    assert data["authenticatedReadRoutes"] == ["GET /api/wallet/market (Telegram initData; KAIROS informational market projection)"]
    main = _text("/opt/obsidian-exchange/relay-fastapi/main.py")
    assert main.count("agreed_rate=float(rate or 0)") >= 2
    assert main.count("agreed_crypto_amount=float(crypto_amount or 0)") >= 2


def test_bot_binance_fallback_has_no_explicit_timeout():
    bot = _text("/opt/obsidian-exchange/bot/main_bot.py")
    body = bot[bot.index("def get_cached_rate(coin)"):bot.index("def get_rate_with_markup")]
    binance = [line for line in body.splitlines() if "api.binance.com" in line and "requests.get" in line]
    assert len(binance) == 2 and all("timeout=" not in line for line in binance)


def test_kairos_market_lane_is_bounded_read_only_but_not_freshness_accepted():
    main = _text("/opt/obsidian-exchange/relay-fastapi/main.py")
    gateway = _text("/opt/obsidian-exchange/relay/core/market_gateway.py")
    web = _text("/opt/obsidian-exchange/relay/webapp.html")
    route = main[main.index('@app.get("/api/wallet/market")'):main.index('@app.get("/api/wallet/history")')]
    assert "verify_init_data" in route and "public_market" in route
    assert "fetch('/api/wallet/market'" in web
    assert "loopback HTTP address" in gateway and "timeout=timeout" in gateway
    assert "raise_for_status" in gateway and '"status": "unavailable"' in gateway
    assert "isfinite" not in gateway and "max_age" not in gateway and "divergence" not in gateway


def test_public_stats_are_local_sent_state_and_frontend_fails_silent():
    main = _text("/opt/obsidian-exchange/relay-fastapi/main.py")
    store = _text("/opt/obsidian-exchange/relay/repositories/reporting_store.py")
    js = _text("/opt/obsidian-exchange/relay-fastapi/static/js/main.js")
    assert '@app.get("/api/stats/public")' in main and ".public_stats()" in main
    stats = store[store.index("def public_stats"):store.index("def reserves")]
    assert "status='sent'" in stats and "SUM(rub_amount)" in stats
    front = js[js.index("async function loadPublicStats"):js.index("// ═", js.index("async function loadPublicStats") + 10)]
    assert "оставляем дефолтное значение" in front


def test_matrix_has_advanced_beyond_public_market_information():
    matrix = json.loads((ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    ids = [item["id"] for item in matrix["features"]]
    assert len(ids) == len(set(ids)) == 25
    assert "PUBLIC_MARKET_INFORMATION" in ids
    assert "CUSTOMER_ENGAGEMENT" in ids
    assert matrix["omittedFeatureFamilies"] == []


def test_six_surface_partial_not_accepted_boundary():
    data = json.loads(EVIDENCE.read_text())
    assert data["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert set(data["surfaceMatrix"]) == {"telegramBot", "site", "miniApp", "admin", "api", "native"}
    assert data["coverageConclusion"]["readOnlyAuthorityIsolated"] is False
    assert data["coverageConclusion"]["productionPricingAccepted"] is False
    assert data["observationSafety"] == {"authenticatedCalls":False,"marketOrProviderCalls":False,"customerRowsRead":False,"secretValuesRead":False,"writersExercised":False,"deployOrRestart":False}
