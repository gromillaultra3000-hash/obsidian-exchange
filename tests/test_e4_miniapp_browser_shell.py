from pathlib import Path


WEBAPP = (Path(__file__).resolve().parents[1] / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_mini_app_shell_has_an_embedded_favicon_and_the_compact_primary_tabs():
    assert '<link rel="icon" href="data:image/svg+xml,' in WEBAPP
    for tab in ("ecosystem", "exchange", "wallet", "history", "more"):
        assert f'id="tab-{tab}"' in WEBAPP
        assert f'id="panel-{tab}"' in WEBAPP
