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
    document.querySelectorAll('.nav-links a[data-path]').forEach(a => {
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
            const res = await fetch(
                'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,litecoin,tether&vs_currencies=rub'
            );
            data = await res.json();
            sessionStorage.setItem(RATES_CACHE_KEY, JSON.stringify({ data, ts: Date.now() }));
        } catch (e) {
            targets.forEach(el => { el.textContent = 'н/д'; el.classList.remove('loading'); });
            return;
        }
    }

    const map = {
        bitcoin: data.bitcoin?.rub,
        litecoin: data.litecoin?.rub,
        tether: data.tether?.rub
    };

    targets.forEach(el => {
        const key = el.dataset.rate;
        const val = map[key];
        if (!val) { el.textContent = 'н/д'; el.classList.remove('loading'); return; }
        el.classList.remove('loading');
        el.textContent = Math.round(val).toLocaleString('ru-RU') + ' ₽';
    });

    window.__oeRates = {
        BTC: map.bitcoin,
        LTC: map.litecoin,
        USDT: map.tether
    };

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

    // Комиссия по тирам (из бота)
    function getWidgetCommission(amount, currency) {
        if (currency === 'USDT') return 2;
        if (amount < 10000)  return 27;
        if (amount < 30000)  return 25;
        if (amount < 100000) return 23;
        return 19;
    }

    function updateWidget() {
        const amount = parseFloat(amountInput.value) || 0;
        const rates  = window.__oeRates;

        if (!amount || amount <= 0 || !rates || !rates[selectedCurrency]) {
            if (outputEl)   outputEl.textContent   = '—';
            if (rateInfoEl) rateInfoEl.textContent = '';
            return;
        }

        const rawRate    = rates[selectedCurrency];
        const commission = getWidgetCommission(amount, selectedCurrency);
        // Курс с наценкой: rawRate / (1 - commission/100)
        const rateWithMarkup = rawRate / (1 - commission / 100);
        const cryptoAmount   = amount / rateWithMarkup;

        const decimals = selectedCurrency === 'USDT' ? 2 : (selectedCurrency === 'LTC' ? 4 : 6);
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
function getCommissionPercent(amount, currency) {
    if (currency === 'USDT') return 2;
    if (amount < 10000)  return 27;
    if (amount < 30000)  return 25;
    if (amount < 100000) return 23;
    return 19;
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
        const commission     = getCommissionPercent(amount, currency);
        const rateWithMarkup = rates[currency] / (1 - commission / 100);
        const cryptoAmount   = amount / rateWithMarkup;
        big.textContent   = `≈ ${cryptoAmount.toFixed(8).replace(/0+$/, '').replace(/\.$/, '')} ${currency}`;
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
    document.querySelectorAll('.faq-item').forEach(item => {
        const q = item.querySelector('.faq-question');
        if (!q) return;
        q.addEventListener('click', () => {
            const wasOpen = item.classList.contains('open');
            item.parentElement.querySelectorAll('.faq-item').forEach(i => i.classList.remove('open'));
            if (!wasOpen) item.classList.add('open');
        });
    });
}
