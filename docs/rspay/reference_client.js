/**
 * RSPay — эталонный клиент на Node.js (справочный, в бою НЕ используется).
 *
 * Боевая интеграция обменника живёт в relay/providers/rspay.py: сервис на
 * FastAPI + aiogram, отдельного Node-процесса в нём нет. Этот файл написан
 * потому, что его форма задана заданием (клиент + express-обработчик вебхука),
 * и потому, что на нём удобно сверять подпись, если Python-сторона получит 401:
 * две независимые реализации одного HMAC — самый быстрый способ понять, чья
 * ошибка.
 *
 * Требуется Node 18+ (глобальные fetch и crypto.randomUUID). Внешних SDK нет:
 * подпись — штатный модуль crypto, multipart собирается руками, чтобы
 * подписывались ровно те байты, которые уходят в сеть.
 *
 *   SHOP_API_KEY  — ключ магазина   (кабинет → «Магазины»)
 *   API_SECRET    — секрет мерчанта (кабинет → «Настройки»)
 *   RSPAY_BASE_URL — по умолчанию https://rspay.win/api/v1
 */
'use strict';

const crypto = require('crypto');

const BASE_URL = (process.env.RSPAY_BASE_URL || 'https://rspay.win/api/v1').replace(/\/+$/, '');
const SHOP_API_KEY = process.env.SHOP_API_KEY || '';
const API_SECRET = process.env.API_SECRET || '';

/** HMAC-SHA256 (hex) от сырого тела. Для запросов без тела — от пустой строки. */
function createSignature(body, apiSecret = API_SECRET) {
  return crypto.createHmac('sha256', apiSecret)
    .update(body === undefined || body === null ? '' : body)
    .digest('hex');
}

/**
 * Заголовки запроса. body — Buffer/строка ровно тех байтов, что уйдут в сеть.
 * Пересобрать тело после подписи (например, повторным JSON.stringify) значит
 * получить 401, который выглядит как «неверный ключ».
 */
function authHeaders(body, contentType) {
  const headers = {
    'X-Shop-API-Key': SHOP_API_KEY,
    'X-Signature': createSignature(body),
    'X-Timestamp': String(Date.now()),      // миллисекунды, окно ±5 минут
    'X-Nonce': crypto.randomUUID(),         // живёт 5 минут, повтор не принимается
  };
  if (contentType) headers['Content-Type'] = contentType;
  return headers;
}

async function parse(res) {
  const text = await res.text();
  let data = null;
  try { data = JSON.parse(text); } catch { /* не-JSON оставляем как есть */ }
  if (res.status === 401) {
    throw new Error('RSPay 401: неверный ключ/секрет, либо часы разошлись больше '
      + 'чем на 5 минут, либо nonce повторился');
  }
  if (res.status === 409) throw new Error('RSPay 409: transaction_id уже существует');
  if (!res.ok) {
    const fields = data && data.errors
      ? ' ' + Object.entries(data.errors)
        .map(([k, v]) => `${k}: ${[].concat(v).join(', ')}`).join('; ')
      : '';
    throw new Error(`RSPay ${res.status}: ${(data && data.error) || text.slice(0, 200)}${fields}`);
  }
  return data;
}

async function post(path, payload) {
  const body = Buffer.from(JSON.stringify(payload), 'utf8');
  const res = await fetch(`${BASE_URL}${path}`, {
    method: 'POST', body, headers: authHeaders(body, 'application/json'),
  });
  return parse(res);
}

async function get(path, query) {
  const qs = query ? '?' + new URLSearchParams(query).toString() : '';
  // Тела нет → подпись от пустой строки.
  const res = await fetch(`${BASE_URL}${path}${qs}`, { headers: authHeaders('') });
  return parse(res);
}

/** 1) Создать заявку и получить реквизиты. */
function requestRequisites(payload) {
  const {
    transaction_id, payment_method, amount, currency = 'RUB',
    user, kyc, receipt, callback_url, client_created_count, client_paid_count,
  } = payload;
  if (!transaction_id || !payment_method || !amount || !user || kyc === undefined) {
    throw new Error('requestRequisites: обязательны transaction_id, payment_method, '
      + 'amount, user, kyc');
  }
  // kyc=true допустим только для qr и только если в user лежит телефон
  // плательщика: иначе верификация уйдёт на чужой номер.
  if (kyc === true && !/^\+7\d{10}$/.test(String(user))) {
    throw new Error('kyc=true требует в поле user номер телефона +7XXXXXXXXXX');
  }
  const body = { transaction_id, payment_method, amount, currency, user, kyc };
  if (receipt !== undefined) body.receipt = receipt;
  if (callback_url) body.callback_url = callback_url;
  if (client_created_count !== undefined) body.client_created_count = client_created_count;
  if (client_paid_count !== undefined) body.client_paid_count = client_paid_count;
  return post('/requisites/request/', body);
}

