from pathlib import Path


WEBAPP = (Path(__file__).resolve().parents[1] / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_mobile_secondary_panel_keeps_a_visible_more_context_and_return_control():
    assert 'id="mobile-secondary-back"' in WEBAPP
    assert '.mobile-secondary-back:not([hidden]) { display:block; }' in WEBAPP
    assert "const mobileSecondary = tab.classList.contains('secondary-tab') && tab.offsetParent === null;" in WEBAPP
    assert "moreTab.classList.add('context-active');" in WEBAPP
    assert "moreTab.setAttribute('aria-current', 'page');" in WEBAPP
    assert "mobileSecondaryBack?.addEventListener('click', () => switchTab('more'));" in WEBAPP
