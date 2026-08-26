(() => {
  'use strict';

  const lanes = document.getElementById('lanes');
  const portfolioStatus = document.getElementById('portfolio-status');
  const marketStatus = document.getElementById('market-status');
  const marketCopy = document.getElementById('market-copy');
  const marketQuotes = document.getElementById('market-quotes');
  let marketExpiryTimer = null;

  const escape = (value) => String(value).replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));

  const marketUnavailable = (message) => {
    marketStatus.textContent = message;
    marketQuotes.innerHTML = '<span class="quote-time">Старые или непроверенные цены не показываются.</span>';
  };

  const renderMarket = (market) => {
    if (marketExpiryTimer) window.clearTimeout(marketExpiryTimer);
    const observedAt = new Date(market && market.observedAt || '');
    const maxAgeMs = Number(market && market.maxAgeSeconds || 0) * 1000;
    const ageMs = Date.now() - observedAt.valueOf();
    const validQuotes = Array.isArray(market && market.quotes) ? market.quotes.filter((quote) => (
      ['BTC', 'ETH', 'LTC'].includes(quote.asset) && Number.isFinite(Number(quote.last)) && Number(quote.last) > 0
    )) : [];
    if (!market || market.status !== 'INDICATIVE_SNAPSHOT' || maxAgeMs <= 0
        || Number.isNaN(observedAt.valueOf()) || ageMs < 0 || ageMs > maxAgeMs || !validQuotes.length) {
      marketUnavailable('Цена скрыта: snapshot устарел или недоступен');
      return;
    }
    marketCopy.textContent = market.description || marketCopy.textContent;
    marketStatus.textContent = 'Индикативно · snapshot актуален';
    marketQuotes.innerHTML = validQuotes.map((quote) => `<div class="quote-row">
      <strong>${escape(quote.asset)}/USDT</strong><span>${escape(Number(quote.last).toLocaleString('ru-RU'))} USDT</span>
    </div>`).join('') + `<span class="quote-time">Источник: ${escape(market.sourceLabel || '—')} · обновлено <time datetime="${escape(market.observedAt)}">${escape(observedAt.toLocaleString('ru-RU', {timeZone: 'UTC'}))} UTC</time></span>`;
    marketExpiryTimer = window.setTimeout(() => renderMarket(market), maxAgeMs - ageMs + 1);
  };

  const render = (overview) => {
    const portfolio = overview && overview.portfolio;
    const items = portfolio && Array.isArray(portfolio.lanes) ? portfolio.lanes : [];
    if (!items.length) {
      portfolioStatus.textContent = 'Временно недоступно';
      lanes.innerHTML = '<article class="lane"><p>Структура портфеля пока недоступна.</p></article>';
    } else {
      portfolioStatus.textContent = portfolio.state || 'Preview';
      lanes.innerHTML = items.map((lane) => `<article class="lane">
        <span class="lane-label">${escape(lane.domain)}</span>
        <h3>${escape(lane.title)}</h3>
        <p>${escape(lane.description)}</p>
        <span class="status">${escape(lane.status)}</span>
      </article>`).join('');
    }
    renderMarket(overview && overview.market);
  };

  fetch('/preview/api/v1/overview.json', {credentials: 'omit'})
    .then((response) => response.ok ? response.json() : Promise.reject(new Error('overview_unavailable')))
    .then(render)
    .catch(() => renderMarket(null));
})();
