from pathlib import Path


WEBAPP = (Path(__file__).resolve().parents[1] / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_market_chart_has_read_only_context_and_derived_24_hour_change():
    for marker in ("РЫНОК · НАБЛЮДЕНИЕ", "Историческая динамика, не курс заявки", "id=\"chart-change\"", "id=\"chart-updated\"", "id=\"chart-last\"", "id=\"chart-refresh\"", "id=\"marketChart\""):
        assert marker in WEBAPP
    assert "fetch(`/api/market/history?asset=${encodeURIComponent(requestedAsset)}`, { cache: 'no-store' })" in WEBAPP
    assert "market_chart?vs_currency=rub" not in WEBAPP
    assert "const change = ((last - first) / first) * 100;" in WEBAPP
    assert "const maxPoints = 48;" in WEBAPP
    assert "История рынка временно недоступна" in WEBAPP


def test_market_chart_uses_compact_mobile_chart_options():
    for marker in ("height:158px", "maxTicksLimit: 3", "pointHoverRadius: 4", "displayColors: false"):
        assert marker in WEBAPP


def test_market_chart_can_be_manually_refreshed_without_a_money_action():
    assert "async function loadChart(manual = false)" in WEBAPP
    assert "manual ? 'Обновляем историю рынка…'" in WEBAPP
    assert "if (marketChart) marketChart.destroy();" in WEBAPP
    assert "document.getElementById('chart-refresh').addEventListener('click', () => loadChart(true));" in WEBAPP


def test_market_chart_has_accessible_asset_switching_and_ticker_handoffs():
    for asset in ("BTC", "ETH", "LTC"):
        assert f'data-chart-asset="{asset}"' in WEBAPP
    assert "function selectChartAsset(asset)" in WEBAPP
    assert "role=\"button\"" in WEBAPP
    assert "aria-controls=\"marketChart\"" in WEBAPP
    assert "marketAssets =" in WEBAPP


def test_market_chart_persists_only_the_selected_public_asset_for_the_session():
    assert "const chartAssetStorageKey = 'oe.market-history.asset.v1';" in WEBAPP
    assert "sessionStorage.getItem(chartAssetStorageKey)" in WEBAPP
    assert "function rememberChartAsset(asset)" in WEBAPP
    assert "Закрытие: ${last.toLocaleString('ru-RU'" in WEBAPP
