from pathlib import Path


HOW_IT_WORKS = (Path(__file__).resolve().parents[1] / "relay-fastapi" / "templates" / "how_it_works.html").read_text(encoding="utf-8")


def test_public_first_step_uses_the_canonical_telegram_mini_app_handoff():
    app_link = 'https://t.me/{{ bot_username }}?start=app'
    assert HOW_IT_WORKS.count(app_link) >= 2
    assert "Откройте Mini App в Telegram" in HOW_IT_WORKS
    assert "🟣 Открыть Mini App" in HOW_IT_WORKS
    assert 'href="/webapp"' not in HOW_IT_WORKS


def test_public_onramp_does_not_replace_specialized_sell_or_swap_flows():
    assert "💰 Продать крипту" in HOW_IT_WORKS
    assert "🔄 Начать своп" in HOW_IT_WORKS
