# RSPay — Merchant API (выжимка документации)

Источник: <https://merchant.rspay.win/api-docs> — одностраничное приложение,
скачать «страницы» нечем: весь текст документации лежит строками внутри
JS-бандла (`main.<hash>.js`). Поэтому здесь дословная выжимка, снятая
06.08.2026, а не архив HTML, как у `docs/stormtrade/` и `docs/xpayconnect/`.

## Базовый URL

Фронт кабинета вызывает API относительным путём `/api/v1/` на апексе
`rspay.win` (`PUBLIC_APEX_HOST` в конфиге бандла). Проверено запросом без
ключей — оба хоста отвечают `401 {"error": "Authentication required"}`:

```
https://rspay.win/api/v1/            ← используем этот (RSPAY_BASE_URL)
https://merchant.rspay.win/api/v1/   ← отвечает так же
```

`https://api.payment-aggregator.com` из «AI-промпта» на странице документации —
плейсхолдер их шаблона, а не рабочий хост.

## Аутентификация

Каждый запрос:

| Заголовок | Значение |
|---|---|
| `X-Shop-API-Key` | ключ КОНКРЕТНОГО магазина (кабинет → «Магазины») |
| `X-Signature` | HMAC-SHA256 (hex) от **точного сырого тела**, ключ = **API Secret мерчанта** (кабинет → «Настройки») |
| `X-Timestamp` | UNIX-время в **миллисекундах**, допуск ±5 минут от их сервера |
| `X-Nonce` | уникальная строка (UUID) на запрос, живёт 5 минут, повтор не принимается |

* Для запросов **без тела** (GET) подпись считается **от пустой строки**.
* Ключ магазина и секрет мерчанта — из разных разделов кабинета; секрет после
  создания повторно не показывается.

## Эндпоинты

### `POST /api/v1/requisites/request/` — создать заявку и получить реквизиты

Поля тела:

| Поле | Тип | |
|---|---|---|
| `transaction_id` | string | обяз., уникален в рамках магазина; повтор → **409 Conflict** |
| `payment_method` | string | обяз., код метода — список зависит от магазина |
| `amount` | number/string | обяз. |
| `currency` | string | опц., по умолчанию `RUB` |
| `user` | string | обяз. — стабильный ID клиента; для `payment_method=qr` + `kyc=true` это **номер телефона плательщика** `+7XXXXXXXXXX` |
| `kyc` | boolean | обяз. |
| `receipt` | boolean | опц., по умолчанию `false`; `true` только для `card`/`sbp` — обязывает мерчанта загрузить чек |
| `callback_url` | string | опц., webhook по этой транзакции |
| `client_created_count` | int ≥ 0 | опц., сколько заявок клиент создал у мерчанта |
| `client_paid_count` | int ≥ 0 | опц., сколько оплатил |

Ответ с реквизитами: `success: true, ready: true, status: "available"` и блок
`requisites`, форма которого зависит от метода:

* карта — `card_number`, `bank_name`, `owner_name`;
* СБП / объединённый банковский метод — `phone_number`, `bank_name`, `owner_name`;
* `qr`, `deeplink`, внутрибанковые `*_qr_vnm` — `payment_link`, иногда ещё
  `qr_data` (строка для отрисовки QR, напр. `BANK0001|SUM2500|ORDERorder_vnm_567`).

Плюс `fees.total_fee`, `merchant_transaction_id`, `callback_url`.

Реквизитов нет — это **штатный ответ 200**:

```json
{"success": false, "ready": true, "status": "none",
 "error": "По выбранному методу оплаты нет реквизитов",
 "merchant_transaction_id": "order_123"}
```

### `POST /api/v1/requisites/status/` — платёжный статус по нашему id

