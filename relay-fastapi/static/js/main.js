// ObsidianExchange — публичный JS v2

document.addEventListener('DOMContentLoaded', () => {

    // ── Navbar ──
    const burger = document.getElementById('burger');
    const navLinks = document.getElementById('nav-links');
    const navbar = document.getElementById('navbar');

    if (burger && navLinks) {
        burger.addEventListener('click', () => navLinks.classList.toggle('open'));
        navLinks.querySelectorAll('a').forEach(a =>
            a.addEventListener('click', () => navLinks.classList.remove('open'))
        );
    }

    // Подсветка активного пункта
    const path = window.location.pathname.replace(/\/+$/, '') || '/';
    // .nav-links — легаси-навбар, .navlinks — v5-навбар
    document.querySelectorAll('.nav-links a[data-path], .navlinks a[data-path]').forEach(a => {
        if (a.dataset.path === path) a.classList.add('active');
    });

    // Blur при скролле
    if (navbar) {
        window.addEventListener('scroll', () => {
            navbar.classList.toggle('scrolled', window.scrollY > 20);
        }, { passive: true });
    }

    // Инициализация функций
    fetchMarketRates();
    loadPublicStats();
    initExchangeWidget();
    initCalculator();
    initFaq();
});

// ══════════════════════════════════════
// КУРСЫ (CoinGecko)
// ══════════════════════════════════════
const RATES_CACHE_KEY = 'oe_rates_cache';
const RATES_TTL = 60 * 1000;

async function fetchMarketRates() {
    const targets = document.querySelectorAll('[data-rate]');
    if (!targets.length && !document.getElementById('widget-amount')) return;

    let data = null;
    try {
        const cached = JSON.parse(sessionStorage.getItem(RATES_CACHE_KEY) || 'null');
        if (cached && Date.now() - cached.ts < RATES_TTL) data = cached.data;
    } catch (e) {}

    if (!data) {
        try {
            // Свой /api/rates, а не CoinGecko напрямую: тот же источник, что у
            // бэкенда (курсы кешируются на сервере), плюс тарифы и список
            // открытых направлений — фронту нечего хардкодить. И никакого CORS.
            const res = await fetch('/api/rates');
            const api = await res.json();
            const rates = Object.fromEntries(Object.entries(api).filter(([code, value]) =>
                /^[A-Z0-9]{2,12}$/.test(code) && Number.isFinite(Number(value)) && Number(value) > 0
            ));
            data = {
                rates,
                _tiers: api.commission_tiers,
                _offerings: api.offerings
            };
            sessionStorage.setItem(RATES_CACHE_KEY, JSON.stringify({ data, ts: Date.now() }));
        } catch (e) {
            targets.forEach(el => { el.textContent = 'н/д'; el.classList.remove('loading'); });
            return;
        }
    }

    if (data._tiers) window.__oeTiers = data._tiers;
    if (data._offerings) window.__oeOfferings = data._offerings;

    // `rates` — текущий контракт /api/rates. Старый кэш с именами CoinGecko
    // остаётся читаемым только до его минутного TTL, чтобы не ломать открытую
    // вкладку во время релиза.
    const rates = data.rates || {
        BTC: data.bitcoin?.rub, LTC: data.litecoin?.rub,
        USDT: data.tether?.rub, ETH: data.ethereum?.rub
    };
    const map = {
        ...rates,
        bitcoin: rates.BTC,
        litecoin: rates.LTC,
        tether: rates.USDT,
        ethereum: rates.ETH
    };

    targets.forEach(el => {
        const key = el.dataset.rate;
        const val = map[key];
        if (!val) { el.textContent = 'н/д'; el.classList.remove('loading'); return; }
        el.classList.remove('loading');
        el.textContent = Math.round(val).toLocaleString('ru-RU') + ' ₽';
    });

    window.__oeRates = Object.fromEntries(Object.entries(rates).filter(([, value]) =>
        Number.isFinite(Number(value)) && Number(value) > 0
    ));
    // Направления, закрытые на бэкенде (нет ликвидности), не должны предлагаться
    document.querySelectorAll('[data-coin-card], [data-offering]').forEach(el => {
        const code = el.dataset.coinCard || el.dataset.offering;
        const open = !window.__oeOfferings ||
                     window.__oeOfferings.some(o => o.code === code);
        el.hidden = !open;
    });
    const calculator = document.getElementById('calc-currency');
    if (calculator && calculator.selectedOptions[0]?.hidden) {
        const firstOpen = [...calculator.options].find(option => !option.hidden);
        if (firstOpen) calculator.value = firstOpen.value;
    }

    // Тикер
    const tickBtc = document.getElementById('tick-btc');
    const tickLtc = document.getElementById('tick-ltc');
    const tickUsdt = document.getElementById('tick-usdt');
    if(tickBtc) tickBtc.textContent = Math.round(map.bitcoin).toLocaleString('ru-RU') + ' ₽';
    if(tickLtc) tickLtc.textContent = Math.round(map.litecoin).toLocaleString('ru-RU') + ' ₽';
    if(tickUsdt) tickUsdt.textContent = map.tether?.toFixed(1) + ' ₽';
    // Дублируем для бесконечности тикера
    const ticker = document.getElementById('ticker');
    if(ticker && !ticker.dataset.duped) { ticker.innerHTML = ticker.innerHTML + ticker.innerHTML; ticker.dataset.duped = '1'; }

    document.dispatchEvent(new CustomEvent('oe-rates-loaded'));
}

