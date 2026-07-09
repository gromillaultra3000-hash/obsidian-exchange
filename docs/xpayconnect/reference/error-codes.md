> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/reference/error-codes.md).

# Коды ошибок

## Формат ответа

Все ошибки возвращаются в едином формате:

```json
{
    "ok": false,
    "status": 403,
    "message": "DISABLED"
}
```

| Поле        | Тип     | Описание                  |
| ----------- | ------- | ------------------------- |
| **ok**      | boolean | Всегда `false` для ошибок |
| **status**  | integer | HTTP-код ошибки           |
| **message** | string  | Код ошибки                |

***

## Общие ошибки

| HTTP | Код                   | Описание                                              |
| ---- | --------------------- | ----------------------------------------------------- |
| 400  | LIMITS\_ERROR         | Сумма не проходит по лимитам мерчанта                 |
| 400  | INVALID\_MERCHANT\_ID | Некорректный или отсутствующий идентификатор мерчанта |
| 401  | INVALID\_API\_KEY     | Недействительный API-ключ или неверная подпись        |
| 403  | DISABLED              | Мерчант или провайдер отключён                        |
| 429  | TOO\_MANY\_REQUESTS   | Превышен лимит запросов                               |
| 500  | Internal server error | Внутренняя ошибка сервера                             |

## Ошибки ордеров

| HTTP | Код                    | Описание                                     |
| ---- | ---------------------- | -------------------------------------------- |
| 404  | ORDER\_NOT\_FOUND      | Ордер не найден по указанному идентификатору |
| 409  | ORDER\_ALREADY\_EXISTS | Ордер с таким `order_id` уже существует      |
| 409  | REQUISITES\_NOT\_FOUND | Не удалось получить реквизиты для ордера     |

## Ошибки выплат

| HTTP | Код                      | Описание                                                            |
| ---- | ------------------------ | ------------------------------------------------------------------- |
| 400  | INVALID\_PAYOUT\_DETAILS | Некорректные данные выплаты (holderAccount, holderName, methodName) |
| 400  | INVALID\_HOLDER\_ACCOUNT | Неверный формат реквизита: 16 цифр для карты, 11 для СБП            |

{% hint style="info" %}
При ошибке `REQUISITES_NOT_FOUND` рекомендуется повторить запрос через 5–10 секунд — реквизиты могут стать доступны.
{% endhint %}
