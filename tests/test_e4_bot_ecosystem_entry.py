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


def test_swap_deep_link_reuses_the_existing_bot_pair_selector():
    start = BOT.index('async def cmd_start')
    end = BOT.index('# ---------- ОБРАБОТЧИКИ МЕНЮ ----------', start)
    command = BOT[start:end]
    assert 'start_payload == "swap"' in command
    assert 'await send_swap_menu(message)' in command
    assert 'def build_swap_pairs_kb()' in BOT
    assert 'async def send_swap_menu(message: Message)' in BOT
    handler_start = BOT.index('async def menu_swap')
    handler = BOT[handler_start:BOT.index('@router.callback_query(F.data.startswith("swap_pair_"))', handler_start)]
    assert 'await send_swap_menu(callback.message)' in handler


def test_tools_deep_link_reuses_the_existing_optional_tools_menu():
    start = BOT.index('async def cmd_start')
    end = BOT.index('# ---------- ОБРАБОТЧИКИ МЕНЮ ----------', start)
    command = BOT[start:end]
    assert 'start_payload == "tools"' in command
    assert 'await send_tools_menu(message)' in command
    assert 'async def send_tools_menu(message: Message)' in BOT
    assert 'reply_markup=build_tools_kb()' in BOT


def test_referral_deep_link_reuses_the_existing_referral_menu():
    start = BOT.index('async def cmd_start')
    end = BOT.index('# ---------- ОБРАБОТЧИКИ МЕНЮ ----------', start)
    command = BOT[start:end]
    assert 'start_payload == "referral"' in command
    assert 'await send_referral_menu(message, message.from_user.id)' in command
    assert 'async def send_referral_menu(message: Message, user_id: int)' in BOT
    menu_start = BOT.index('async def menu_ref')
    menu = BOT[menu_start:BOT.index('@router.callback_query(F.data == "rate_sub_toggle")', menu_start)]
    assert 'await send_referral_menu(callback.message, callback.from_user.id)' in menu


def test_profile_deep_link_reuses_existing_bot_profile_settings():
    start = BOT.index('async def cmd_start')
    end = BOT.index('# ---------- ОБРАБОТЧИКИ МЕНЮ ----------', start)
    command = BOT[start:end]
    assert 'start_payload == "profile"' in command
    assert 'await profile(message, uid=message.from_user.id)' in command


def test_site_mini_app_deep_link_renders_only_the_existing_canonical_webapp_button():
    start = BOT.index('async def cmd_start')
    end = BOT.index('# ---------- ОБРАБОТЧИКИ МЕНЮ ----------', start)
    command = BOT[start:end]
    assert 'start_payload == "app"' in command
    assert 'reply_markup=build_mini_app_entry_kb()' in command
    assert 'def build_mini_app_entry_kb()' in BOT
    entry_start = BOT.index('def build_mini_app_entry_kb()')
    entry = BOT[entry_start:BOT.index('def _fmt_rate_compact', entry_start)]
    assert 'web_app=WebAppInfo(url=f"{PUBLIC_RELAY}/webapp")' in entry
    assert 'не создаёт' in entry


def test_bot_market_entry_is_read_only_and_reuses_the_existing_mini_app():
    assert 'def build_market_entry_kb()' in BOT
    assert 'web_app=WebAppInfo(url=f"{PUBLIC_RELAY}/webapp?market=BTC")' in BOT
    assert '@router.message(Command("market"))' in BOT
    assert 'Это не курс заявки и не запускает обмен или торговлю.' in BOT
    command = BOT[BOT.index('async def cmd_start'):BOT.index('# ---------- ОБРАБОТЧИКИ МЕНЮ ----------')]
    assert 'start_payload == "market"' in command
    assert 'await cmd_market(message)' in command