// ══════════════════════════════════════
// EXCHANGE WIDGET (главная страница)
// ══════════════════════════════════════
function initExchangeWidget() {
    const amountInput = document.getElementById('widget-amount');
    if (!amountInput) return;

    const outputEl    = document.getElementById('widget-output');
    const rateInfoEl  = document.getElementById('widget-rate-info');
    const currencyBtns = document.querySelectorAll('.currency-btn');
    let selectedCurrency = 'BTC';


    function updateWidget() {
        const amount = parseFloat(amountInput.value) || 0;
        const rates  = window.__oeRates;

        if (!amount || amount <= 0 || !rates || !rates[selectedCurrency]) {
            if (outputEl)   outputEl.textContent   = '—';
            if (rateInfoEl) rateInfoEl.textContent = '';
            return;
        }

        const rawRate    = rates[selectedCurrency];
        const commission = getCommissionPercent(amount);
        // Курс с наценкой: rawRate / (1 - commission/100)
        const rateWithMarkup = rawRate / (1 - commission / 100);
        const cryptoAmount   = amount / rateWithMarkup;

        const decimals = { USDT: 2, LTC: 4, ETH: 5, BTC: 6 }[selectedCurrency] ?? 6;
        const formatted = cryptoAmount.toFixed(decimals).replace(/0+$/, '').replace(/\.$/, '');

        if (outputEl)   outputEl.textContent   = formatted + ' ' + selectedCurrency;
        if (rateInfoEl) rateInfoEl.textContent =
            `Комиссия ${commission}% · курс ${Math.round(rateWithMarkup).toLocaleString('ru-RU')} ₽ / ${selectedCurrency}`;
    }

    currencyBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            currencyBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedCurrency = btn.dataset.currency;
            updateWidget();
        });
    });

    amountInput.addEventListener('input', updateWidget);
    document.addEventListener('oe-rates-loaded', updateWidget);

    // Предзаполнение
    amountInput.value = '10000';
    updateWidget();
}

// ══════════════════════════════════════
// КАЛЬКУЛЯТОР (страница /rates)
// ══════════════════════════════════════
// Тарифная лестница приходит с сервера (/api/rates → commission_tiers,
// единый источник core/pricing.py). Локальные значения — только аварийный
// дубль на случай, если курсы ещё не загрузились; они ОБЯЗАНЫ совпадать с
// сервером. Раньше здесь жила своя лестница с чужими границами и фиксированными
// 2% по USDT — витрина обещала одно, а списывалось другое.
const FALLBACK_TIERS = [
    { to_rub: 5000,  percent: 27 },
    { to_rub: 10000, percent: 25 },
    { to_rub: 20000, percent: 23 },
    { to_rub: null,  percent: 19 }
];

