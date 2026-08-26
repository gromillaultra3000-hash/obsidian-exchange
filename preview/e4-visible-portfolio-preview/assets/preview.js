(() => {
  'use strict';

  const lanes = document.getElementById('lanes');
  const portfolioStatus = document.getElementById('portfolio-status');
  const marketStatus = document.getElementById('market-status');
  const marketCopy = document.getElementById('market-copy');

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
    marketStatus.textContent = market.status || 'Не подключено';
    marketCopy.textContent = market.description || marketCopy.textContent;
  };

  fetch('/preview/api/v1/overview.json', {credentials: 'omit'})
    .then((response) => response.ok ? response.json() : Promise.reject(new Error('overview_unavailable')))
    .then(render)
    .catch(() => render(null));
})();
