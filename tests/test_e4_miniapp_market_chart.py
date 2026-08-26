from pathlib import Path


WEBAPP = (Path(__file__).resolve().parents[1] / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_market_chart_has_read_only_context_and_derived_24_hour_change():
    for marker in ("РЫНОК · НАБЛЮДЕНИЕ", "Историческая динамика, не курс заявки", "id=\"chart-change\"", "id=\"chart-updated\""):
        assert marker in WEBAPP
    assert "const change = ((last - first) / first) * 100;" in WEBAPP
    assert "const maxPoints = 48;" in WEBAPP
    assert "История рынка временно недоступна" in WEBAPP


def test_market_chart_uses_compact_mobile_chart_options():
    for marker in ("height:158px", "maxTicksLimit: 3", "pointHoverRadius: 4", "displayColors: false"):
        assert marker in WEBAPP
