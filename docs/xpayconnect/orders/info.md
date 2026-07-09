> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/orders/info.md).

# Информация об ордере

> Метод: **GET**
>
> Путь: **/merchant/order/{id}**

{% hint style="info" %}
Параметр `{id}` — это `internal_id` ордера (формат `lux...`) или `order_id` (external\_id), переданный мерчантом при создании.
{% endhint %}

#### Примеры запроса

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const axios = require('axios');

const apiKey = 'YOUR_API_KEY';
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|`).digest('hex');

const { data } = await axios.get('https://api.xpayconnect.io/merchant/order/lux01993328-a828-7581-b3a9-e712a6a0e88c', {
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

resp = requests.get('https://api.xpayconnect.io/merchant/order/lux01993328-a828-7581-b3a9-e712a6a0e88c', headers={
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

$ch = curl_init('https://api.xpayconnect.io/merchant/order/lux01993328-a828-7581-b3a9-e712a6a0e88c');
curl_setopt_array($ch, [
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => [
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
    "id": "lux019dde94-0c92-746e-9bbc-6041608c469d",
    "payment_id": "11664",
    "status": "success",
    "success_callback_url": "https://example.com/wbh",
    "created_at": "2026-04-30T13:28:57.764Z",
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
```

| Поле                       | Тип               | Описание                                                                                                                                                                                                                                                                                                                     |
| -------------------------- | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ok**                     | boolean           | `true` при успешном запросе                                                                                                                                                                                                                                                                                                  |
| **id**                     | string            | Уникальный идентификатор в системе (internal\_id)                                                                                                                                                                                                                                                                            |
| **payment\_id**            | string            | Идентификатор на стороне мерчанта (external\_id)                                                                                                                                                                                                                                                                             |
| **status**                 | string (enum)     | `pending` — в работе, `success` — успешно, `error` — отменён/ошибка                                                                                                                                                                                                                                                          |
| **success\_callback\_url** | string, null      | URL для отправки вебхука                                                                                                                                                                                                                                                                                                     |
| **created\_at**            | string (datetime) | Дата и время создания ордера                                                                                                                                                                                                                                                                                                 |
| **currency**               | string (enum)     | Валюта ордера: `RUB`, `KGS`, `KZT`, `UZS`. Совпадает с валютой мерчанта                                                                                                                                                                                                                                                      |
| **usdtAmount**             | number, null      | Оценочная сумма в USDT **БЕЗ** учёта комиссии мерчанта. Для фиатных методов = `amount / exchangeRate` (только при `convertToUsdt: true`). Для `usdt_trc20`/`ton` = сумма из `cryptoAmount` (то, что платит клиент). Для `ton` численно содержит сумму в TON, не USDT                                                         |
| **usdtAmountAfterFee**     | number, null      | Сумма в USDT, начисляемая на USDT-баланс мерчанта **после** комиссии. До `success` — оценка; после `success` — точное значение из БД. Возвращается, если есть базовое USDT-значение (фиатные методы с `convertToUsdt: true` или `usdt_trc20`/`ton` с заполненным `cryptoAmount`). Для `ton` численно содержит сумму в TON    |
| **amountAfterFee**         | number            | Сумма в фиатной валюте после удержания комиссии мерчанта (`amount − round(amount × fee% / 100)`). До `success` — оценка; после `success` — точное значение из БД. Возвращается всегда                                                                                                                                        |
| **exchangeRate**           | number, null      | Зафиксированный курс USDT/`currency` (заполняется при `convertToUsdt: true` для фиатных методов; для `usdt_trc20`/`ton` отсутствует)                                                                                                                                                                                         |
| **payment\_details**       | object            | Информация о реквизитах                                                                                                                                                                                                                                                                                                      |
| ↳ **address**              | string            | Реквизиты для оплаты                                                                                                                                                                                                                                                                                                         |
| ↳ **bank**                 | string            | Название банка                                                                                                                                                                                                                                                                                                               |
| ↳ **holder\_name**         | string            | Имя держателя реквизитов                                                                                                                                                                                                                                                                                                     |
| ↳ **type**                 | string (enum)     | [Платёжный метод](/orders/create.md#platezhnye-metody)                                                                                                                                                                                                                                                                       |
| ↳ **amount**               | string            | Финальная сумма к оплате клиентом в валюте `currency`. Может отличаться от переданного мерчантом значения после [уникализации в системе](/orders/create.md#unikalizaciya-summy)                                                                                                                                              |
| ↳ **cryptoAmount**         | string, null      | Сумма к оплате в криптовалюте — заполняется только для крипто-методов (`usdt_trc20`, `ton`, `btc`, `ltc` и т.п.). Для `ton` сумма в TON, не в USDT. Для фиатных методов (`card`/`sim`/`sbp`) отсутствует — конвертация выручки мерчанта в USDT регулируется флагом `convertToUsdt` и полями `usdtAmount`/`exchangeRate` выше |

{% hint style="info" %}
Поле `payment_details.cryptoAmount` появляется в ответе **только для крипто-методов**. Для ордера выше (метод `card`) его нет. Пример ответа для `usdt_trc20`:

```json
{
    "ok": true,
    "id": "lux01993328-...",
    "payment_id": "uE4w...",
    "status": "pending",
    "currency": "RUB",
    "usdtAmount": 20,
    "usdtAmountAfterFee": 17.4,
    "amountAfterFee": 2001,
    "payment_details": {
        "address": "TXY...usdt-address",
        "bank": "USDT TRC-20",
        "holder_name": "—",
        "type": "usdt_trc20",
        "amount": "2300",
        "cryptoAmount": "20.00000000"
    }
}
```

Для `usdt_trc20` поля `usdtAmount` / `usdtAmountAfterFee` берутся из `cryptoAmount` (так как сумма уже в USDT), `exchangeRate` отсутствует. Для `usdt_trc20` ордеров фиатный `amountAfterFee` всё равно возвращается — это сумма в валюте мерчанта после удержания комиссии (релевантно, если мерчант на фиатном балансе).

Аналогично для `ton` (работает через LuckyExchange):

```json
{
    "ok": true,
    "id": "lux01993328-...",
    "payment_id": "uE4w...",
    "status": "pending",
    "currency": "RUB",
    "usdtAmount": 50,
    "usdtAmountAfterFee": 47.5,
    "amountAfterFee": 4750,
    "payment_details": {
        "address": "UQA...ton-address",
        "bank": "TON",
        "holder_name": "TON",
        "type": "ton",
        "amount": "5000",
        "cryptoAmount": "50.00000000"
    }
}
```

Для `ton` поля `usdtAmount` / `usdtAmountAfterFee` содержат сумму в **TON** (название поля унаследовано от usdt-метода, численно это TON-amount). `exchangeRate` отсутствует. `convertToUsdt: true` для метода `ton` не поддерживается — система не знает курс TON/USD, поэтому создание ордера будет отклонено.
{% endhint %}
