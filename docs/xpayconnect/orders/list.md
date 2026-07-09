> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/orders/list.md).

# Список ордеров

> Метод: **GET**
>
> Путь: **/merchant/orders**

## Параметры запроса

| Поле              | Тип               | Обязательный | Описание                                                                       |
| ----------------- | ----------------- | ------------ | ------------------------------------------------------------------------------ |
| **merchant\_id**  | string            | да           | Уникальное имя мерчанта в системе XPayConnect                                  |
| **page**          | integer           | нет          | Номер страницы. По умолчанию: `1`                                              |
| **size**          | integer           | нет          | Элементов на странице. По умолчанию: `10`, максимум: `100`                     |
| **type**          | string (enum)     | нет          | Фильтр по [платёжному методу](/orders/create.md#platezhnye-metody)             |
| **order\_status** | string (enum)     | нет          | Фильтр по статусу: `pending`, `success`, `error`                               |
| **start\_date**   | string (datetime) | нет          | Начало периода, формат: `2025-02-06 00:00:00`. UTC. По умолчанию: текущий день |
| **end\_date**     | string (datetime) | нет          | Конец периода, формат: `2025-02-06 23:59:59`. UTC. По умолчанию: текущий день  |

#### Примеры запроса

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const axios = require('axios');

const apiKey = 'YOUR_API_KEY';
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|`).digest('hex');

const { data } = await axios.get('https://api.xpayconnect.io/merchant/orders', {
    params: { merchant_id: 'exMerchant', page: 1, size: 10 },
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

resp = requests.get('https://api.xpayconnect.io/merchant/orders', params={
    'merchant_id': 'exMerchant', 'page': 1, 'size': 10,
}, headers={'client-api-key': api_key, 'x-api-key': x_api_key})
data = resp.json()
```

{% endtab %}

{% tab title="PHP" %}

```php
$apiKey = 'YOUR_API_KEY';
$xApiKey = hash('sha256', $apiKey . '|');
$url = 'https://api.xpayconnect.io/merchant/orders?' . http_build_query([
    'merchant_id' => 'exMerchant', 'page' => 1, 'size' => 10,
]);

$ch = curl_init($url);
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['client-api-key: ' . $apiKey, 'x-api-key: ' . $xApiKey],
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
    "total": 3,
    "orders": [
        {
            "id": "lux019dde94-0c92-746e-9bbc-6041608c469d",
            "payment_id": "11664",
            "status": "success",
            "success_callback_url": "https://example.com/wbh",
            "created_at": "2026-04-30T13:28:57.764Z",
            "merchantFeePercent": 13,
            "convertToUsdt": true,
            "currency": "KZT",
            "usdtAmount": 47.87,
            "usdtAmountAfterFee": 41.65,
            "amountAfterFee": 19891.43,
            "exchangeRate": 463.2823486606767,
            "payment_details": {
                "address": "4400430353907287",
                "bank": "Kaspi Bank (KZ)",
                "holder_name": "ARTUR RUZIBOEV",
                "type": "card",
                "amount": "22305"
            }
        }
    ]
}
```

| Поле                                   | Тип               | Описание                                                                                                                                                                                                           |
| -------------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **ok**                                 | boolean           | `true` при успешном запросе                                                                                                                                                                                        |
| **total**                              | integer           | Общее количество ордеров по фильтру                                                                                                                                                                                |
| **orders**                             | array             | Массив ордеров                                                                                                                                                                                                     |
| **orders\[\*].id**                     | string            | Уникальный идентификатор в системе (internal\_id)                                                                                                                                                                  |
| **orders\[\*].payment\_id**            | string            | Идентификатор на стороне мерчанта                                                                                                                                                                                  |
| **orders\[\*].status**                 | string (enum)     | `pending`, `success`, `error`                                                                                                                                                                                      |
| **orders\[\*].success\_callback\_url** | string, null      | URL, на который отправляется вебхук при success                                                                                                                                                                    |
| **orders\[\*].created\_at**            | string (datetime) | Дата и время создания                                                                                                                                                                                              |
| **orders\[\*].currency**               | string (enum)     | Валюта ордера: `RUB`, `KGS`, `KZT`, `UZS`                                                                                                                                                                          |
| **orders\[\*].usdtAmount**             | number, null      | Оценочная сумма в USDT **БЕЗ** учёта комиссии. Для фиатных методов = `amount / exchangeRate` (при `convertToUsdt: true`); для `usdt_trc20` = сумма из `cryptoAmount`                                               |
| **orders\[\*].usdtAmountAfterFee**     | number, null      | Сумма в USDT, начисляемая на USDT-баланс мерчанта **после** комиссии. До `success` — оценка; после `success` — точное значение из БД                                                                               |
| **orders\[\*].amountAfterFee**         | number            | Сумма в фиатной валюте после удержания комиссии мерчанта. До `success` — оценка; после `success` — точное значение. Возвращается всегда                                                                            |
| **orders\[\*].exchangeRate**           | number, null      | Зафиксированный курс USDT/`currency` (фиатные методы с `convertToUsdt: true`)                                                                                                                                      |
| **orders\[\*].convertToUsdt**          | boolean           | Флаг, переданный мерчантом при создании ордера: будет ли выручка конвертирована и начислена на USDT-баланс                                                                                                         |
| **orders\[\*].merchantFeePercent**     | number            | Зафиксированная при создании комиссия мерчанта (в процентах)                                                                                                                                                       |
| **orders\[\*].payment\_details**       | object            | Информация о реквизитах (аналогично [информации об ордере](/orders/info.md)) — включает `address`, `bank`, `holder_name`, `type`, `amount` (финальная сумма к оплате) и `cryptoAmount` (только для крипто-методов) |
