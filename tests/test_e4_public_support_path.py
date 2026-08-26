from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FAQ = (ROOT / "relay-fastapi" / "templates" / "faq.html").read_text(encoding="utf-8")
CONTACTS = (ROOT / "relay-fastapi" / "templates" / "contacts.html").read_text(encoding="utf-8")
PUBLIC_JS = (ROOT / "relay-fastapi" / "static" / "js" / "main.js").read_text(encoding="utf-8")


def test_faq_accordion_exposes_its_open_state_and_risk_context():
    assert "question?.setAttribute('aria-expanded', String(open))" in PUBLIC_JS
    assert "q.setAttribute('aria-controls', answer.id)" in PUBLIC_JS
    assert "answer?.setAttribute('aria-hidden', String(!open))" in PUBLIC_JS
    assert "криптовалютные переводы необратимы" in FAQ
    assert "сделка без риска для клиента" not in FAQ


def test_contacts_uses_the_canonical_mini_app_entry_without_removing_support():
    assert 'href="https://t.me/{{ bot_username }}?start=app"' in CONTACTS
    assert "Открыть Mini App" in CONTACTS
    assert 'href="https://t.me/{{ support_username }}"' in CONTACTS
