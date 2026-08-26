from pathlib import Path


WEBAPP = (Path(__file__).resolve().parents[1] / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_mobile_navigation_overrides_desktop_top_anchor_and_respects_safe_area():
    mobile = WEBAPP[WEBAPP.index("@media (max-width:620px)"):
                    WEBAPP.index("@media (max-width:420px)")]
    assert ".tabs" in mobile
    assert "top:auto" in mobile
    assert "bottom:env(safe-area-inset-bottom, 0px)" in mobile
    assert "padding-bottom:calc(82px + env(safe-area-inset-bottom, 0px))" in mobile


def test_mobile_navigation_keeps_five_primary_paths_and_hides_only_secondary_tabs():
    mobile = WEBAPP[WEBAPP.index("@media (max-width:620px)"):
                    WEBAPP.index("@media (max-width:420px)")]
    assert "grid-template-columns:repeat(5,1fr)" in mobile
    assert ".tab.secondary-tab { display:none; }" in mobile
    for tab in ("ecosystem", "exchange", "wallet", "history", "more"):
        assert f'data-tab="{tab}"' in WEBAPP
