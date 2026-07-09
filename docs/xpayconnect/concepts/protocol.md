> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/concepts/protocol.md).

# Описание протокола

## Базовый URL

Все запросы отправляются на:

```
https://api.xpayconnect.io
```

## Формат запросов

Запросы к API выполняются по протоколу HTTPS с использованием методов GET и POST.

### Обязательные заголовки

| Заголовок          | Описание                                                 |
| ------------------ | -------------------------------------------------------- |
| **Content-Type**   | `application/json`                                       |
| **client-api-key** | API-ключ мерчанта (выдаётся администратором)             |
| **x-api-key**      | SHA-256 подпись запроса ([подробнее](/concepts/auth.md)) |

### Тело запроса

* **POST-запросы** — данные передаются в формате JSON в теле запроса
* **GET-запросы** — параметры передаются в query-строке или в пути URL

***

## Формат ответов

Все ответы возвращаются в формате JSON. Успешные ответы содержат поле `ok: true`:

```json
{
    "ok": true,
    "id": "lux01993328-a828-7581-b3a9-e712a6a0e88c",
    "status": "pending"
}
```

Ошибки возвращаются с `ok: false` и HTTP-кодом ошибки:

```json
{
    "ok": false,
    "status": 400,
    "message": "LIMITS_ERROR"
}
```

{% hint style="info" %}
Полный список ошибок и их описания — в разделе [Ошибки](/reference/error-codes.md).
{% endhint %}
