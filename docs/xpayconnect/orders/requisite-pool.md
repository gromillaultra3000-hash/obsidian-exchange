> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/orders/requisite-pool.md).

# Пул реквизитов

Пул реквизитов — механизм, позволяющий мерчанту заранее получить список свободных реквизитов и создать ордер, привязав его к конкретному реквизиту. Это ускоряет процесс выдачи реквизитов клиенту и повышает конверсию.

***

## Получение пула

> Метод: **GET**
>
> Путь: **/merchant/pool/requisites**

Возвращает список реквизитов, доступных для создания ордера прямо сейчас.

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const axios = require('axios');

const apiKey = 'YOUR_API_KEY';
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|`).digest('hex');

const { data } = await axios.get('https://api.xpayconnect.io/merchant/pool/requisites', {
    headers: { 'client-api-key': apiKey, 'x-api-key': xApiKey },
});
```

{% endtab %}

{% tab title="Python" %}

```python
import hashlib
import requests

api_key = 'YOUR_API_KEY'
x_api_key = hashlib.sha256(f'{api_key}|'.encode()).hexdigest()

resp = requests.get('https://api.xpayconnect.io/merchant/pool/requisites', headers={
    'client-api-key': api_key,
    'x-api-key': x_api_key,
})
data = resp.json()
```

{% endtab %}

{% tab title="PHP" %}

```php
$apiKey = 'YOUR_API_KEY';
$xApiKey = hash('sha256', $apiKey . '|');

$ch = curl_init('https://api.xpayconnect.io/merchant/pool/requisites');
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['client-api-key: ' . $apiKey, 'x-api-key: ' . $xApiKey],
]);
$response = json_decode(curl_exec($ch), true);
curl_close($ch);
```

{% endtab %}
{% endtabs %}

### Ответ

```json
{
    "success": true,
    "requisites": [
        { "id": 9319, "amount": 2300, "type": "sim", "remainingSeconds": 847 },
        { "id": 9322, "amount": 2500, "type": "card", "remainingSeconds": 614 }
    ]
}
```

