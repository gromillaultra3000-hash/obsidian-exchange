> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/orders/create.md).

# Создание ордера (PAYIN-FIAT)

> Метод: **POST**
>
> Путь: **/merchant/createOrder**

## Параметры запроса

```json
{
    "order_id": "uE4wBDWPEN77F9FbrLzXA1w8NbVSB",
    "amount": 2300,
    "amountUp": 120,
    "amountDown": 10,
    "type": "sim",
    "success_callback_url": "http://test.com/api/order/success",
    "merchant_id": "exMerchant",
    "client_id": "99999999",
    "currency": "RUB",
    "convertToUsdt": false,
    "comment": "Заказ #12345"
}
```

| Поле                       | Тип                     | Описание                                                                                                               |
| -------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **order\_id**              | string (uuid)           | Уникальный идентификатор на стороне мерчанта (external\_id)                                                            |
| **amount**                 | integer                 | Сумма платежа в валюте мерчанта. См. [Валюты](/reference/currencies.md)                                                |
| **type**                   | string (enum)           | [Платёжные методы](/reference/payment-methods.md)                                                                      |
| **merchant\_id**           | string                  | Уникальное имя мерчанта в системе XPayConnect                                                                          |
| **success\_callback\_url** | string, nullable        | Ссылка в системе мерчанта для получения вебхука, завершающего обмен                                                    |
| **client\_id**             | string, nullable        | ID клиента в системе мерчанта. Используется для идентификации плательщика                                              |
| **currency**               | string (enum), optional | Валюта ордера. См. [Валюты](/reference/currencies.md). По умолчанию: `RUB`                                             |
| **convertToUsdt**          | boolean, optional       | Конвертировать зачисление в USDT. Требуется доступ от администрации. По умолчанию: `false`                             |
| **amountUp**               | number, optional        | Допустимое отклонение суммы вверх для уникализации (см. ниже)                                                          |
| **amountDown**             | number, optional        | Допустимое отклонение суммы вниз для уникализации (см. ниже)                                                           |
| **comment**                | string, optional        | Произвольный комментарий от мерчанта. Максимум 500 символов. Сохраняется в ордере и доступен в административной панели |

#### Примеры запроса

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const axios = require('axios');

