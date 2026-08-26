from pathlib import Path


WEBAPP = (Path(__file__).resolve().parents[1] / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_mini_app_ticker_uses_the_shared_public_rates_contract():
    assert "fetch('/api/rates', { cache: 'no-store' })" in WEBAPP
    assert "simple/price?ids=bitcoin,litecoin,tether" not in WEBAPP
    assert "!Number.isFinite(value) || value <= 0" in WEBAPP
    assert "label.textContent = 'котировка';" in WEBAPP
    assert "label.textContent = 'недоступно';" in WEBAPP


def test_mini_app_does_not_render_a_fabricated_day_change_before_rates_arrive():
    for stale_change in ("+2.4%", "+1.1%", "−0.1%"):
        assert stale_change not in WEBAPP
    assert WEBAPP.count('class="rate-change neutral"') >= 3
