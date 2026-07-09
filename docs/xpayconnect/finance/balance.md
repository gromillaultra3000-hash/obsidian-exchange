> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/finance/balance.md).

# Баланс

> Метод: **GET**
>
> Путь: **/merchant/balance/{merchant\_id}**

{% hint style="info" %}
Параметр `{merchant_id}` — уникальное имя мерчанта в системе XPayConnect.
{% endhint %}

#### Примеры запроса

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const axios = require('axios');

const apiKey = 'YOUR_API_KEY';
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|`).digest('hex');

const { data } = await axios.get('https://api.xpayconnect.io/merchant/balance/exMerchant', {
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

resp = requests.get('https://api.xpayconnect.io/merchant/balance/exMerchant', headers={
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

$ch = curl_init('https://api.xpayconnect.io/merchant/balance/exMerchant');
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
    "balance": 99999.99,
    "usdtBalance": 10000,
    "currency": "RUB",
    "allowUsdt": false
}
```

| Поле            | Тип          | Описание                                       |
| --------------- | ------------ | ---------------------------------------------- |
| **ok**          | boolean      | `true` при успешном запросе                    |
| **balance**     | number       | Текущий баланс мерчанта в основной валюте      |
| **usdtBalance** | number, null | Баланс в USDT (если подключена конвертация)    |
| **currency**    | string       | Валюта баланса (`RUB`, `KGS`, `KZT` или `UZS`) |
| **allowUsdt**   | boolean      | Разрешена ли конвертация в USDT для мерчанта   |
