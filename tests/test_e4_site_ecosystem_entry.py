from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "relay-fastapi" / "templates" / "index.html").read_text(encoding="utf-8")
WEBAPP = (ROOT / "relay" / "webapp.html").read_text(encoding="utf-8")
RELAY = (ROOT / "relay-fastapi" / "main.py").read_text(encoding="utf-8")


def test_public_site_links_to_preview_and_a_concrete_mini_app_entry_without_replacing_exchange():
    assert 'href="/preview/">Экосистема · preview</a>' in INDEX
    assert 'href="https://t.me/{{ bot_username }}?start=app" target="_blank" rel="noopener"' in INDEX
    assert 'Открыть Mini App в Telegram</a>' in INDEX
    assert 'Создать заявку' in INDEX
    assert 'href="/rates"' in INDEX
    assert 'else %}https://t.me/{{ bot_username }}?start=app{% endif %}' in INDEX
    assert 'Открыть Mini App для обмена →' in INDEX
    assert 'href="https://t.me/{{ bot_username }}" class="btn" style="width:100%"' not in INDEX


def test_public_site_widget_uses_the_same_open_offerings_as_rates_and_mini_app():
    for currency in ("BTC", "LTC", "USDT", "XRP", "TON"):
        assert f"'{currency}' in offered_currencies" in INDEX
        assert f'data-currency="{currency}"' in INDEX
        assert f'data-coin-card="{currency}"' in INDEX


def test_mini_app_uses_the_configured_bot_username_for_telegram_handoffs():
    assert "const ecosystemBotUsername = '__OBSIDIAN_BOT_USERNAME__';" in WEBAPP
    for payload in ('swap', 'tools', 'referral', 'profile'):
        assert f'${{ecosystemBotUsername}}?start={payload}' in WEBAPP
    assert "def _mini_app_bot_username()" in RELAY
    assert "re.fullmatch(r'[A-Za-z0-9_]{5,32}', candidate)" in RELAY
    assert "replace('__OBSIDIAN_BOT_USERNAME__', _mini_app_bot_username())" in RELAY
