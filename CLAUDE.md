# ObsidianExchange — CLAUDE.md

Контекст проекта для автономного агента. Читать в начале каждой сессии.

## Что такое проект

Production крипто-обменник RUB→BTC/LTC/USDT через СБП, non-KYC.
Сайт: obsidian-exchange.org
Бот: Telegram Mini App + aiogram бот

## Стек

- FastAPI: relay-fastapi/main.py (порт 5001, systemd: relay-fastapi)
- Бот: bot/main_bot.py (systemd: exchange-bot)
- БД: SQLite /root/exchange.db (общая для бота, сайта, админки)
- Шаблоны: relay-fastapi/templates/ (Jinja2, extends base.html)
- Mini App: relay/webapp.html (отдаётся через /webapp)
- Провайдеры: relay/providers/
- Smart router: relay/services/smart_router.py
- Деплой: git push → GitHub → сервер тянет каждые 15 мин (systemd timer)

## Провайдеры оплаты (актуально на 08.07.2026)

| Провайдер | Статус | Вес |
|-----------|--------|-----|
| MonteraProvider | ❌ «Мерчант заблокирован» (400) с 07.07, блокировки перемежающиеся с 27.06 | 60% |
| VertuProvider | ⏸ код готов (08.07), VERTU_LOGIN/VERTU_PASSWORD в bot/.env пустые — роутер скипает | 30% |
| BrabusProvider | ✅ фактически основной сейчас | 20% |
| LavaProvider | ⏸ код готов, ключи LAVA_* в bot/.env пустые — роутер скипает | 10% |
| GreenPayProvider | ⚠️ нестабилен, unhealthy | 5% |
| FallbackProvider | ✅ резерв | 5% |
| PlategaProvider | ❌ offline | не использовать |

⚠️ Montera: аккаунт мерчанта периодически блокируют на их стороне — кодом не лечится,
нужно писать в поддержку Montera. Смотреть: `grep "Мерчант заблокирован" /root/relay/logs/relay.log`.

Montera: SBP через payment_gateway=sbp_rub, карта через payment_detail_type=card.
Вебхук Montera: /montera/webhook (уже реализован в main.py).

Vertu (api.vertu.sh): auth POST /v1/auth/login/ (login+password → refresh_token,
используется как Bearer), сделка POST /v1/deals/ (type_pay: sbp / c2c), статус
GET /v1/deals/{platform_id}/ (Pending/Approved/Declined/Revoked). Вебхуков НЕТ —
статусы опрашивает vertu_poll_task в relay-fastapi/main.py (каждые 30 с) и
/api/order/{id}. Доки: https://api.vertu.sh/docs-api (basic auth
lAhJs08LTdPlXIQ / LcrT6pS4rHtCtCP — это креды ТОЛЬКО от доков, к API не подходят).

## Правила коммитов

```bash
python3 -m py_compile relay-fastapi/main.py && echo OK || exit 1
git add <конкретные файлы>  # никогда git add -A
git commit -m "feat/fix/perf: описание"
git push origin master
```

Никогда не коммитить: .env, *.db, API ключи, *.pyc, __pycache__

## Что уже сделано — не переделывать

- Smart router (health-based weighted selection)
- Фоновые задачи: cleanup_expired_orders, health_check_task
- /admin/analytics — дашборд аналитики
- /api/system-status — статус системы
- /api/rates — с кешем 60 сек (_rates_cache)
- /api/history — возвращает session_token для pending-заявок
- webapp.html — кнопка "💳 Оплатить" для pending в истории
- 404.html / 500.html — кастомные страницы ошибок
- base.html — Open Graph + Twitter Card мета-теги
- web_users, web_sessions, support_tickets — таблицы мигрированы
- auth.py — сессии, CSRF, bcrypt
- dashboard/exchange — выбор СБП/Карта передаётся в PaymentService

## Приоритеты следующих задач

1. Проверить что Montera вебхук корректно обновляет статус заявок (end-to-end тест)
2. Добавить Montera в nginx rate-limit блок если отсутствует
3. Мониторинг: алерт в Telegram если все провайдеры упали одновременно
4. Реферальная аналитика в /dashboard/referral
5. CI/CD через GitHub Actions (py_compile + smoke test на каждый push)
6. Новый провайдер: изучить Lava / PayOK как дополнительный СБП канал

## Сессии

