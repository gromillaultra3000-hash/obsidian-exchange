(() => {
  'use strict';
  const shape = [['wallets', 'SELF_CUSTODY'], ['obsidian_exchange', 'OBSIDIAN_OPERATIONAL'], ['verified_exchanges', 'CEX_CUSTODY']];
  const labels = {SELF_CUSTODY: 'Ваши кошельки · ключи только у вас', OBSIDIAN_OPERATIONAL: 'ObsidianExchange · не ваш server-held balance', CEX_CUSTODY: 'Внешние биржи · KYC и custody у биржи'};
  const button = document.getElementById('load');
  const status = document.getElementById('status');
  const lanes = document.getElementById('lanes');
  const escape = (value) => String(value).replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  const valid = (data) => data && data.schemaVersion === 'unified-portfolio.v1'
    && Array.isArray(data.lanes) && data.lanes.length === shape.length
    && data.lanes.every((lane, index) => lane && lane.id === shape[index][0]
      && lane.custodyDomain === shape[index][1] && typeof lane.state === 'string'
      && Array.isArray(lane.sources) && lane.sources.every((source) => source
        && Array.isArray(source.balances) && source.balances.every((balance) => balance && typeof balance === 'object')));
  const showUnavailable = (text) => { status.textContent = text; lanes.innerHTML = '<article class="lane"><p>Данные не подтверждены или временно недоступны. Старые значения не показываются.</p></article>'; };
  const render = (data) => {
    status.textContent = data.complete ? 'Данные прочитаны · домены не суммируются' : 'Часть источников недоступна';
    lanes.innerHTML = data.lanes.map((lane) => {
      const stale = lane.sources.some((source) => source.balances.some((balance) =>
        ['STALE', 'UNKNOWN', 'ERROR'].includes(balance.state) || balance.total === null));
      const details = lane.sources.map((source) => {
        const balances = source.balances.map((balance) => (['STALE', 'UNKNOWN', 'ERROR'].includes(balance.state) || balance.total === null)
          ? `${escape(balance.assetId)}: недоступно`
          : `${escape(balance.assetId)}: ${escape(balance.total)}`).join('<br>');
        const activity = source.activity ? `Заявок: ${Number(source.activity.orderCount || 0)} · успешно: ${Number(source.activity.successfulOrderCount || 0)}` : '';
        return `<p>${escape(source.providerId || 'Источник')}<br>${balances || escape(activity || 'Данных нет')}</p>`;
      }).join('') || '<p>Подключённых источников нет.</p>';
      return `<article class="lane"><span class="lane-label">${escape(stale ? 'DEGRADED' : lane.state)}</span><h3>${escape(labels[lane.custodyDomain])}</h3>${details}</article>`;
    }).join('');
  };
  button.addEventListener('click', async () => {
    button.disabled = true; status.textContent = 'Запрашиваем read-only данные…';
    const tg = window.Telegram && window.Telegram.WebApp;
    const headers = tg && tg.initData ? {'X-Telegram-Init-Data': tg.initData} : {};
    try {
      const response = await fetch('/api/wallet/portfolio', {method: 'GET', headers, credentials: tg && tg.initData ? 'omit' : 'same-origin', cache: 'no-store'});
      if (response.status === 403) return showUnavailable('Войдите в кабинет и привяжите Telegram, чтобы увидеть только свои данные.');
      const data = response.ok ? await response.json() : null;
      if (!valid(data)) return showUnavailable('Портфель временно недоступен: контракт данных не подтверждён.');
      render(data);
    } catch (_) { showUnavailable('Портфель временно недоступен.'); }
    finally { button.disabled = false; }
  });
})();