Тело: `{"transaction_id": "<merchant_transaction_id>"}`.
Ответ: `success`, `ready` (финальный ли статус), `status`, `transaction_status`
(alias), `requisites_status` (`available` / `none` / `null`),
`legacy_requisites_status`, `merchant_transaction_id`, `rspay_id`, `amount`,
`currency`, `callback_url`, `note`.

### `POST /api/v1/transactions/cancel/` — отмена, если клиент передумал

Тело: `{"transaction_id": "..."}`. Доступна только для `pending` и
`processing`. Повторный вызов — 200 с `already_cancelled: true`. После отмены
приходит вебхук со `status: "cancelled"`.

### `POST /api/v1/requisites/receipt/` — чек мерчанта

`multipart/form-data`: `transaction_id`, `proof` (файл), `comment` (опц.).
Только для заявок, созданных с `receipt=true`. Форматы `pdf`, `png`, `jpg`,
`jpeg`; картинки они сжимают до 1 МБ сами, PDF больше 10 МБ отклоняется.
Legacy-режим — JSON с `receipt_file_base64`.

### `GET /api/v1/merchant/transactions/` — список с пагинацией

Query: `page`, `page_size` (≤100), `status`, `currency`, `date_from`, `date_to`
(ISO 8601).

### `GET /api/v1/transactions/{transaction_id}/` — карточка по ВНУТРЕННЕМУ id

`transaction_id` здесь — числовой id RSPay, не наш `merchant_transaction_id`.

### `GET /api/v1/balance/` — доступный к выводу баланс

`{"balance_rub": "1500.50", "balance_usdt": "15.005000"}`. Источник истины —
USDT, рубли считаются по их курсу. Подпись от пустой строки.

## Статусы транзакции

`pending` — создана, ждёт действий · `processing` — обрабатывается ·
`success` — оплачена · `failed` — отклонена · `cancelled` — отменена ·
`no_requisites` — реквизиты не найдены · `refunded` / `partial_refunded` —
возврат.

## Способы оплаты

Список зависит от магазина, эндпоинта «перечисли мои методы» нет — в кабинете
они сгруппированы как «Базовые», «Внутрибанковые» (суффиксы `_card`, `_sbp`,
`_vnm`) и «Другие». Встречаются в примерах документации: `card`, `sbp`, `qr`,
`deeplink`, `alfabank`, `alfabank_qr_vnm`, `sberbank_qr_vnm`. У нас
обобщённые `card`/`sbp`/`qr` переводятся переменными `RSPAY_METHOD_*`, а точные
коды магазина перечисляются в `RSPAY_METHODS`.

## Вебхук

`POST` на URL из настроек магазина при смене статуса:

```json
{"event_type": "transaction.status_changed",
 "transaction_id": 1587970,
 "merchant_transaction_id": "gp_675545_b5ybih",
 "status": "success", "amount": "4475.00", "currency": "RUB",
 "timestamp": "2026-06-14T16:03:39.080398+00:00",
 "payment_method": "sbp", "requisites_status": "available",
 "fees": {"total_fee": "693.63", "merchant_net_amount": "3781.37"},
 "requisites": {"phone_number": "+79991234567", "bank_name": "Sberbank",
                "owner_name": "Ivan Ivanov"}}
```

* Подпись — `X-Signature`, тот же HMAC-SHA256 от сырого тела.
* **`external_id` мерчанту не отправляется** — сопоставлять только по
  `merchant_transaction_id`.
* Отвечать `200 OK`; при неудаче они повторяют до 3 раз с ростом задержки.

## Ошибки

Формат: `{"error": "...", "errors": {"поле": ["текст"]}, "timestamp": "..."}`.

`400` — валидация · `401` — неверный ключ/подпись, **или** отсутствующий
`X-Timestamp`/`X-Nonce`, **или** время вне окна ±5 минут, **или** повтор nonce ·
`403` — нет прав · `404` — не найдено · `502` — сбой загрузки чека ·
`500` — внутренняя ошибка. Детали процессинга и upstream в тело не попадают.