/** 2) Загрузить чек (только для заявок, созданных с receipt=true). */
async function uploadReceipt({ transaction_id, proof, filename, contentType, comment }) {
  const allowed = { pdf: 'application/pdf', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };
  const ext = String(filename || '').split('.').pop().toLowerCase();
  const type = contentType || allowed[ext];
  if (!type) throw new Error('RSPay принимает чек только в pdf, png, jpg или jpeg');
  if (ext === 'pdf' && proof.length > 10 * 1024 * 1024) {
    throw new Error('RSPay не примет PDF больше 10 МБ');
  }

  // multipart собирается вручную: так подписываются ровно те байты, что уходят.
  const boundary = '----rspay' + crypto.randomBytes(16).toString('hex');
  const part = (name, value) => Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="${name}"\r\n\r\n${value}\r\n`, 'utf8');
  const chunks = [part('transaction_id', transaction_id)];
  if (comment) chunks.push(part('comment', comment));
  chunks.push(Buffer.from(
    `--${boundary}\r\nContent-Disposition: form-data; name="proof"; filename="${filename}"\r\n`
    + `Content-Type: ${type}\r\n\r\n`, 'utf8'), proof, Buffer.from('\r\n', 'utf8'));
  chunks.push(Buffer.from(`--${boundary}--\r\n`, 'utf8'));
  const body = Buffer.concat(chunks);

  const res = await fetch(`${BASE_URL}/requisites/receipt/`, {
    method: 'POST', body,
    headers: authHeaders(body, `multipart/form-data; boundary=${boundary}`),
  });
  return parse(res);
}

/**
 * 3) Статус.
 *  - byMerchantId: по НАШЕМУ transaction_id (то, чем пользуются в бою);
 *  - getTransactionStatus: по ВНУТРЕННЕМУ числовому id RSPay.
 * Перепутать их местами — получить 404 и решить, что платежа нет.
 */
const byMerchantId = (transaction_id) => post('/requisites/status/', { transaction_id });
const getTransactionStatus = (transaction_id) => get(`/transactions/${transaction_id}/`);
const cancelTransaction = (transaction_id) => post('/transactions/cancel/', { transaction_id });
const listTransactions = (query) => get('/merchant/transactions/', query);
const getBalance = () => get('/balance/');

/** 4) Проверка подписи входящего вебхука. */
function verifyWebhookSignature(rawBody, signature, apiSecret = API_SECRET) {
  // Пустой секрет или пустая подпись — это «проверить невозможно», а не
  // «проверка пройдена»: иначе любой POST пометит заявку оплаченной.
  if (!apiSecret || !signature) return false;
  const expected = createSignature(rawBody, apiSecret);
  const a = Buffer.from(String(signature).trim().toLowerCase(), 'utf8');
  const b = Buffer.from(expected, 'utf8');
  // Длины сверяем отдельно: timingSafeEqual на разных длинах бросает исключение.
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

// ── пример вызова ────────────────────────────────────────────────────────────

async function example() {
  const created = await requestRequisites({
    transaction_id: `order_${Date.now()}`,
    payment_method: 'card',
    amount: '8571.00',
    user: 'user_123',
    kyc: false,
    receipt: true,
    client_created_count: 12,
    client_paid_count: 9,
    callback_url: 'https://merchant.example.com/webhook',
  });
  if (!created.success || !created.requisites) {
    // Штатный ответ 200: свободных реквизитов сейчас нет. Это не сбой канала —
    // повторять тем же способом бессмысленно, нужен другой метод или маршрут.
    console.warn('реквизиты не выданы:', created.error);
    return;
  }
  console.log('реквизиты:', created.requisites, 'комиссия:', created.fees);
  console.log('статус:', await byMerchantId(created.merchant_transaction_id));
}

// ── express-обработчик вебхука ───────────────────────────────────────────────

function mountWebhook(app) {
  // express.raw обязателен: подпись считается от СЫРЫХ байтов, а express.json
  // отдал бы уже разобранный объект, и обратная сборка дала бы другие байты.
  app.post('/webhook', require('express').raw({ type: '*/*' }), (req, res) => {
    const rawBody = Buffer.isBuffer(req.body) ? req.body : Buffer.from(req.body || '');
    if (!verifyWebhookSignature(rawBody, req.header('X-Signature') || '')) {
      return res.status(401).send('invalid signature');
    }
    let payload;
    try { payload = JSON.parse(rawBody.toString('utf8')); } catch { return res.sendStatus(400); }

    // Сопоставление ТОЛЬКО по merchant_transaction_id: external_id мерчанту
    // не приходит. Возврат (refunded) оплатой не считать.
    const { merchant_transaction_id: id, status } = payload;
    if (status === 'success') markPaid(id, payload);
    else if (status === 'refunded' || status === 'partial_refunded') alertHumans(id, payload);

    // 200 сразу после записи события: RSPay повторяет до 3 раз.
    res.sendStatus(200);
  });
}

function markPaid(id, payload) { console.log('оплачено', id, payload.amount); }
function alertHumans(id, payload) { console.warn('возврат по', id, payload.status); }

module.exports = {
  createSignature, authHeaders, requestRequisites, uploadReceipt,
  getTransactionStatus, byMerchantId, cancelTransaction, listTransactions,
  getBalance, verifyWebhookSignature, mountWebhook, example,
};
