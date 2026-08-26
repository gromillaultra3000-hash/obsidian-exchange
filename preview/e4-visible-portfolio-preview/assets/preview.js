(() => {
  'use strict';

  const lanes = document.getElementById('lanes');
  const portfolioStatus = document.getElementById('portfolio-status');
  const marketStatus = document.getElementById('market-status');
  const marketCopy = document.getElementById('market-copy');
  const marketQuotes = document.getElementById('market-quotes');

  const escape = (value) => String(value).replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));

  const render = (overview) => {
    const portfolio = overview && overview.portfolio;
    const items = portfolio && Array.isArray(portfolio.lanes) ? portfolio.lanes : [];
    if (!items.length) {
      portfolioStatus.textContent = 'Временно недоступно';
      lanes.innerHTML = '<article class="lane"><p>Структура портфеля пока недоступна.</p></article>';
      return;
    }
    portfolioStatus.textContent = portfolio.state || 'Preview';
    lanes.innerHTML = items.map((lane) => `<article class="lane">
      <span class="lane-label">${escape(lane.domain)}</span>
      <h3>${escape(lane.title)}</h3>
      <p>${escape(lane.description)}</p>
      <span class="status">${escape(lane.status)}</span>
    </article>`).join('');
    const market = overview.market || {};
    const observedAt = new Date(market.observedAt || '');
    const maxAgeMs = Number(market.maxAgeSeconds || 0) * 1000;
    const fresh = market.status === 'INDICATIVE_SNAPSHOT' && maxAgeMs > 0
      && !Number.isNaN(observedAt.valueOf()) && Date.now() - observedAt.valueOf() <= maxAgeMs;
    marketCopy.textContent = market.description || marketCopy.textContent;
    if (!fresh) {
      marketStatus.textContent = 'Цена скрыта: snapshot устарел';
      marketQuotes.innerHTML = '<span class="quote-time">Новый snapshot ещё не опубликован. Старую цену не показываем.</span>';
      return;
    }
    marketStatus.textContent = 'Индикативно · snapshot актуален';
    marketQuotes.innerHTML = (market.quotes || []).map((quote) => `<div class="quote-row">
      <strong>${escape(quote.asset)}/USDT</strong><span>${escape(Number(quote.last).toLocaleString('ru-RU'))} USDT</span>
    </div>`).join('') + `<span class="quote-time">Источник: ${escape(market.sourceLabel || '—')} · обновлено <time datetime="${escape(market.observedAt)}">${escape(observedAt.toLocaleString('ru-RU', {timeZone: 'UTC'}))} UTC</time></span>`;
  };

  fetch('/preview/api/v1/overview.json', {credentials: 'omit'})
    .then((response) => response.ok ? response.json() : Promise.reject(new Error('overview_unavailable')))
    .then(render)
    .catch(() => render(null));
})();
