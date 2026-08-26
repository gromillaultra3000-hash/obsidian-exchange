from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "relay-fastapi" / "templates" / "index.html").read_text(encoding="utf-8")


def test_public_site_links_to_the_isolated_ecosystem_preview_without_replacing_exchange():
    assert 'href="/preview/">Экосистема · preview</a>' in INDEX
    assert 'href="https://t.me/{{ bot_username }}" target="_blank" rel="noopener"' in INDEX
    assert 'Открыть в Telegram</a>' in INDEX
    assert 'Создать заявку' in INDEX
    assert 'href="/rates"' in INDEX
