> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/concepts/auth.md).

# Авторизация

Каждый запрос к API должен содержать подпись в заголовке **x-api-key**. Подпись формируется на основе API-ключа и тела запроса.

## Заголовки

| Заголовок          | Описание                                       |
| ------------------ | ---------------------------------------------- |
| **client-api-key** | API-ключ в открытом виде                       |
| **x-api-key**      | SHA-256 хеш строки `<API_KEY>\|<тело_запроса>` |

## Формирование подписи

1. Соедините API-ключ с телом запроса (JSON-строка), используя `|` как разделитель
2. Вычислите SHA-256 хеш полученной строки
3. Передайте результат в заголовке **x-api-key**

{% hint style="warning" %}
JSON-строка тела запроса не должна содержать пробелов. В Python используйте `json.dumps(body, separators=(',', ':'))`. В JavaScript `JSON.stringify()` по умолчанию не добавляет пробелов.
{% endhint %}

### Примеры для POST-запросов

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const crypto = require('crypto');
const apiKey = 'YOUR_API_KEY';
const body = { order_id: 'test-001', amount: 2300, type: 'sim', merchant_id: 'exMerchant' };

const bodyStr = JSON.stringify(body);
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|${bodyStr}`).digest('hex');

// Заголовки запроса:
// 'client-api-key': apiKey
// 'x-api-key': xApiKey
```

{% endtab %}

{% tab title="Python" %}

```python
import hashlib
import json

api_key = 'YOUR_API_KEY'
body = {'order_id': 'test-001', 'amount': 2300, 'type': 'sim', 'merchant_id': 'exMerchant'}

body_str = json.dumps(body, separators=(',', ':'))  # без пробелов!
x_api_key = hashlib.sha256(f'{api_key}|{body_str}'.encode()).hexdigest()
```

{% endtab %}

{% tab title="PHP" %}

```php
$apiKey = 'YOUR_API_KEY';
$body = ['order_id' => 'test-001', 'amount' => 2300, 'type' => 'sim', 'merchant_id' => 'exMerchant'];

$bodyStr = json_encode($body, JSON_UNESCAPED_UNICODE);
$xApiKey = hash('sha256', $apiKey . '|' . $bodyStr);
```

{% endtab %}
{% endtabs %}

### GET-запросы без тела

Для GET-запросов или запросов без тела используйте пустую строку вместо тела:

{% tabs %}
{% tab title="JavaScript" %}

```javascript
const xApiKey = crypto.createHash('sha256').update(`${apiKey}|`).digest('hex');
```

{% endtab %}

{% tab title="Python" %}

```python
x_api_key = hashlib.sha256(f'{api_key}|'.encode()).hexdigest()
```

{% endtab %}

{% tab title="PHP" %}

```php
$xApiKey = hash('sha256', $apiKey . '|');
```

{% endtab %}
{% endtabs %}
