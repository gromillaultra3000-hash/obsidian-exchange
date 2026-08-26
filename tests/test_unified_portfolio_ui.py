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
    for existing in ('data-tab="exchange"', 'data-tab="wallet"', 'data-tab="market"', 'data-tab="history"'):
        assert existing in webapp


def test_mobile_navigation_keeps_secondary_sections_in_more_panel():
    assert 'data-tab="more"' in webapp
    assert 'id="panel-more"' in webapp
    assert '.tab.secondary-tab' in webapp
    for target in ('market', 'referral', 'profile', 'faq'):
        assert f"switchTab('{target}')" in webapp


def test_ecosystem_overview_uses_the_existing_read_only_portfolio_contract():
    assert 'id="ecosystem-portfolio"' in webapp
    assert 'function ecosystemPortfolioRender' in webapp
    assert 'ecosystemPortfolioRender(data)' in webapp
    assert "tab.dataset.tab === 'ecosystem'" in webapp


def test_activity_navigation_preserves_existing_history_handler():
    assert 'data-tab="history"' in webapp
    assert '>Активность<' in webapp
    assert "tab.dataset.tab === 'history') loadHistory()" in webapp
