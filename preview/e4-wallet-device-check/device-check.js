'use strict';
const deviceBuild = {"id":"9376b40b5e9edb3700593d12e8b6459b467510dbe401eae9877a33e8fefda3f1","sourceSHA256":"ee01d3f55a2f97c3f957e9166a02f79cd247f7d924316c666d6d94a754bfe7e3","generatorSHA256":"a1cb253be7b39958deb86212c8e7ff60698c47154898f0a8fe31fd10efb5d8a8"};

const deviceCounters = {reviewRequests: 0, sdkCalls: 0, resolved: 0, rejected: 0};
let devicePending = null;
let deviceOutcome = 'not-started';
const deviceAddress = '0:' + 'b'.repeat(64);
const tcUI = {account: {address: deviceAddress, chain: '-239'}, sendTransaction(request) {
    deviceCounters.sdkCalls++;
    deviceOutcome = 'synthetic-pending';
    deviceUpdate();
    return new Promise((resolve, reject) => { devicePending = {resolve, reject}; deviceUpdate(); });
}};

// BEGIN EXTRACTED PRODUCTION
        function esc(s) {
            return String(s == null ? '' : s).replace(/[&<>"']/g,
                c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
                        '"': '&quot;', "'": '&#39;' }[c]));
        }
        const walletAttemptStorageKey = 'oe.device-check.wallet-attempt.v1';
        const walletAttemptSharedKey = 'oe.device-check.wallet-attempt.shared.v1';
        const walletAttemptLockName = 'oe.device-check.wallet-handoff.v1';
        let walletAttempt = null;
        let walletAttemptStorageFault = false;
        let walletAttemptBusy = false;
        let walletAttemptObservedRaw;
        function validWalletAttempt(value) {
            return value && ((value.version === 1 && Object.keys(value).sort().join(',') === 'network,operation,orderId,version,wallet')
                || (value.version === 2 && Object.keys(value).sort().join(',') === 'attemptId,network,operation,orderId,version,wallet'
                    && typeof value.attemptId === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value.attemptId)))
                && typeof value.wallet === 'string' && /^(-1|0):[0-9a-f]{64}$/.test(value.wallet)
                && ['-239', '-3'].includes(value.network)
                && ((value.operation === 'transfer' && value.orderId === null)
                    || (value.operation === 'payment' && Number.isSafeInteger(value.orderId) && value.orderId > 0));
        }
        function walletAttemptCapabilities() {
            return typeof navigator !== 'undefined' && navigator.locks && typeof navigator.locks.request === 'function'
                && typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function';
        }
        function parseWalletAttempt(raw, version) {
            try {
                const value = typeof raw === 'string' && raw.length <= 512 ? JSON.parse(raw) : null;
                return validWalletAttempt(value) && value.version === version ? value : {invalid: true};
            } catch (_) { return {invalid: true}; }
        }
        function readWalletAttempt() {
            try {
                const legacy = sessionStorage.getItem(walletAttemptStorageKey);
                const shared = localStorage.getItem(walletAttemptSharedKey);
                const raw = JSON.stringify([legacy, shared]);
                if (raw !== walletAttemptObservedRaw) {
                    const ack = document.getElementById('wallet-attempt-ack');
                    if (ack) ack.checked = false;
                    walletAttemptObservedRaw = raw;
                }
                // Keep a local reminder even if another context removes storage.
                if (legacy !== null || shared !== null) {
                    const older = legacy !== null ? parseWalletAttempt(legacy, 1) : null;
                    const current = shared !== null ? parseWalletAttempt(shared, 2) : null;
                    walletAttempt = current || older;
                    if (older && current && (older.invalid || current.invalid
                        || ['wallet', 'network', 'operation', 'orderId'].some(field => older[field] !== current[field]))) walletAttempt = {invalid: true};
                }
                walletAttemptStorageFault = !walletAttemptCapabilities();
            } catch (_) { walletAttemptStorageFault = true; }
        }
        function renderWalletAttempt() {
            const notice = document.getElementById('wallet-attempt-notice');
            const details = document.getElementById('wallet-attempt-details');
            const ack = document.getElementById('wallet-attempt-ack');
            const remove = document.getElementById('wallet-attempt-remove');
            if (!notice || !details || !ack || !remove) return;
            notice.style.display = walletAttempt || walletAttemptStorageFault ? '' : 'none';
            details.textContent = walletAttemptStorageFault
                ? 'Хранилище или безопасная координация вкладок недоступны. Новый перевод заблокирован. Используйте поддерживаемый браузер, восстановите доступ к хранилищу и проверьте предыдущие операции.'
                : walletAttempt && !walletAttempt.invalid
                    ? 'Кошелёк: ' + walletAttempt.wallet + ' · сеть TON ' + (walletAttempt.network === '-239' ? 'mainnet' : 'testnet')
                        + ' · ' + (walletAttempt.operation === 'payment' ? 'Оплата заявки #' + walletAttempt.orderId : 'Прямой перевод') + '. Исход требует проверки.'
                    : 'Данные предыдущих попыток повреждены или различаются. Проверьте историю всех использованных кошельков и статусы заявок перед удалением напоминания.';
            if (walletAttemptBusy) details.textContent += ' В другой вкладке ещё выполняется запрос кошелька. Напоминание не удалено.';
            remove.disabled = !walletAttempt || walletAttemptStorageFault || walletHandoffPending || !ack.checked;
            ack.disabled = walletHandoffPending || walletAttemptStorageFault;
        }
        function walletAttemptBlocked(say) {
            readWalletAttempt();
            renderWalletAttempt();
            if (!walletAttempt && !walletAttemptStorageFault) return false;
            say('Новый перевод заблокирован: проверьте предыдущую попытку в напоминании ниже. Пока результат неясен, не повторяйте перевод.');
            return true;
        }
        function walletAttemptAddress(address, network) {
            if (typeof address !== 'string') return null;
            if (/^(-1|0):[0-9a-fA-F]{64}$/.test(address)) return address.toLowerCase();
            if (!/^[A-Za-z0-9_+/-]{48}$/.test(address)) return null;
            try {
                const bytes = Array.from(atob(address.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
                if (bytes.length !== 36 || ![0x11, 0x51].includes(bytes[0] & 0x7f)
                    || ((bytes[0] & 0x80) !== 0 && network !== '-3') || ![0, 255].includes(bytes[1])) return null;
                let crc = 0;
                for (const byte of bytes.slice(0, 34)) {
                    crc ^= byte << 8;
                    for (let bit = 0; bit < 8; bit++) crc = ((crc << 1) ^ ((crc & 0x8000) ? 0x1021 : 0)) & 0xffff;
                }
                if (crc !== (bytes[34] << 8 | bytes[35])) return null;
                return (bytes[1] === 255 ? '-1' : '0') + ':' + bytes.slice(2, 34).map(byte => byte.toString(16).padStart(2, '0')).join('');
            } catch (_) { return null; }
        }
        function walletAttemptBinding(data, operation, orderId) {
            const account = tcUI && tcUI.account;
            if (operation === 'payment' && (!Number.isSafeInteger(data.sell_id) || data.sell_id !== orderId)) return null;
            const value = {version: 1, wallet: walletAttemptAddress(data.from_address, data.request.network), network: data.request.network,
                operation: operation, orderId: orderId};
            if (!validWalletAttempt(value) || !account || typeof account.address !== 'string'
                || account.address.toLowerCase() !== value.wallet || account.chain !== value.network) return null;
            return value;
        }
        function beginWalletAttempt(data, operation, orderId, say) {
            if (walletAttemptBlocked(say)) return false;
            const value = walletAttemptBinding(data, operation, orderId);
            if (!value) { say('Кошелёк или сеть изменились либо недоступны. Подключите нужный кошелёк и заново проверьте перевод.'); return false; }
            // Persist and read back before invoking the external signing boundary.
            walletAttempt = {...value, version: 2, attemptId: crypto.randomUUID()};
            try {
                const encoded = JSON.stringify(walletAttempt);
                localStorage.setItem(walletAttemptSharedKey, encoded);
                if (localStorage.getItem(walletAttemptSharedKey) !== encoded) throw new Error('storage');
                walletAttemptObservedRaw = JSON.stringify([sessionStorage.getItem(walletAttemptStorageKey), encoded]);
            } catch (_) {
                walletAttemptStorageFault = true;
                say('Не удалось сохранить напоминание. Запрос в кошелёк не отправлен. Новый перевод заблокирован до проверки хранилища.');
                renderWalletAttempt();
                return false;
            }
            document.getElementById('wallet-attempt-ack').checked = false;
            renderWalletAttempt();
            return true;
        }
        async function runWalletHandoff(data, operation, orderId, say, grant) {
            if (!grant || !Number.isFinite(grant.expiresAt) || grant.generation !== exchangeReviewPreparationGeneration || Date.now() >= grant.expiresAt
                || walletHandoffPending || walletAttemptBlocked(say)) return false;
            let entered = false;
            walletAttemptBusy = false;
            walletHandoffPending = true;
            renderWalletAttempt();
            try {
                return await navigator.locks.request(walletAttemptLockName, {mode: 'exclusive', ifAvailable: true}, async lock => {
                    if (!lock) { walletAttemptBusy = true; say('Другой запрос кошелька ещё выполняется. Проверьте его результат; повтор автоматически не выполняется.'); return false; }
                    if (grant.generation !== exchangeReviewPreparationGeneration || Date.now() >= grant.expiresAt) {
                        say('Проверка условий устарела. Откройте её заново.'); return false;
                    }
                    if (!beginWalletAttempt(data, operation, orderId, say)) return false;
                    entered = true;
                    await tcUI.sendTransaction(data.request);
                    return true;
                });
            } catch (error) {
                if (entered) throw error;
                walletAttemptStorageFault = true;
                say('Безопасная координация вкладок недоступна. Запрос в кошелёк не отправлен.');
                return false;
            } finally {
                walletHandoffPending = false;
                renderWalletAttempt();
            }
        }
        async function migrateWalletAttempt() {
            // Legacy evidence is never removed or overwritten by migration.
            try {
                const legacy = sessionStorage.getItem(walletAttemptStorageKey);
                if (legacy === null || !walletAttemptCapabilities()) return;
                await navigator.locks.request(walletAttemptLockName, {mode: 'exclusive', ifAvailable: true}, lock => {
                    if (!lock || localStorage.getItem(walletAttemptSharedKey) !== null) return;
                    const latest = sessionStorage.getItem(walletAttemptStorageKey);
                    if (latest === null) return;
                    const older = parseWalletAttempt(latest, 1);
                    const encoded = JSON.stringify(older.invalid ? {invalid: true} : {...older, version: 2, attemptId: crypto.randomUUID()});
                    localStorage.setItem(walletAttemptSharedKey, encoded);
                    if (localStorage.getItem(walletAttemptSharedKey) !== encoded) throw new Error('storage');
                });
                readWalletAttempt();
            } catch (_) { walletAttemptStorageFault = true; }
            renderWalletAttempt();
        }

        let exchangeReviewCommit = null;
        // Pending wallet responses belong to one review attempt only.
        let exchangeReviewPreparationGeneration = 0;
        let walletHandoffPending = false;
        let exchangeReviewRestoreFocus = null;
        let exchangeReviewExpiresAt = 0;
        let exchangeReviewExpiryTimer = null;
        const exchangeReviewAckWindowMs = 2 * 60 * 1000;
        function exchangeReviewFocusable(modal) {
            return Array.from(modal.querySelectorAll('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href]'))
                .filter(element => element.offsetParent !== null);
        }
        function clearExchangeReviewExpiry() {
            if (exchangeReviewExpiryTimer) clearTimeout(exchangeReviewExpiryTimer);
            exchangeReviewExpiryTimer = null;
            exchangeReviewExpiresAt = 0;
        }
        function updateExchangeReviewConfirm() {
            const modal = document.getElementById('exchange-review');
            const ack = document.getElementById('exchange-review-ack');
            const confirm = document.getElementById('exchange-review-confirm');
            const fresh = exchangeReviewCommit && Date.now() < exchangeReviewExpiresAt;
            if (confirm) confirm.disabled = !ack || !ack.checked || !fresh
                || !modal || modal.style.display !== 'flex';
        }
        function invalidateExchangeReview() {
            exchangeReviewPreparationGeneration++;
            const ack = document.getElementById('exchange-review-ack');
            const freshness = document.getElementById('exchange-review-freshness');
            clearExchangeReviewExpiry();
            exchangeReviewCommit = null;
            if (ack) ack.checked = false;
            if (freshness) freshness.textContent = 'Время проверки истекло. Вернитесь к форме и откройте условия заново.';
            updateExchangeReviewConfirm();
        }
        function closeExchangeReview() {
            exchangeReviewPreparationGeneration++;
            const modal = document.getElementById('exchange-review');
            if (modal) modal.style.display = 'none';
            clearExchangeReviewExpiry();
            exchangeReviewCommit = null;
            const restore = exchangeReviewRestoreFocus;
            exchangeReviewRestoreFocus = null;
            if (restore && document.contains(restore) && !restore.disabled) restore.focus();
        }
        function openExchangeReview({title, description = 'Заявка ещё не создана. Ничего не списывается до следующего подтверждения.', confirmLabel = 'Подтвердить и создать', rows, risk, onConfirm}) {
            exchangeReviewPreparationGeneration++;
            const modal = document.getElementById('exchange-review');
            const heading = document.getElementById('exchange-review-title');
            const descriptionBox = document.getElementById('exchange-review-description');
            const summary = document.getElementById('exchange-review-summary');
            const riskBox = document.getElementById('exchange-review-risk');
            const ack = document.getElementById('exchange-review-ack');
            const confirm = document.getElementById('exchange-review-confirm');
            const freshness = document.getElementById('exchange-review-freshness');
            if (!modal || !heading || !descriptionBox || !summary || !riskBox || !ack || !confirm || !freshness) return;
            heading.textContent = title;
            descriptionBox.textContent = description;
            confirm.textContent = confirmLabel;
            summary.innerHTML = rows.map(row => '<div class="device-style-18">'
                + '<div class="device-style-19">' + esc(row.label) + '</div>'
                + '<div class="device-style-20">' + esc(row.value) + '</div></div>').join('');
            riskBox.textContent = '⚠ ' + risk;
            ack.checked = false;
            exchangeReviewCommit = onConfirm;
            clearExchangeReviewExpiry();
            exchangeReviewExpiresAt = Date.now() + exchangeReviewAckWindowMs;
            freshness.textContent = 'Подтверждение доступно 2 минуты. Если время истечёт, откройте проверку заново.';
            exchangeReviewExpiryTimer = setTimeout(() => {
                if (modal.style.display === 'flex' && Date.now() >= exchangeReviewExpiresAt) {
                    invalidateExchangeReview();
                }
            }, exchangeReviewAckWindowMs + 50);
            exchangeReviewRestoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            modal.style.display = 'flex';
            updateExchangeReviewConfirm();
            // Start with the conditions, including when reopening a scrolled
            // review. Focusing the checkbox skips these on a small screen.
            const surface = modal.querySelector('.exchange-review-surface');
            if (surface) surface.scrollTop = 0;
            heading.focus({preventScroll: true});
        }


        (function wireExchangeReview() {
            const modal = document.getElementById('exchange-review');
            const ack = document.getElementById('exchange-review-ack');
            const cancel = document.getElementById('exchange-review-cancel');
            const confirm = document.getElementById('exchange-review-confirm');
            if (!modal || !ack || !cancel || !confirm) return;
            ack.addEventListener('change', updateExchangeReviewConfirm);
            cancel.addEventListener('click', closeExchangeReview);
            confirm.addEventListener('click', async () => {
                if (!ack.checked || !exchangeReviewCommit || Date.now() >= exchangeReviewExpiresAt) {
                    if (Date.now() >= exchangeReviewExpiresAt) invalidateExchangeReview();
                    return;
                }
                const commit = exchangeReviewCommit;
                const expiresAt = exchangeReviewExpiresAt;
                closeExchangeReview();
                await commit({generation: exchangeReviewPreparationGeneration, expiresAt: expiresAt});
            });
            document.addEventListener('keydown', event => {
                if (event.key === 'Escape' && modal.style.display === 'flex') closeExchangeReview();
            });
            modal.addEventListener('keydown', event => {
                if (event.key !== 'Tab' || modal.style.display !== 'flex') return;
                const focusable = exchangeReviewFocusable(modal);
                if (!focusable.length) { event.preventDefault(); modal.focus(); return; }
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                if (!focusable.includes(document.activeElement)) {
                    event.preventDefault();
                    (event.shiftKey ? last : first).focus();
                } else if (event.shiftKey && document.activeElement === first) {
                    event.preventDefault(); last.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                    event.preventDefault(); first.focus();
                }
            });
        })();
        (function wireWalletAttemptNotice() {
            const ack = document.getElementById('wallet-attempt-ack');
            const remove = document.getElementById('wallet-attempt-remove');
            if (!ack || !remove) return;
            readWalletAttempt();
            ack.checked = false;
            renderWalletAttempt();
            ack.addEventListener('change', renderWalletAttempt);
            remove.addEventListener('click', async () => {
                if (walletHandoffPending || !ack.checked || !walletAttemptCapabilities()) return;
                const acknowledged = walletAttemptObservedRaw;
                walletAttemptBusy = false;
                try {
                    await navigator.locks.request(walletAttemptLockName, {mode: 'exclusive', ifAvailable: true}, lock => {
                        if (!lock) { walletAttemptBusy = true; ack.checked = false; return; }
                        readWalletAttempt();
                        if (walletHandoffPending || !walletAttempt || walletAttemptStorageFault || !ack.checked
                            || acknowledged !== walletAttemptObservedRaw) return;
                        // Delete only the exact evidence the user saw, under the same
                        // exclusion as publication and the entire SDK promise.
                        sessionStorage.removeItem(walletAttemptStorageKey);
                        if (sessionStorage.getItem(walletAttemptStorageKey) !== null) throw new Error('storage');
                        localStorage.removeItem(walletAttemptSharedKey);
                        if (localStorage.getItem(walletAttemptSharedKey) !== null) throw new Error('storage');
                        walletAttempt = null;
                        walletAttemptObservedRaw = JSON.stringify([null, null]);
                        ack.checked = false;
                        closeExchangeReview();
                    });
                } catch (_) { walletAttemptStorageFault = true; }
                renderWalletAttempt();
            });
            window.addEventListener('storage', event => {
                if (event.key === walletAttemptSharedKey || event.key === null) { readWalletAttempt(); renderWalletAttempt(); }
            });
            migrateWalletAttempt();
        })();
// END EXTRACTED PRODUCTION

function deviceReport() {
    let storageReadable = false;
    try { localStorage.getItem(walletAttemptSharedKey); sessionStorage.getItem(walletAttemptStorageKey); storageReadable = true; } catch (_) {}
    return {
        schemaVersion: 1, diagnostic: 'inert-wallet-device-check', build: deviceBuild,
        environment: {userChoice: document.getElementById('device-environment').value, verified: false},
        capabilities: {secureContext: isSecureContext, webLocks: !!(navigator.locks && navigator.locks.request),
            randomUUID: !!(globalThis.crypto && crypto.randomUUID), storageReadable,
            clipboard: !!(navigator.clipboard && navigator.clipboard.writeText)},
        counters: {...deviceCounters}, counterScope: 'current-document-only',
        pending: walletHandoffPending, attemptPresent: !!walletAttempt,
        storageOrCoordinationFault: walletAttemptStorageFault, lastOutcome: deviceOutcome,
        realWalletConnected: false, realTransferPerformed: false,
        acceptance: 'manual-observation-only; environment selection is not device verification'
    };
}
function deviceUpdate() {
    document.getElementById('device-report').value = JSON.stringify(deviceReport(), null, 2);
    document.getElementById('device-resolve').disabled = !devicePending;
    document.getElementById('device-reject').disabled = !devicePending;
}
function deviceSay(text) { document.getElementById('device-status').textContent = text; deviceUpdate(); }
function deviceStart(operation) {
    deviceCounters.reviewRequests++;
    if (walletHandoffPending) { deviceSay('Тестовый ответ ещё ожидается. Повтор заблокирован.'); return; }
    if (walletAttemptBlocked(deviceSay)) { deviceUpdate(); return; }
    const orderId = operation === 'payment' ? 42 : null;
    const data = {from_address: deviceAddress, sell_id: 42, request: {network: '-239', messages: []}};
    openExchangeReview({
        title: operation === 'payment' ? 'Тест: оплата заявки #42' : 'Тест: перевод',
        description: 'Это имитация. Кошелёк не подключается, подписи и деньги не используются. После подтверждения выберите тестовый ответ на основной странице.',
        confirmLabel: 'Начать имитацию',
        rows: [{label: 'Исполнитель', value: 'Локальная имитация ответа'}, {label: 'Сумма', value: '0 · никаких средств'}],
        risk: 'Проверяется только интерфейс, блокировка повторов и сохранение тестового напоминания. Это не проверка реальной подписи или оплаты.',
        onConfirm: async grant => {
            try {
                const sent = await runWalletHandoff(data, operation, orderId, deviceSay, grant);
                if (sent) { deviceOutcome = 'synthetic-resolved'; deviceSay('Получен тестовый ответ. Напоминание остаётся до ручной проверки.'); }
            } catch (_) { deviceOutcome = 'synthetic-rejected-unknown'; deviceSay('Имитирован неизвестный исход. Напоминание остаётся; автоматического повтора нет.'); }
            deviceUpdate();
        }
    });
    deviceUpdate();
}
document.getElementById('device-transfer').addEventListener('click', () => deviceStart('transfer'));
document.getElementById('device-payment').addEventListener('click', () => deviceStart('payment'));
for (const outcome of ['resolve', 'reject']) document.getElementById('device-' + outcome).addEventListener('click', () => {
    if (!devicePending) return;
    const pending = devicePending; devicePending = null;
    if (outcome === 'resolve') { deviceCounters.resolved++; pending.resolve({synthetic: true}); }
    else { deviceCounters.rejected++; pending.reject(new Error('Synthetic unknown outcome')); }
    deviceUpdate();
});
document.getElementById('device-reload').addEventListener('click', () => location.reload());
document.getElementById('device-environment').addEventListener('change', deviceUpdate);
document.getElementById('device-report-copy').addEventListener('click', async () => {
    deviceUpdate();
    const report = document.getElementById('device-report');
    const feedback = document.getElementById('device-copy-status');
    try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error('unavailable');
        await navigator.clipboard.writeText(report.value);
        feedback.textContent = 'Отчёт скопирован. Он никуда не отправлен.';
    } catch (_) { report.focus(); report.select(); feedback.textContent = 'Копирование недоступно. Выделите и скопируйте текст отчёта вручную.'; }
});
new MutationObserver(deviceUpdate).observe(document.getElementById('wallet-attempt-notice'), {attributes: true, subtree: true, childList: true, characterData: true});
document.documentElement.classList.add('device-ready');
deviceUpdate();