const apiKey = 'YOUR_API_KEY';
const body = {
    order_id: 'uE4wBDWPEN77F9FbrLzXA1w8NbVSB',
    amount: 2300,
    type: 'sim',
    success_callback_url: 'http://test.com/api/order/success',
    merchant_id: 'exMerchant',
    client_id: '99999999',
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
    'amount': 2300,
    'type': 'sim',
    'success_callback_url': 'http://test.com/api/order/success',
    'merchant_id': 'exMerchant',
    'client_id': '99999999',
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
    'amount' => 2300,
    'type' => 'sim',
    'success_callback_url' => 'http://test.com/api/order/success',
    'merchant_id' => 'exMerchant',
    'client_id' => '99999999',
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
    "usdtAmount": 29.37,
    "usdtAmountAfterFee": 25.5,
    "amountAfterFee": 2001,
    "exchangeRate": 78.3,
    "currency": "RUB",
    "payment_details": {
        "address": "+79221110500",
        "bank": "Сбербанк",
        "holder_name": "Имя Фамилия",
        "type": "sim",
        "amount": "2300"
    }
}
```

| Поле                   | Тип              | Описание                                                                                                                                                                                                                                                                               |
| ---------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ok**                 | boolean          | `true` при успешном предоставлении реквизитов                                                                                                                                                                                                                                          |
| **id**                 | string (uuid)    | Уникальный идентификатор внутренней системы (internal\_id)                                                                                                                                                                                                                             |
| **payment\_id**        | string           | **order\_id**, переданный мерчантом при создании, либо сгенерированный системой, если передан `null`                                                                                                                                                                                   |
| **status**             | string (enum)    | Статус платежа: `pending`, `success`, `error`                                                                                                                                                                                                                                          |
| **usdtAmount**         | number, null     | Оценочная сумма в USDT по курсу `exchangeRate`, рассчитанная **БЕЗ** учёта комиссии мерчанта (`amount / exchangeRate`). Заполняется только при `convertToUsdt: true`                                                                                                                   |
| **usdtAmountAfterFee** | number, null     | Оценочная сумма в USDT, которая будет начислена на USDT-баланс мерчанта **после** удержания комиссии: `(amount − комиссия) / exchangeRate`. На этапе создания — оценка; точная сумма фиксируется при `success`. Заполняется только при `convertToUsdt: true`                           |
| **amountAfterFee**     | number           | Сумма в фиатной валюте после удержания комиссии мерчанта (`amount − round(amount × fee% / 100)`). Возвращается всегда, в т.ч. без `convertToUsdt`. Полезно для мерчантов на фиатном балансе, чтобы заранее видеть, сколько именно зачислится после успеха ордера                       |
| **exchangeRate**       | number, null     | Зафиксированный курс USDT/`currency`                                                                                                                                                                                                                                                   |
| **currency**           | string           | Валюта ордера                                                                                                                                                                                                                                                                          |
| **payment\_details**   | object           | Информация о предоставленных реквизитах                                                                                                                                                                                                                                                |
| ↳ **address**          | string           | Реквизиты для совершения оплаты                                                                                                                                                                                                                                                        |
| ↳ **bank**             | string           | Название банка                                                                                                                                                                                                                                                                         |
| ↳ **holder\_name**     | string           | Имя держателя реквизитов                                                                                                                                                                                                                                                               |
| ↳ **type**             | string (enum)    | [Платёжный метод](/reference/payment-methods.md)                                                                                                                                                                                                                                       |
| ↳ **amount**           | string           | Финальная сумма к оплате клиентом в валюте `currency` (может отличаться от переданной мерчантом — после уникализации в системе)                                                                                                                                                        |
| ↳ **cryptoAmount**     | string, optional | Точная сумма к оплате в крипто-валюте — присутствует **только для крипто-методов** (`usdt_trc20` и т.п.). Если адаптер ещё не успел получить её от провайдера на момент ответа, поле отсутствует — в этом случае его можно получить через [`GET /merchant/order/:id`](/orders/info.md) |

***

## Уникализация суммы

Для устранения коллизий при матчинге банковских уведомлений с ордерами система может автоматически сдвигать сумму в заданном диапазоне, чтобы каждый активный ордер имел уникальное значение.

### Как работает

Если в системе уже есть активный pending-ордер с такой же суммой, то сумма нового ордера будет сдвинута в пределах `[amount - amountDown, amount + amountUp]`:

* Сначала пробуется `amount + 1`, затем `amount - 1`, `amount + 2`, `amount - 2` и т.д.
* Используется первое свободное значение
* Если все значения в диапазоне заняты — возвращается оригинальная сумма

{% hint style="info" %}
Поле `amount` в `payment_details` ответа — это **финальная сумма**, которую клиент должен оплатить. Она может отличаться от запрошенной.
{% endhint %}

### Настройка

Уникализация работает только для валюты `RUB` и только для PAYIN-ордеров. Она включается автоматически если:

* В запросе передан `amountUp > 0` или `amountDown > 0`, либо
* У мерчанта в настройках заданы `defaultAmountUp > 0` или `defaultAmountDown > 0`

Приоритет: значения из запроса имеют приоритет над настройками мерчанта.

{% hint style="warning" %}
Если оба отклонения равны `0` или не заданы — уникализация выключена, сумма возвращается как есть.
{% endhint %}

### Пример

Мерчант отправляет:

```json
{ "amount": 5000, "amountUp": 100, "amountDown": 10 }
```

Если в системе уже есть активный ордер на 5000 RUB, ответ вернёт:

```json
{
    "payment_details": {
        "amount": "5001",
        ...
    }
}
```

Клиент должен оплатить именно `5001 RUB` — так система однозначно сопоставит входящий платёж с этим ордером.

***

## Платёжные методы

Полный список доступных методов — на отдельной странице: [Платёжные методы](/reference/payment-methods.md).

{% hint style="info" %}
Методы `card_pdf` и `sbp_pdf` требуют загрузки чека после оплаты — см. [Загрузка чека](/orders/receipt-upload.md).
{% endhint %}