function getCommissionPercent(amount) {
    const tiers = (window.__oeTiers && window.__oeTiers.length) ? window.__oeTiers : FALLBACK_TIERS;
    for (const t of tiers) {
        if (t.to_rub === null || t.to_rub === undefined || amount < t.to_rub) return t.percent;
    }
    return tiers[tiers.length - 1].percent;
}

function initCalculator() {
    const amountEl   = document.getElementById('calc-amount');
    const currencyEl = document.getElementById('calc-currency');
    const resultEl   = document.getElementById('calc-result');
    if (!amountEl || !currencyEl || !resultEl) return;

    function render() {
        const amount   = parseFloat(amountEl.value);
        const currency = currencyEl.value;
        const big      = resultEl.querySelector('.big');
        const small    = resultEl.querySelector('.small');

        if (!amount || amount <= 0) {
            big.textContent   = '—';
            small.textContent = 'Введите сумму в RUB';
            return;
        }
        const rates = window.__oeRates;
        if (!rates || !rates[currency]) {
            big.textContent   = '—';
            small.textContent = 'Курс загружается…';
            return;
        }
        const commission     = getCommissionPercent(amount);
        const rateWithMarkup = rates[currency] / (1 - commission / 100);
        const cryptoAmount   = amount / rateWithMarkup;
        const decimals = { USDT: 2, TON: 4, LTC: 4, XRP: 6, ETH: 5, BTC: 6 }[currency] ?? 6;
        big.textContent   = `≈ ${cryptoAmount.toFixed(decimals).replace(/0+$/, '').replace(/\.$/, '')} ${currency}`;
        small.textContent = `Комиссия ${commission}% · курс ${Math.round(rateWithMarkup).toLocaleString('ru-RU')} ₽ за 1 ${currency}`;
    }

    amountEl.addEventListener('input', render);
    currencyEl.addEventListener('change', render);
    document.addEventListener('oe-rates-loaded', render);
    render();
}

// ══════════════════════════════════════
// СТАТИСТИКА
// ══════════════════════════════════════
async function loadPublicStats() {
    const el = document.getElementById('stat-exchanges-today');
    if (!el) return;
    try {
        const res  = await fetch('/api/stats/public');
        const data = await res.json();
        const val  = data.exchanges_today;
        if (val && val > 0) el.textContent = val.toLocaleString('ru-RU') + '+';
    } catch (e) {
        // оставляем дефолтное значение из HTML
    }
}

// ══════════════════════════════════════
// FAQ АККОРДЕОН
// ══════════════════════════════════════
function initFaq() {
    const items = [...document.querySelectorAll('.faq-item')];
    if (!items.length) return;

    function setOpen(activeItem) {
        items.forEach(item => {
            const question = item.querySelector('.faq-question');
            const answer = item.querySelector('.faq-answer');
            const open = item === activeItem;
            item.classList.toggle('open', open);
            question?.setAttribute('aria-expanded', String(open));
            answer?.setAttribute('aria-hidden', String(!open));
        });
    }

    items.forEach((item, index) => {
        const q = item.querySelector('.faq-question');
        const answer = item.querySelector('.faq-answer');
        if (!q) return;
        q.type = 'button';
        if (answer) {
            answer.id = answer.id || `faq-answer-${index + 1}`;
            q.setAttribute('aria-controls', answer.id);
        }
        q.addEventListener('click', () => {
            const wasOpen = item.classList.contains('open');
            setOpen(wasOpen ? null : item);
        });
    });
    setOpen(items.find(item => item.classList.contains('open')) || null);
}