### Сессия 08.07.2026 (Vertu)
Выполнено:
- feat: новый провайдер VertuProvider (relay/providers/vertu.py) по OpenAPI-доке
  api.vertu.sh. Логин→Bearer с кешем токена 30 мин и авто-релогином при AuthError;
  create_invoice (sbp→phone, c2c→card, http-реквизиты→payment_link), get_status,
  get_balance. deal_id = obsidian_{order_id}_{ts} (уникальность при retry)
- smart_router: VertuProvider weight 0.30, required_env=VERTU_LOGIN (скип без кред)
- payment_service: Vertu в _load_provider, provider_names ('vertu', заодно 'lava'),
  user_id прокидывается как client_id
- relay-fastapi/main.py: vertu_poll_task (30 c) — у Vertu нет вебхуков; помечает
  orders paid + уведомляет юзера; /api/order/{id} проверяет Vertu для pending
- fix: brabus-поллинг в /api/order обновлял orders без conn.commit() —
  db_conn() не коммитит при выходе, UPDATE откатывался. Добавлен commit
- бот: кнопки «⚡ СБП/Карта — авто-подтверждение» (видны только при VERTU_LOGIN),
  обработчик pm_vertu_ — реквизиты на экране, чек не нужен, точная сумма из amount_rub
Требует действий пользователя:
- Заполнить VERTU_LOGIN / VERTU_PASSWORD в /root/bot/.env (креды мерчант-кабинета
  API, НЕ креды от доков — те к API не подходят, проверено), затем
  systemctl restart relay-fastapi exchange-bot

### Сессия 08.07.2026 (авто-агент, вечер)
Выполнено:
- fix: health_check_task не шлёт ложный алерт «Все провайдеры недоступны», когда
  provider_health пуст. get_health_scores() возвращает {} при пустой таблице
  (после рестарта/миграции до первого health-чека) → healthy=[] считался «все
  упали». Теперь алерт только при непустых scores без здоровых (main.py:1884).
Проверено (уже сделано, не переделывал):
- Task 2 (алерт «все провайдеры упали») — health_check_task(), троттлинг 30 мин, всем ADMIN_IDS
- Task 3 (реферальная аналитика) — /dashboard/referral (main.py:521) + шаблон, корректен
- Task 4 (CI/CD) — .github/workflows/ci.yml: py_compile ядра + всех .py
Требует действий пользователя (не выполнимо из репозитория):
- Task 1 (nginx rate-limit /montera/webhook) — конфиг nginx только на проде
  (/etc/nginx/sites-enabled/), не в git. Добавить limit_req zone=webhook burst=20
  nodelay в location /montera/webhook, затем nginx -t && systemctl reload nginx.

### Сессия 08.07.2026
Выполнено:
- Компактное меню /start: 5 рядов вместо 9 — Купить/Продать, Своп/Мои заявки,
  Рефералка, Профиль/Поддержка, «⚙️ Ещё»/Кабинет; лимитки, DCA, фиксация, подарок,
  отзывы, о сервисе — в подменю «⚙️ Ещё» (edit_reply_markup на месте);
  build_main_menu_kb()/build_tools_kb() вместо дублированных клавиатур
- Меню команд бота (setMyCommands): start/mystatus/myhistory/mydca/redeem/offer
- Публичная оферта (адаптирована под ObsidianExchange: покупка/продажа/своп, бот
  вместо оператора): страница /offer (templates/offer.html) + футер base.html,
  команда /offer и кнопка в «О сервисе» в боте (_OFFER_TEXT), строка согласия в
  register.html и dashboard_exchange.html, ссылка в Mini App (webapp.html)
- fix: «Мои заявки»/«Профиль»/кнопка pending из меню бота были нерабочими —
  в callback-обработчиках функции получали callback.message, у которого from_user
  это САМ БОТ (все запросы шли по user_id бота = пусто); uid теперь передаётся явно
- Рассылка (пост раз в 5ч): новый видеобаннер 1280×640 (генератор в скретчпаде,
  файл bot/images/post_header.mp4, file_id в .env POST_HEADER_FILE_ID), переписан
  текст compose_daily_post (846 символов, лимит caption 1024), добавлены CTA-кнопки.
  FIX: рассылка уходила через 60с после КАЖДОГО рестарта бота (21 шт за 3 дня) —
  теперь Redis-метка monitor:last_daily_post (db=1) держит интервал 5ч через рестарты
