#!/usr/bin/env python3
"""Build an inert, offline-capable device diagnostic from bounded production UI code."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
NAMESPACES = {
    'oe.wallet-attempt.v1': 'oe.device-check.wallet-attempt.v1',
    'oe.wallet-attempt.shared.v1': 'oe.device-check.wallet-attempt.shared.v1',
    'oe.wallet-handoff.v1': 'oe.device-check.wallet-handoff.v1',
}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def one(source, pattern, label):
    matches = list(re.finditer(pattern, source, re.M))
    if len(matches) != 1:
        raise ValueError(f'Expected one {label}, found {len(matches)}')
    return matches[0].group(0)


def extract(source):
    helpers = one(source, r'^        const walletAttemptStorageKey[\s\S]*?(?=^        async function createSellOrder)', 'wallet helpers and review')
    esc = one(source, r'^        function esc\(s\) \{[\s\S]*?^        \}', 'esc')
    wiring = [one(source, rf'^        \(function {name}\(\) \{{[\s\S]*?^        \}}\)\(\);', name)
              for name in ('wireExchangeReview', 'wireWalletAttemptNotice')]
    markup = one(source, r'        <section id="wallet-attempt-notice"[\s\S]*?(?=\n        <!-- Рынок)', 'notice and review markup').strip()
    script = '\n'.join([esc, helpers, *wiring])
    # Fail closed if a future broader boundary includes a network/SDK dependency.
    for forbidden in ('fetch(', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'sendBeacon', 'import(', 'initData', 'TON_CONNECT', 'TonConnectUI', '<script', 'eval('):
        if forbidden in script:
            raise ValueError(f'Unexpected active dependency in extracted code: {forbidden}')
    if re.search(r'\b(?:fetch|eval|import)\s*\(|(?:localStorage|sessionStorage)\s*\.\s*clear\s*\(', script):
        raise ValueError('Unexpected network, executable loading or broad storage mutation')
    if re.search(r'<(?:script|iframe|object|embed|form)\b|\s(?:on\w+|src|href|action)\s*=', markup, re.I):
        raise ValueError('Unexpected active markup')
    return script, markup


# No real SDK is loaded. The name mirrors the extracted production boundary only.
STUB = r'''
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
'''
DIAGNOSTIC = r'''
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
'''
CSS = '''
:root{color-scheme:dark;--muted:#c0b7ce}*{box-sizing:border-box}body{margin:0;background:#140a22;color:#f7f4fa;font:16px/1.5 system-ui,sans-serif}main{max-width:760px;margin:auto;padding:18px}h1{font-size:24px;line-height:1.2}h2{font-size:18px}p{margin:10px 0}button,select,textarea{font:inherit}button,select{padding:12px;border:1px solid #b99acb;border-radius:10px;background:#30213e;color:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:default}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible{outline:3px solid #efbc5b;outline-offset:3px}.device-controls{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0}.device-controls button{flex:1 1 150px}label{display:block}input[type=checkbox]{min-width:20px;min-height:20px}textarea{display:block;width:100%;height:260px;background:#21152e;color:#fff;padding:10px;border:1px solid #a68ebd;border-radius:10px;font:12px/1.5 monospace;resize:vertical}#device-status,#device-copy-status{min-height:24px;overflow-wrap:anywhere}.device-note{padding:12px;border:1px solid #bd8c55;border-radius:10px}html:not(.device-ready) #wallet-attempt-notice{display:none}.exchange-review-surface{color:#f7f4fa}ol{padding-left:22px}a{color:#d6b2f5}
'''
HTML = '''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'none'; img-src 'none'; font-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'">
<meta name="referrer" content="no-referrer"><title>Проверка интерфейса кошелька на устройстве</title><link rel="stylesheet" href="device-check.css"><script src="device-check.js" defer></script></head>
<body><main><h1>Проверка интерфейса на устройстве</h1>
<p class="device-note">Только имитация. Здесь нет подключения кошелька, Telegram SDK, подписи или перевода денег. Ничего вводить из кошелька не нужно. Отчёт остаётся на устройстве.</p>
<p>Для проверки Mini App откройте preview кнопкой бота и перейдите к проверке устройства по ссылке внизу. Прямая ссылка может открыться в браузере Telegram и сама по себе не подтверждает запуск Mini App. Выбор ниже — ваше описание среды, а не подтверждение совместимости.</p>
<label for="device-environment">Где вы открыли страницу?</label><select id="device-environment"><option value="unknown">Не указано</option><option value="telegram-miniapp-ios">Mini App Telegram на iOS</option><option value="telegram-browser-ios">Браузер Telegram на iOS</option><option value="safari-ios">Safari на iOS</option><option value="telegram-miniapp-android">Mini App Telegram на Android</option><option value="telegram-browser-android">Браузер Telegram на Android</option><option value="other">Другой браузер</option></select>
<ol><li>Начните тест, прочитайте условия и подтвердите имитацию.</li><li>Пока ответ ожидается, попробуйте второй тест или эту же ссылку в другой вкладке: повтор должен блокироваться.</li><li>Выберите тестовый ответ. Перезагрузите страницу: напоминание должно сохраниться.</li><li>После проверки тестового результата подтвердите это в напоминании и удалите его. Никакой новый тест не запускается автоматически.</li></ol>
<div class="device-controls"><button id="device-transfer" type="button">Тест перевода</button><button id="device-payment" type="button">Тест оплаты</button></div>
<div id="device-status" role="status" aria-live="polite"></div>
<div class="device-controls"><button id="device-resolve" type="button" disabled>Ответ: принят</button><button id="device-reject" type="button" disabled>Ответ: неизвестен</button><button id="device-reload" type="button">Перезагрузить</button></div>
<p>Тексты напоминания ниже взяты из рабочего интерфейса. Здесь «кошелёк» и «заявка» обозначают только тестовые данные.</p>
__MARKUP__
<h2>Локальный отчёт</h2><p>Счётчики относятся только к текущей загрузке страницы. Отчёт не содержит адреса кошелька, данных Telegram или сведений об устройстве, собранных автоматически. При необходимости отправьте его выбранному вами получателю вручную.</p>
<label for="device-report">Текст отчёта</label><textarea id="device-report" readonly spellcheck="false"></textarea><div class="device-controls"><button id="device-report-copy" type="button">Скопировать отчёт</button></div><div id="device-copy-status" role="status" aria-live="polite"></div>
<p>Тестовое напоминание сохраняется для этого сайта до ручного удаления. Его ключи отделены от рабочего приложения. Проверка не подтверждает реальные денежные операции или совместимость другого устройства.</p>
<noscript>Для локальной проверки нужен JavaScript. Без него тест не запущен.</noscript></main></body></html>
'''


def build(source_path):
    source_bytes = source_path.read_bytes()
    source = source_bytes.decode('utf-8')
    original, markup = extract(source)
    transformed = original
    for old, new in NAMESPACES.items():
        if transformed.count("'" + old + "'") != 1:
            raise ValueError('Storage/lock declaration drift: ' + old)
        transformed = transformed.replace("'" + old + "'", "'" + new + "'")
    styles = {}
    def externalize(match):
        style = match.group(1)
        if style not in styles:
            styles[style] = 'device-style-' + str(len(styles) + 1)
        return 'class="' + styles[style] + '"'
    # Only literal presentation attributes change; wallet/review logic remains intact.
    markup = re.sub(r'style="([^"]*)"', externalize, markup)
    transformed = re.sub(r'style="([^"]*)"', externalize, transformed)
    # Merge classes when copied markup already had a class attribute.
    markup = re.sub(r'class="([^"]*)" class="([^"]*)"', r'class="\1 \2"', markup)
    css = CSS
    for style, classname in styles.items():
        if style.startswith('display:none;padding:16px;'):
            style = style.removeprefix('display:none;')
        css += '.' + classname + '{' + style + '}\n'
    source_sha = digest(source_bytes)
    generator_sha = digest(Path(__file__).read_bytes())
    build_id = digest((source_sha + generator_sha).encode())
    metadata = {'id': build_id, 'sourceSHA256': source_sha, 'generatorSHA256': generator_sha}
    script = "'use strict';\nconst deviceBuild = " + json.dumps(metadata, separators=(',', ':')) + ';\n' + STUB + '\n// BEGIN EXTRACTED PRODUCTION\n' + transformed + '\n// END EXTRACTED PRODUCTION\n' + DIAGNOSTIC
    files = {'index.html': HTML.replace('__MARKUP__', markup), 'device-check.js': script, 'device-check.css': css}
    manifest = {'schemaVersion': 1, 'build': metadata, 'source': 'relay/webapp.html',
                'scope': 'inert device UI diagnostic; no real SDK, authentication, transfer, network API or report upload',
                'originalExtractSHA256': digest(original.encode()), 'transformedExtractSHA256': digest(transformed.encode()),
                'namespaces': NAMESPACES, 'styleExternalization': styles,
                'noticeInitialVisibility': 'external CSS hides notice until device-ready; production render controls visibility thereafter',
                'artifacts': {name: digest(content.encode()) for name, content in files.items()}}
    files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'relay/webapp.html')
    parser.add_argument('--output', type=Path, default=ROOT / 'preview/e4-wallet-device-check')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    files = build(args.source)
    if args.check:
        if not args.output.is_dir() or {p.name for p in args.output.iterdir()} != set(files):
            raise SystemExit('Device artifact set differs')
        for name, content in files.items():
            if (args.output / name).read_text() != content:
                raise SystemExit('Device artifact differs: ' + name)
        print('DEVICE_CHECK_BUILD_EXACT')
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (args.output / name).write_text(content)
        print('DEVICE_CHECK_BUILT')


if __name__ == '__main__':
    main()
