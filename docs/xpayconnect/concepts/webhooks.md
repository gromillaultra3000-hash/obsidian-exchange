> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/concepts/webhooks.md).

# Вебхуки

После изменения статуса ордера на **success** система отправляет POST-запрос на URL, указанный в поле `success_callback_url` при создании ордера.

{% hint style="info" %}
Если `success_callback_url` не указан при создании ордера, вебхук отправлен не будет.
{% endhint %}

## Формат вебхука

Пример для фиатного метода с конвертацией в USDT (`convertToUsdt: true`):

```json
{
    "id": "lux01993328-a828-7581-b3a9-e712a6a0e88c",
    "order_id": "uE4wBDWPEN77F9FzXA1w8NbVSB",
    "type": "card",
    "amount": 2300,
    "currency": "RUB",
    "status": "success",
    "created_at": "2025-02-06 13:00:13.276",
    "amountAfterFee": 2001,
    "usdtAmount": 25.41,
    "usdtAmountAfterFee": 22.11,
    "exchangeRate": 90.5
}
```

| Поле                   | Тип               | Описание                                                                                                                                                                                                                                  |
| ---------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **id**                 | string            | Уникальный идентификатор в системе XPayConnect (internal\_id)                                                                                                                                                                             |
| **order\_id**          | string            | Идентификатор на стороне мерчанта (external\_id)                                                                                                                                                                                          |
| **type**               | string (enum)     | [Платёжный метод](/orders/create.md#platezhnye-metody)                                                                                                                                                                                    |
| **amount**             | integer           | Сумма платежа в валюте `currency` (брутто, до удержания комиссии мерчанта)                                                                                                                                                                |
| **currency**           | string (enum)     | Валюта ордера: `RUB`, `KGS`, `KZT`, `UZS`. Совпадает с валютой, указанной при создании ордера                                                                                                                                             |
| **status**             | string            | Всегда `success` (вебхуки отправляются только при успешной обработке ордера)                                                                                                                                                              |
| **created\_at**        | string (datetime) | Дата и время создания ордера                                                                                                                                                                                                              |
| **amountAfterFee**     | number, optional  | Сумма в фиатной валюте после удержания комиссии мерчанта — точное значение, зачисленное на баланс мерчанта при success. Может отсутствовать у legacy-ордеров, созданных до внедрения этого поля                                           |
| **usdtAmount**         | number, optional  | Сумма USDT **БЕЗ** учёта комиссии. Для фиатных методов = `amount / exchangeRate` (только при `convertToUsdt: true`). Для `usdt_trc20` = сумма из `cryptoAmount` (то, что заплатил клиент). Отсутствует, если ни одно условие не выполнено |
| **usdtAmountAfterFee** | number, optional  | Точная сумма в USDT, зачисленная на USDT-баланс мерчанта после удержания комиссии. Заполняется при `convertToUsdt: true` (фиатные методы)                                                                                                 |
| **exchangeRate**       | number, optional  | Зафиксированный курс USDT/`currency` (заполняется при `convertToUsdt: true` для фиатных методов; для `usdt_trc20` отсутствует)                                                                                                            |
| **cryptoAmount**       | string, optional  | Точная сумма в крипто-валюте, фактически заплаченная клиентом. Возвращается для крипто-методов (`usdt_trc20` и т.п.). Для фиатных методов отсутствует                                                                                     |

{% hint style="info" %}
Пример вебхука для крипто-метода (`usdt_trc20`, мерчант на фиатном балансе без `convertToUsdt`):

```json
{
    "id": "lux01993328-...",
    "order_id": "uE4wBDWPEN77F9FzXA1w8NbVSB",
    "type": "usdt_trc20",
    "amount": 5000,
    "currency": "RUB",
    "status": "success",
    "created_at": "2026-05-01 10:15:42.118",
    "amountAfterFee": 3900,
    "usdtAmount": 50,
    "cryptoAmount": "50.00000000"
}
```

Для `usdt_trc20` поле `usdtAmount` берётся из `cryptoAmount` (сумма уже в USDT). `exchangeRate` отсутствует. `usdtAmountAfterFee` отсутствует, если у мерчанта фиатный баланс — он получает фиат `amountAfterFee` за вычетом комиссии.
{% endhint %}

{% hint style="info" %}
Пример вебхука для `ton` (аналогично `usdt_trc20`, работает через LuckyExchange):

```json
{
    "id": "lux01993328-...",
    "order_id": "uE4wBDWPEN77F9FzXA1w8NbVSB",
    "type": "ton",
    "amount": 5000,
    "currency": "RUB",
    "status": "success",
    "created_at": "2026-05-01 10:15:42.118",
    "amountAfterFee": 4750,
    "usdtAmount": 50,
    "cryptoAmount": "50.00000000"
}
```

Для `ton` поле `usdtAmount` равно `cryptoAmount`, потому что оба измеряются в TON (название `usdtAmount` унаследовано от usdt-метода — численно для TON-ордера это TON-amount). `exchangeRate` отсутствует. `convertToUsdt: true` для метода `ton` не поддерживается — создание ордера будет отклонено, так как система не знает курс TON/USD.
{% endhint %}

***

## Подпись вебхука

Вебхук содержит заголовок **x-api-key** с SHA-256 хешем. Для верификации сформируйте подпись аналогично [авторизации запросов](/concepts/auth.md) и сравните с полученным значением.

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');

function verifyWebhook(body, receivedHash, apiKey) {
    const bodyStr = JSON.stringify(body);
    const expected = crypto.createHash('sha256').update(`${apiKey}|${bodyStr}`).digest('hex');
    return expected === receivedHash;
}
```

{% endtab %}

{% tab title="Python" %}

```python
import hashlib
import json

def verify_webhook(body: dict, received_hash: str, api_key: str) -> bool:
    body_str = json.dumps(body, separators=(',', ':'))
    expected = hashlib.sha256(f'{api_key}|{body_str}'.encode()).hexdigest()
    return expected == received_hash
```

{% endtab %}

{% tab title="PHP" %}

```php
function verifyWebhook(array $body, string $receivedHash, string $apiKey): bool {
    $bodyStr = json_encode($body, JSON_UNESCAPED_UNICODE);
    $expected = hash('sha256', $apiKey . '|' . $bodyStr);
    return hash_equals($expected, $receivedHash);
}
```

{% endtab %}
{% endtabs %}

***

## Ответ на вебхук

В ответ на вебхук сервер мерчанта должен вернуть HTTP **200**. При любом другом коде ответа система повторит доставку:

| Попытка | Задержка  |
| ------- | --------- |
| 1       | 15 секунд |
| 2       | 1 минута  |
| 3       | 5 минут   |
| 4       | 15 минут  |
| 5       | 1 час     |

{% hint style="warning" %}
После 5 неудачных попыток доставка прекращается. Используйте эндпоинт [Информация об ордере](/orders/info.md) для проверки статуса вручную.
{% endhint %}
