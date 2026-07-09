> For the complete documentation index, see [llms.txt](https://docs.xpayconnect.io/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://docs.xpayconnect.io/readme.md).

# XPayConnect API

**XPayConnect** — платформа для приёма платежей и выплат, поддерживающая множество платёжных методов: банковские карты, СБП, мобильные переводы, криптовалюта.

## Быстрый старт

{% stepper %}
{% step %}

### Получите API-ключ

Запросите `client-api-key` у администратора системы.
{% endstep %}

{% step %}

### Настройте авторизацию

Каждый запрос подписывается SHA-256 хешем. Подробнее в разделе [Авторизация](/concepts/auth.md).
{% endstep %}

{% step %}

### Создайте первый ордер

Отправьте POST-запрос на `/merchant/createOrder`. Подробнее в разделе [Создание ордера](/orders/create.md).
{% endstep %}
{% endstepper %}

## Базовый URL

```
https://api.xpayconnect.io
```

{% hint style="info" %}
Все запросы выполняются по HTTPS. HTTP-запросы не поддерживаются.
{% endhint %}

## Разделы документации

| Раздел                                      | Описание                             |
| ------------------------------------------- | ------------------------------------ |
| [Описание протокола](/concepts/protocol.md) | Формат запросов и ответов            |
| [Авторизация](/concepts/auth.md)            | Подпись запросов через SHA-256       |
| [Вебхуки](/concepts/webhooks.md)            | Получение уведомлений о статусах     |
| [Создание ордера](/orders/create.md)        | Приём платежей (PAYIN)               |
| [Создание выплаты](/orders/payout.md)       | Выплаты клиентам (PAYOUT)            |
| [Информация об ордере](/orders/info.md)     | Получение статуса ордера             |
| [Список ордеров](/orders/list.md)           | Фильтрация и пагинация               |
| [Пул реквизитов](/orders/requisite-pool.md) | Предварительное получение реквизитов |
| [Баланс](/finance/balance.md)               | Текущий баланс мерчанта              |
| [Ошибки](/reference/error-codes.md)         | Коды ошибок и их описания            |
