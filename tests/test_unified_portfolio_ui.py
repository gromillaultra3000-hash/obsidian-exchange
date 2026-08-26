from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
webapp = (ROOT / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_three_custody_lanes_have_explicit_honest_copy():
    assert "fetch('/api/wallet/portfolio'" in webapp
    assert "SELF_CUSTODY" in webapp and "Ключи только у вас" in webapp
    assert "OBSIDIAN_OPERATIONAL" in webapp and "Без хранения средств" in webapp
    assert "CEX_CUSTODY" in webapp and "KYC и custody у биржи" in webapp
    assert "Часть данных устарела" in webapp
    assert "Временно недоступно" in webapp
    assert "Итог неполный" in webapp


def test_renderer_does_not_coerce_missing_balance_to_zero():
    start = webapp.index("function unifiedPortfolioRender")
    end = webapp.index("async function loadUnifiedPortfolio", start)
    renderer = webapp[start:end]
    assert "balance.total === null" in renderer
    assert "'недоступно'" in renderer
    assert "balance.total || 0" not in renderer
    assert "parseFloat(balance.total)" not in renderer


def test_existing_wallet_actions_remain_wired():
    for marker in ("on('w-act-send'", "on('w-act-recv'", "on('w-act-buy'", "portfolioRender(d && d.portfolio)"):
        assert marker in webapp


def test_ecosystem_overview_is_the_default_without_removing_legacy_flows():
    assert 'data-tab="ecosystem"' in webapp
    assert 'id="panel-ecosystem"' in webapp
    assert 'switchTab(\'wallet\')' in webapp
    assert 'switchTab(\'exchange\')' in webapp
    assert 'switchTab(\'market\')' in webapp
    assert 'id="ecosystem-exchange-status"' in webapp
    assert 'function renderEcosystemExchangeStatus' in webapp
    assert "renderEcosystemExchangeStatus(d)" in webapp
    for existing in ('data-tab="exchange"', 'data-tab="wallet"', 'data-tab="market"', 'data-tab="history"'):
        assert existing in webapp
    assert "КОШЕЛЁК · PRIVATE EXCHANGE · CEX READ-ONLY" in webapp


def test_mobile_navigation_keeps_secondary_sections_in_more_panel():
    assert 'data-tab="more"' in webapp
    assert 'id="panel-more"' in webapp
    assert '.tab.secondary-tab' in webapp
    for target in ('market', 'referral', 'profile', 'faq'):
        assert f"switchTab('{target}')" in webapp


def test_more_panel_reaches_the_existing_telegram_swap_flow():
    assert 'onclick="openBotSwap()"' in webapp
    assert 'function openBotSwap()' in webapp
    assert 'https://t.me/Obsidian666999bot?start=swap' in webapp
    assert "tg.openTelegramLink(url)" in webapp


def test_more_panel_reaches_existing_optional_exchange_tools():
    assert 'onclick="openBotTools()"' in webapp
    assert 'function openBotTools()' in webapp
    assert 'https://t.me/Obsidian666999bot?start=tools' in webapp
    assert 'Лимит · DCA · фиксация курса · подарки' in webapp


def test_market_quotes_have_freshness_guard_and_manual_refresh():
    assert 'id="market-refresh"' in webapp
    assert 'id="market-quote-status"' in webapp
    assert 'function validMarketSnapshot' in webapp
    assert 'marketSnapshotMaxAgeMs' in webapp
    assert "ageMs < 0 || ageMs > marketSnapshotMaxAgeMs" in webapp
    assert "Старые значения не показываются" in webapp
    assert "on('market-refresh', loadMarketQuotes)" in webapp
    assert "fetch('/api/wallet/market', {cache: 'no-store'" in webapp


def test_ecosystem_overview_uses_the_existing_read_only_portfolio_contract():
    assert 'id="ecosystem-portfolio"' in webapp
    assert 'function ecosystemPortfolioRender' in webapp
    assert 'ecosystemPortfolioRender(data)' in webapp
    assert "tab.dataset.tab === 'ecosystem'" in webapp
    assert "function isUnifiedPortfolioV1" in webapp
    assert "schemaVersion === 'unified-portfolio.v1'" in webapp
    assert "cache: 'no-store'" in webapp
    assert "Старые значения не показываются" in webapp
    assert "stale ? 'DEGRADED'" in webapp
    assert "source && Array.isArray(source.balances)" in webapp


def test_activity_navigation_preserves_existing_history_handler():
    assert 'data-tab="history"' in webapp
    assert '>Активность<' in webapp
    assert "tab.dataset.tab === 'history') loadHistory()" in webapp
    assert 'id="history-refresh"' in webapp
    assert 'data-history-filter="pending"' in webapp
    assert 'function setHistoryFilter' in webapp
    assert "cache: 'no-store'" in webapp
    assert "Операции кошелька остаются в разделе «Кошелёк»" in webapp
    assert 'id="activity-support"' in webapp
    assert 'function openSupport' in webapp
    assert "https://t.me/ObsidianSupBot" in webapp
    assert "Данные из приложения не отправляются автоматически" in webapp


def test_mini_app_tabs_are_keyboard_and_screen_reader_accessible():
    assert 'role="tablist" aria-label="Разделы"' in webapp
    for name in ('ecosystem', 'exchange', 'wallet', 'history', 'market', 'referral', 'profile', 'faq', 'more'):
        assert f'id="tab-{name}"' in webapp
        assert f'aria-controls="panel-{name}"' in webapp
        assert f'id="panel-{name}" role="tabpanel"' in webapp
    assert 'tabindex="-1"' in webapp
    assert 'font-family:inherit; -webkit-appearance:none; appearance:none;' in webapp
    assert "const visibleAppTabs" in webapp
    for key in ('ArrowLeft', 'ArrowRight', 'Home', 'End'):
        assert key in webapp
    assert "visibleTabs[next].focus()" in webapp


def test_exchange_shows_private_and_cex_custody_context_before_form():
    assert 'aria-label="Маршрут обмена"' in webapp
    assert "💎 Private lane" in webapp
    assert "ObsidianExchange · без KYC" in webapp
    assert "📈 CEX / KYC lane" in webapp
    assert "switchTab('market')" in webapp
    assert "Сейчас только котировки и портфель" in webapp
    assert "торговое подключение в этом приложении пока недоступно" in webapp


def test_overview_has_an_owner_scoped_read_only_activity_entrypoint():
    assert 'id="ecosystem-activity"' in webapp
    assert 'id="ecosystem-activity-status" role="status"' in webapp
    assert "function loadEcosystemActivity" in webapp
    assert "function renderEcosystemActivity" in webapp
    assert "Статусы заявок временно недоступны" in webapp
    assert "cache: 'no-store'" in webapp
    assert "loadUnifiedPortfolio(); loadEcosystemActivity();" in webapp
    assert "renderEcosystemActivity(orders);" in webapp
    assert "loadSysStatus();\n        loadUnifiedPortfolio();\n        loadEcosystemActivity();" in webapp


def test_activity_makes_the_existing_order_number_ready_for_support_copying():
    assert 'class="history-copy-id"' in webapp
    assert 'data-order-id="${esc(orderId)}"' in webapp
    assert "function copyOrderId" in webapp
    assert "navigator.clipboard" in webapp
    assert "document.execCommand('copy')" in webapp
    assert "copyOrderId(button.dataset.orderId, button)" in webapp
    assert "Копировать №" in webapp


def test_narrow_mobile_layout_keeps_overview_and_review_actions_readable():
    assert 'class="ecosystem-lanes"' in webapp
    assert '.ecosystem-lanes { grid-template-columns:1fr; }' in webapp
    assert 'class="exchange-review-surface"' in webapp
    assert 'class="exchange-review-actions"' in webapp
    assert '.exchange-review-actions { grid-template-columns:1fr !important; }' in webapp
