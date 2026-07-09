> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/orders/payout.md).

# Создание выплаты (PAYOUT)

> Метод: **POST**
>
> Путь: **/merchant/createOrder**

## Параметры запроса

```json
{
    "order_id": "uE4wBDWPEN77F9FbrLzXA1w8NbVSB",
    "amount": 23000,
    "type": "sim",
    "success_callback_url": "http://test.com/api/order/success",
    "merchant_id": "exMerchant",
    "client_id": "99999999",
    "direction": "PAYOUT",
    "payout_details": {
        "holderAccount": "79030000000",
        "holderName": "Имя Фамилия",
        "methodName": "Альфа Банк"
    }
}
```

| Поле                       | Тип              | Описание                                                                                                                                                                               |
| -------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **order\_id**              | string (uuid)    | Уникальный идентификатор на стороне мерчанта (external\_id)                                                                                                                            |
| **amount**                 | integer          | Сумма выплаты в RUB (брутто, до удержания комиссии мерчанта). С баланса мерчанта спишется `amount` плюс провайдерская комиссия — точную сумму к списанию см. в `amountAfterFee` ответа |
| **type**                   | string (enum)    | **card** — выплата на карту; **sim** — выплата СБП                                                                                                                                     |
| **merchant\_id**           | string           | Уникальное имя мерчанта в системе XPayConnect                                                                                                                                          |
| **success\_callback\_url** | string, nullable | Ссылка в системе мерчанта для получения вебхука, завершающего обмен                                                                                                                    |
| **client\_id**             | string, nullable | ID клиента в системе мерчанта                                                                                                                                                          |
| **direction**              | string (enum)    | Указывается строго для выплат: `PAYOUT`                                                                                                                                                |
| **payout\_details**        | object           | Объект с данными для перевода. Обязателен для выплат                                                                                                                                   |
| ↳ **holderAccount**        | string           | Реквизит для перевода — только цифры без `+`. 11 цифр для СБП, 16 цифр для C2C                                                                                                         |
| ↳ **holderName**           | string           | Имя держателя реквизита                                                                                                                                                                |
| ↳ **methodName**           | string (enum)    | Банк для перевода. Значения из [списка банков](#spisok-bankov-dlya-vyplat-sbp)                                                                                                         |

#### Примеры запроса

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const axios = require('axios');

const apiKey = 'YOUR_API_KEY';
const body = {
    order_id: 'uE4wBDWPEN77F9FbrLzXA1w8NbVSB',
    amount: 23000,
    type: 'sim',
    success_callback_url: 'http://test.com/api/order/success',
    merchant_id: 'exMerchant',
    client_id: '99999999',
    direction: 'PAYOUT',
    payout_details: {
        holderAccount: '79030000000',
        holderName: 'Имя Фамилия',
        methodName: 'Альфа Банк',
    },
};

const bodyStr = JSON.stringify(body);
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|${bodyStr}`).digest('hex');

const { data } = await axios.post('https://api.xpayconnect.io/merchant/createOrder', body, {
    headers: {
        'Content-Type': 'application/json',
        'client-api-key': apiKey,
        'x-api-key': xApiKey,
    },
});
```

{% endtab %}

{% tab title="Python" %}

```python
import hashlib
import json
import requests

api_key = 'YOUR_API_KEY'
body = {
    'order_id': 'uE4wBDWPEN77F9FbrLzXA1w8NbVSB',
    'amount': 23000,
    'type': 'sim',
    'success_callback_url': 'http://test.com/api/order/success',
    'merchant_id': 'exMerchant',
    'client_id': '99999999',
    'direction': 'PAYOUT',
    'payout_details': {
        'holderAccount': '79030000000',
        'holderName': 'Имя Фамилия',
        'methodName': 'Альфа Банк',
    },
}

body_str = json.dumps(body, separators=(',', ':'))
x_api_key = hashlib.sha256(f'{api_key}|{body_str}'.encode()).hexdigest()

resp = requests.post('https://api.xpayconnect.io/merchant/createOrder', json=body, headers={
    'Content-Type': 'application/json',
    'client-api-key': api_key,
    'x-api-key': x_api_key,
})
data = resp.json()
```

{% endtab %}

{% tab title="PHP" %}

```php
$apiKey = 'YOUR_API_KEY';
$body = [
    'order_id' => 'uE4wBDWPEN77F9FbrLzXA1w8NbVSB',
    'amount' => 23000,
    'type' => 'sim',
    'success_callback_url' => 'http://test.com/api/order/success',
    'merchant_id' => 'exMerchant',
    'client_id' => '99999999',
    'direction' => 'PAYOUT',
    'payout_details' => [
        'holderAccount' => '79030000000',
        'holderName' => 'Имя Фамилия',
        'methodName' => 'Альфа Банк',
    ],
];

$bodyStr = json_encode($body, JSON_UNESCAPED_UNICODE);
$xApiKey = hash('sha256', $apiKey . '|' . $bodyStr);

$ch = curl_init('https://api.xpayconnect.io/merchant/createOrder');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $bodyStr,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => [
        'Content-Type: application/json',
        'client-api-key: ' . $apiKey,
        'x-api-key: ' . $xApiKey,
    ],
]);
$response = json_decode(curl_exec($ch), true);
curl_close($ch);
```

{% endtab %}
{% endtabs %}

***

## Ответ

```json
{
    "ok": true,
    "id": "lux01993328-a828-7581-b3a9-e712a6a0e88c",
    "payment_id": "uE4wBDWPEN77F9FbrLzXA1w8NbVSB",
    "status": "pending",
    "direction": "PAYOUT",
    "currency": "RUB",
    "amountAfterFee": 22540,
    "payment_details": {
        "address": "79030000000",
        "bank": "Альфа Банк",
        "holder_name": "Имя Фамилия",
        "type": "sim",
        "amount": "23000"
    }
}
```

| Поле                 | Тип           | Описание                                                                                                                                                                 |
| -------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **ok**               | boolean       | `true` при успешном предоставлении реквизитов                                                                                                                            |
| **id**               | string (uuid) | Уникальный идентификатор внутренней системы (internal\_id)                                                                                                               |
| **payment\_id**      | string        | **order\_id**, переданный мерчантом при создании, либо сгенерированный системой, если передан `null`                                                                     |
| **status**           | string (enum) | Статус платежа: `pending`, `success`, `error`                                                                                                                            |
| **direction**        | string (enum) | `PAYOUT` для выплат                                                                                                                                                      |
| **currency**         | string        | Валюта ордера (для PAYOUT — `RUB`)                                                                                                                                       |
| **amountAfterFee**   | number        | Сумма в фиатной валюте после удержания комиссии мерчанта за выплату (`outFee`). Зафиксирована при создании ордера; при success — фактическое списание с баланса мерчанта |
| **payment\_details** | object        | Информация о предоставленных реквизитах                                                                                                                                  |
| ↳ **address**        | string        | Реквизиты для перевода                                                                                                                                                   |
| ↳ **bank**           | string        | Название банка                                                                                                                                                           |
| ↳ **holder\_name**   | string        | Имя держателя реквизитов                                                                                                                                                 |
| ↳ **type**           | string (enum) | [Платёжный метод для выплат](#platezhnye-metody-dlya-vyplat)                                                                                                             |
| ↳ **amount**         | string        | Сумма выплаты в RUB (брутто, до удержания комиссии)                                                                                                                      |

{% hint style="info" %}
USDT-конвертация (`convertToUsdt`) для выплат **не поддерживается** — поля `usdtAmount`, `usdtAmountAfterFee`, `exchangeRate` в ответах PAYOUT всегда отсутствуют. Комиссия за выплаты регулируется отдельным процентом `outFee` (настраивается на мерчанте), который применяется к `amount` при формировании `amountAfterFee`.
{% endhint %}

***

## Платёжные методы для выплат

| Метод    | Описание |
| -------- | -------- |
| **card** | Карта РФ |
| **sim**  | СБП РФ   |

***

## Список банков для выплат СБП

> Метод: **GET**
>
> Путь: **/merchant/banks**

Возвращает список доступных банков для выплат по СБП. Значения поля `methodName` из ответа этого эндпоинта передаются в поле `payout_details.methodName` при создании выплаты.