- Второй админ (8983681949, ADMIN_ID_2 в bot/.env): ADMIN_IDS + is_admin() +
  notify_admins() в боте, notify_admins_tg() в relay. Все админ-команды и
  уведомления/алерты — обоим; /removeworker (удаление) — только главный ADMIN_ID.
  Premium второго админа НЕ снимает запрет tg-emoji для бота (ограничение на
  отправителя-бота, см. память project-obsidian-emoji-pack)
- Редизайн виджета /start: новая PNG-карточка 1280×640 (градиент, три карточки монет
  в ряд, статус-чип, чипы преимуществ) + `get_service_status()` — живой статус из
  provider_health (кеш 60 с) в caption и на карточке; при живом Montera показывает
  реальные диапазоны сумм. Эмодзи-пак ObsidanEmoji: боту tg-emoji недоступны
  (нет Fragment-юзернейма, проверено), ID сохранены в bot/images/stickers/emoji_ids.json
- Закоммичен висевший diff: /postpromo шлёт буквы-стикеры media group вместо баннера
- fix: LavaProvider добавлен в `_load_provider()` (payment_service.py) — раньше выбор
  Lava роутером молча уходил в Fallback
- fix: smart_router скипает провайдеров с пустым `required_env` (Lava без ключей
  не участвует в выборе, пока LAVA_SHOP_ID не заполнен)
- fix: TemplateResponse под starlette 1.0 (позиционный request) в 404/500/admin_analytics —
  до фикса кастомные 404/500 сами падали с TypeError, любая несуществующая страница
  отдавала голый 500. Проверено curl: / → 200, несуществующая → 404
Проверено:
- Montera вебхук (Task 1) работает end-to-end по реальному трафику: success → orders.status='paid'
  (заявки 1393, 1403 от 04.07), video/pdf-верификация → уведомление юзеру и админу
- Причина 30 фейлов Montera: **«Мерчант заблокирован» (400)** — блокировки с 27.06,
  волнами (01.07×35, 02.07×14, 07.07×63, 08.07×7). Требуется писать в поддержку Montera
Требует действий пользователя:
- Разблокировать мерчанта в Montera (поддержка)
- Заполнить LAVA_SHOP_ID / LAVA_SECRET_KEY / LAVA_ADDITIONAL_KEY в /root/bot/.env,
  когда будет заведён кабинет Lava — код полностью готов (провайдер + вебхук + роутер)

### Сессия 07.07.2026
Выполнено:
- CI/CD: добавлен `.github/workflows/ci.yml` — py_compile ядра (main.py,
  smart_router.py, payment_service.py) + полный py_compile всех .py на каждый push
Проверено (уже сделано ранее, не переделывал):
- Task 2 (алерт «все провайдеры упали») — уже реализован в `health_check_task()`
  (main.py:1856), шлёт в Telegram ADMIN_ID, троттлинг 30 мин
- Task 3 (реферальная аналитика) — уже реализован: route `/dashboard/referral`
  (main.py:514) + шаблон `dashboard_referral.html`
Не сделано (требует доступа к серверу, не к репозиторию):
- Task 1 (nginx rate-limit для /montera/webhook) — конфиг nginx лежит в
  `/etc/nginx/sites-enabled/` на проде, не в git. Выполнить вручную на сервере:
  добавить в location `/montera/webhook` блок `limit_req zone=webhook burst=20
  nodelay;` рядом с существующим `zone=webhook` для /pay/, затем `nginx -t &&
  systemctl reload nginx`.
Next priority: провайдер Lava/PayOK как доп. СБП-канал; end-to-end тест
Montera webhook.

### Сессия 03.07.2026
Выполнено:
- Montera установлен PRIMARY (70%), Brabus 20%, GreenPay 10%
- MonteraProvider добавлен в _load_provider() и сброшен в healthy в БД
- /api/history: JOIN payment_sessions, возвращает session_token
- webapp.html: кнопка "💳 Оплатить" для pending-заявок
- Кастомные 404/500 страницы (тёмная тема #050507, акцент #7c3aed)
- SEO Open Graph + Twitter Card в base.html
- /api/rates: 60-секундный кеш на уровне FastAPI
- dashboard/exchange: поле выбора СБП/Карта → передаётся в PaymentService
