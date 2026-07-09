> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/orders/receipt-upload.md).

# Загрузка чека

> Метод: **POST**
>
> Путь: **/merchant/receipt/upload**
>
> Формат: **multipart/form-data**

Используется для методов [`card_pdf` и `sbp_pdf`](https://github.com/LuckyExchange/xpayconnect-backend/blob/main/docs/orders/payment-methods.md) — после того как клиент совершил оплату, необходимо прикрепить чек для подтверждения.

## Параметры запроса

| Поле        | Тип    | Описание                                                           |
| ----------- | ------ | ------------------------------------------------------------------ |
| **orderId** | string | `external_id` ордера на стороне мерчанта либо `internal_id` ордера |
| **receipt** | file   | PDF, JPEG или PNG, максимум 5 MB                                   |

## Пример запроса

```bash
curl -X POST https://api.xpayconnect.io/merchant/receipt/upload \
  -F "orderId=lux019d0c56-..." \
  -F "receipt=@/path/to/check.pdf"
```
