from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "relay-fastapi" / "templates" / "base.html").read_text(encoding="utf-8")
CSS = (ROOT / "relay-fastapi" / "static" / "css" / "v5.css").read_text(encoding="utf-8")


def test_public_v5_navigation_has_a_concrete_mini_app_handoff():
    assert 'class="nav-actions"' in BASE
    assert 'href="https://t.me/{{ bot_username }}?start=app">Mini App</a>' in BASE
    assert 'class="nav-toggle"' in BASE


def test_mobile_v5_navigation_can_fit_without_hiding_the_mini_app_entry():
    mobile = CSS[CSS.index("@media(max-width:680px)"):CSS.index("/* ── util", CSS.index("@media(max-width:680px)"))]
    for rule in (
        ".nav{gap:8px;padding:10px 12px;align-items:center}",
        ".brand{min-width:0;gap:8px}",
        ".caption{display:none}",
        ".nav-actions .btn{padding:10px 9px;font-size:10px}",
        ".nav-actions .btn.ghost{display:none}",
    ):
        assert rule in mobile
    assert 'class="nav-mobile-login" href="/login">Войти</a>' in BASE
    assert ".nav-mobile-login{display:none}" in CSS
    assert ".navlinks.open .nav-mobile-login{display:block}" in CSS