| Поле                 | Тип           | Описание                                                                        |
| -------------------- | ------------- | ------------------------------------------------------------------------------- |
| **success**          | boolean       | `true` при успешном получении пула                                              |
| **requisites**       | array         | Список доступных реквизитов                                                     |
| **id**               | number        | Уникальный идентификатор реквизита в пуле                                       |
| **amount**           | number        | Сумма, закреплённая за реквизитом (в RUB)                                       |
| **type**             | string (enum) | [Платёжный метод](/orders/create.md#platezhnye-metody)                          |
| **remainingSeconds** | number        | Время в секундах, в течение которого реквизит остаётся зарезервированным в пуле |

***

## Создание ордера из пула

> Метод: **POST**
>
> Путь: **/merchant/createOrder**

Создаёт ордер, используя конкретный реквизит из пула. Передайте `usePool: true` и `requisiteId`, полученный на предыдущем шаге.

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const axios = require('axios');

const apiKey = 'YOUR_API_KEY';
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|`).digest('hex');

const { data } = await axios.post('https://api.xpayconnect.io/merchant/createOrder', {
    order_id: 'merchant-order-001',
    usePool: true,
    requisiteId: 9319,
    success_callback_url: 'https://merchant.com/callback',
    merchant_id: 'exMerchant',
    client_id: '99999999',
    currency: 'RUB',
    convertToUsdt: false,
}, {
    headers: { 'client-api-key': apiKey, 'x-api-key': xApiKey },
});
```

{% endtab %}

{% tab title="Python" %}

```python
import hashlib
import requests

api_key = 'YOUR_API_KEY'
x_api_key = hashlib.sha256(f'{api_key}|'.encode()).hexdigest()

resp = requests.post('https://api.xpayconnect.io/merchant/createOrder', json={
    'order_id': 'merchant-order-001',
    'usePool': True,
    'requisiteId': 9319,
    'success_callback_url': 'https://merchant.com/callback',
    'merchant_id': 'exMerchant',
    'client_id': '99999999',
    'currency': 'RUB',
    'convertToUsdt': False,
}, headers={
    'client-api-key': api_key,
    'x-api-key': x_api_key,
})
data = resp.json()
```

{% endtab %}

{% tab title="PHP" %}

```php
$apiKey = 'YOUR_API_KEY';
$xApiKey = hash('sha256', $apiKey . '|');

$body = json_encode([
    'order_id' => 'merchant-order-001',
    'usePool' => true,
    'requisiteId' => 9319,
    'success_callback_url' => 'https://merchant.com/callback',
    'merchant_id' => 'exMerchant',
    'client_id' => '99999999',
    'currency' => 'RUB',
    'convertToUsdt' => false,
]);

$ch = curl_init('https://api.xpayconnect.io/merchant/createOrder');
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $body,
    CURLOPT_HTTPHEADER => [
        'client-api-key: ' . $apiKey,
        'x-api-key: ' . $xApiKey,
        'Content-Type: application/json',
    ],
]);
$response = json_decode(curl_exec($ch), true);
curl_close($ch);
```

{% endtab %}
{% endtabs %}

### Тело запроса

```json
{
    "order_id": "merchant-order-001",
    "usePool": true,
    "requisiteId": 9319,
    "success_callback_url": "https://merchant.com/callback",
    "merchant_id": "exMerchant",
    "client_id": "99999999",
    "currency": "RUB",
    "convertToUsdt": false
}
```

| Поле                       | Тип                     | Описание                                                                                    |
| -------------------------- | ----------------------- | ------------------------------------------------------------------------------------------- |
| **order\_id**              | string (uuid)           | Уникальный идентификатор на стороне мерчанта (external\_id)                                 |
| **usePool**                | boolean                 | `true` — взять реквизит из пула вместо обращения к провайдеру                               |
| **requisiteId**            | number                  | ID реквизита из пула (поле `id` в ответе метода получения пула)                             |
| **merchant\_id**           | string                  | Уникальное имя мерчанта в системе XPayConnect                                               |
| **success\_callback\_url** | string, nullable        | URL для получения вебхука о завершении платежа                                              |
| **client\_id**             | string, nullable        | ID клиента в системе мерчанта. Используется для повышения конверсии на выдачу реквизитов    |
| **currency**               | string (enum), optional | Валюта ордера. Должна совпадать с валютой мерчанта. По умолчанию `RUB`                      |
| **convertToUsdt**          | boolean, optional       | Конвертировать зачисление в USDT. Требуется разрешение администратора. По умолчанию `false` |

### Ответ

```json
{
    "ok": true,
    "id": "lux01993328-a828-7581-b3a9-e712a6a0e88c",
    "payment_id": "uE4wBDWPEN77F9FbrLzXA1w8NbVSB",
    "status": "pending",
    "usdtAmount": 25.5,
    "exchangeRate": 78.3,
    "currency": "RUB",
    "remainingSeconds": 800,
    "payment_details": {
        "address": "+79221110500",
        "bank": "Сбербанк",
        "holder_name": "Имя Фамилия",
        "type": "sim",
        "amount": "2300"
    }
}
```

| Поле                 | Тип           | Описание                                                                                   |
| -------------------- | ------------- | ------------------------------------------------------------------------------------------ |
| **ok**               | boolean       | `true` при успешном создании ордера                                                        |
| **id**               | string (uuid) | Уникальный идентификатор ордера во внутренней системе (internal\_id)                       |
| **payment\_id**      | string        | Идентификатор, переданный мерчантом, либо сгенерированный системой при значении `null`     |
| **status**           | string        | Статус платежа                                                                             |
| **usdtAmount**       | number, null  | Расчётная сумма в USDT (только при `convertToUsdt: true`)                                  |
| **exchangeRate**     | number, null  | Зафиксированный курс USDT/RUB                                                              |
| **currency**         | string        | Валюта ордера                                                                              |
| **remainingSeconds** | number        | Оставшееся время на оплату в секундах. По истечении реквизиты становятся недействительными |
| **payment\_details** | object        | Информация о предоставленных реквизитах                                                    |
| **address**          | string        | Реквизит для совершения оплаты (номер карты, телефона и т.д.)                              |
| **bank**             | string        | Название банка                                                                             |
| **holder\_name**     | string        | Имя держателя реквизитов                                                                   |
| **type**             | string (enum) | [Платёжный метод](/orders/create.md#platezhnye-metody)                                     |
| **amount**           | string        | Сумма к оплате в RUB                                                                       |
