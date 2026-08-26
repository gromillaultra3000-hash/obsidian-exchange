from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RATES = (ROOT / "relay-fastapi" / "templates" / "rates.html").read_text(encoding="utf-8")
PUBLIC_JS = (ROOT / "relay-fastapi" / "static" / "js" / "main.js").read_text(encoding="utf-8")


def test_rates_surface_uses_the_shared_open_offerings_in_cards_and_calculator():
    assert '{% for currency in offered_currencies %}' in RATES
    assert 'data-offering="{{ currency }}"' in RATES
    assert 'data-rate="{{ currency }}"' in RATES
    assert '<option value="{{ currency }}" data-offering="{{ currency }}">' in RATES
    assert "Object.fromEntries(Object.entries(api).filter" in PUBLIC_JS
    assert "window.__oeRates = Object.fromEntries" in PUBLIC_JS


def test_rates_action_uses_the_canonical_mini_app_entry():
    assert 'href="https://t.me/{{ bot_username }}?start=app"' in RATES
    assert "Открыть Mini App и создать заявку" in RATES
    assert 'href="https://t.me/{{ bot_username }}" class="btn btn-primary btn-block">Создать заявку' not in RATES
