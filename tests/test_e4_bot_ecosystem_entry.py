from pathlib import Path


BOT = (Path(__file__).resolve().parents[1] / "bot" / "main_bot.py").read_text(encoding="utf-8")


def test_main_bot_menu_exposes_the_canonical_ecosystem_mini_app():
    start = BOT.index("def build_main_menu_kb")
    end = BOT.index("def _fmt_rate_compact", start)
    menu = BOT[start:end]
    assert 'text="🟣 Экосистема · Mini App"' in menu
    assert 'web_app=WebAppInfo(url=f"{PUBLIC_RELAY}/webapp")' in menu
    assert 'callback_data="menu_exchange"' in menu
    assert 'callback_data="menu_orders"' in menu
