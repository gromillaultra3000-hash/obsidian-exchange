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

## Провайдеры оплаты (актуально на 09.07.2026)

| Провайдер | Статус | Вес |
|-----------|--------|-----|
| MonteraProvider | ✅ РАБОТАЕТ снова (проверено живьём 11.07 вечер): мерчант РАЗБЛОКИРОВАН — card 4500/5050 → Т-Банк/Сбербанк, sbp 7000/10000 → телефоны Альфа/Сбер. Отдаёт живой список лимитов трейдеров. «Подходящие реквизиты не найдены» на отд. суммах = просто нет трейдера ровно на сумму (не блок). Флаг здоровья сброшен (был is_healthy=0 с 09.07). Блокировки перемежающиеся с 27.06 — могут вернуться, health-система поймает | 60% |
| VertuProvider | ✅ РАБОТАЕТ (живой тест 13.07 вечер): SBP 5000→Т-Банк «Клиент 1», 10000→Сбер «Анди р» — настоящие реквизиты. Нет трейдера только на 2000/3000 и card(wt_c2c) в моменте. ⭐ 13.07 НАЙДЕН И ИСПРАВЛЕН баг «мы сами отключаемся» (16a4a23): основной путь create_session штрафовал health за «Не удалось выдать сделку» (= нет трейдера, НЕ сбой) → Vertu уходил в unhealthy → роутер выкидывал его целиком, хотя на 5000/10000 реквизиты есть. Теперь is_no_trader_error() (единый детектор, все провайдеры) не штрафует за нет-трейдера ни в осн. пути, ни в эскалации. Код сделки корректен (deal_id, реквизиты в ответе create). balance 0.0 pay-in НЕ блокирует. Снова в ротации (~27% на 5000) | 30% |
| BrabusProvider | ✅ фактически основной сейчас | 20% |
| LavaProvider | ⏸ код готов, ключи LAVA_* в bot/.env пустые — роутер скипает | 10% |
| GreenPayProvider | ⚠️ нестабилен, unhealthy | 5% |
| StormTradeProvider | ✅ активен (auth OK, API отвечает штатно 11.07). 11.07 исправлен self-heal deadlock: эскалация гейтилась по is_healthy=0, а провайдер получает живой запрос ТОЛЬКО через эскалацию → навсегда оставался unhealthy (весь резерв был отключён 10-11.07). Фикс 348184c: last-resort пытаемся всегда; «нет свободных реквизитов» больше не штрафует health. Флаг сброшен | last resort, вне weighted-выбора |
| FallbackProvider | ✅ резерв | 5% |
| PlategaProvider | ❌ offline | не использовать |
| XPayConnectProvider | ✅ ПРОД с 14.07.2026 (`obsidian_sng_mono`): реальные реквизиты живьём. ⚠️ НЕ карты РФ — мерчант СНГ («sng») отдаёт ПЛАТЁЖНУЮ ССЫЛКУ (payment_link, напр. payment.link-fast.io) на трансграничные рельсы (банки Душанбе-сити/Спитамен/Seabank). Реквизит=ссылка, /pay показывает QR+кнопку. Коды методов=банки (sber/tbank/alfa/…), фактически возвращают ссылки; sim/card/any→403. bot/.env: XPAY_TYPE_*=tbank, xpay УБРАН из DISABLED_PROVIDERS → в авто-роутере (~24% выбора, #2 по выгоде). Бот-кнопки XPAY_BUTTONS держатся OFF (пикер «Сбер/Т-Банк» не отражает ссылочный флоу — UX бот-кнопки требует решения юзера). Fail-closed страж тестовых реквизитов (6deb80c) на месте | авто-роутер, кнопки off |

StormTrade (docs.stormtrade.club): худшая ставка → НЕ участвует в обычном выборе
роутера (`last_resort: True`). Подключается только: 1) эскалация в
PaymentService._try_stormtrade(), когда выбранный провайдер не выдал реквизиты
(перед FallbackProvider); 2) эксклюзивные методы, которых нет у других — QR СБП
(SBP_QR), пополнение моб. (MOBILE_TOP_UP) — кнопки в боте pm_storm_* (видны при
заполненном STORMTRADE_API_KEY). ⚠️ TO_ACCOUNT (перевод по номеру счёта) УБРАН
08.07.2026 по требованию StormTrade («направлять только СБП/перевод на карту») —
НЕ возвращать; пустой/неизвестный payment_method маппится в SBP (не null,
иначе терминал сам выдаёт TO_ACCOUNT). API идентичен
Brabus (тот же white-label Merchant Integration API: X-Identity + X-Signature
HMAC-SHA1/Base64, POST /api/merchant/invoices со startDeal=true, deals[0].requisites,
вебхук X-Notification-Token → /stormtrade/webhook). Скачанная дока — в git:
docs/stormtrade/ (48 стр. с docs.stormtrade.club, PDF у юзера был только 1-й страницей).

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

XPayConnect (docs.xpayconnect.io, API api.xpayconnect.io): подпись каждого запроса —
заголовки client-api-key (ключ) + x-api-key (SHA-256 от `<KEY>|<тело без пробелов>`,
для GET тело пустое). Создание: POST /merchant/createOrder (type: sim=СБП, card=карта,
any=любой), реквизиты сразу в ответе (payment_details), финальная сумма может быть
СДВИНУТА уникализацией — платить ровно payment_details.amount (провайдер кладёт её в
raw.amount_rub). Статус: GET /merchant/order/{id}. Вебхук /xpay/webhook — только при
success, подпись x-api-key от сырого тела. Cancel-эндпоинта НЕТ. Ключи XPAY_* в
bot/.env. Кнопки в боте pm_xpay_* включаются переменной XPAY_BUTTONS=1 — НЕ включать,
пока XPay не активирует методы. Когда активируют: XPAY_BUTTONS=1, restart, и
`python3 -c "import sys;sys.path.insert(0,'/root/relay');from services.smart_router import reset_provider;reset_provider('XPayConnectProvider')"`.
Скачанная дока — в git: docs/xpayconnect/.

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

1. ✅ Montera вебхук — подтверждён живым трафиком (3× POST 200 OK 13-14.07)
2. ✅ Montera в nginx rate-limit — уже в regex вебхуков
3. ✅ Алерт «все провайдеры упали» — health_check_task
4. ✅ Реферальная аналитика /dashboard/referral
5. ✅ CI/CD GitHub Actions
6. Новый провайдер Lava (код готов, ждёт ключи юзера) / PayOK (изучить)
7. От юзера: SELL_USDT_ADDRESS (USDT-продажа скрыта), LAVA_* ключи,
   BACKUP_OFFSITE_RSYNC (опц.), решение по XPAY_TYPE_DEFAULT (сейчас tbank)

## Роли в боте

- **Админы** (ADMIN_ID, ADMIN_ID_2 в bot/.env) — всё; удаление воркеров/операторов — только главный.
- **Операторы** (таблица `operators` в exchange.db) — сотрудники обработки заявок и поддержки.
  Управление: /addoperator ID [username], /deloperator ID (только главный админ), /operators.
  Могут: /op (панель), /order ID (карточка заявки + payment_sessions для разбора с трейдерами
  провайдера), /pending, /tickets + /reply_ID, /finduser, /msg, подтверждать оплату
  (admin_confirm_ + /confirm КОД — админам приходит уведомление, действие пишется в admin_log).
  НЕ могут: /stats, /report, /broadcast, промокоды, курсы, блокировки, /force_payout,
  управление workers/operators. Уведомления (новая заявка, «я оплатил», чеки, тикеты)
  приходят через notify_staff() = админы + операторы.
- **Работники** (таблица `workers`) — только ручная отправка крипты (/worker, worker_send_).
- Support-бот (`/root/support_bot/support_bot.py`, systemd support-bot, НЕ в git до 09.07) —
  обращения пересылаются всем (админы + операторы из exchange.db, кеш 60 c), ответ — реплаем,
  маппинг в support.db (staff_messages).

## Сессии

### Сессия 14.07.2026 (жизненный цикл заявки до конца + Apple-минимализм, все поверхности)
Задача юзера: «формирование сделок не имеют законченной логики… улучшить UX в
минималистичном ключе, как передовой дизайнер Apple, в фирменном цвете». 4 фазы:
- **ab6c6ff /pay**: полный редизайн (карточка на #050507, #8b5cf6, hairline, без
  matrix-анимаций) + все состояния pending/verify(PDF/видео)/paid/sent/expired,
  рендер из cfg, поллинг /api/order 5с, таймер от expires_at. Нормализация
  реквизитов: дубль получатель==телефон/карта убран, банк-фолбэк «СБП»/«Карта».
- **3a77a42 Mini App**: /api/create_order нормализует реквизиты так же + payment_link
  (XPay) → QR и кнопка «Открыть страницу оплаты»; /api/order отдаёт verification —
  /pay и miniapp ловят запрос PDF/видео live; expired/failed скрывает реквизиты
  («не переводите»); поллинг живёт после локального таймера (оплата на флажке);
  авто-прыжок наружу только если внутри показать нечего.
- **4bb5f23 сайт**: легаси /pay/{order_id} (зелёная Arial-страница, QR из
  paid_btc_tx!) заменён — живая сессия → 302 на /pay/{token}, иначе честная
  статус-страница в фирменном стиле. История заявок: «💳 Оплатить» (pending),
  «🔍 Транзакция» (sent), человекочитаемые статусы; fix: get_user_orders не
  выбирал crypto_address → «Повторить» терял адрес.
- **efb1ff3 бот**: format_requisites — та же нормализация (+дедуп bank/bank_name,
  recipient/holder_name); cleanup_expired_orders шлёт клиенту одноразовое
  уведомление об истечении с кнопкой «Создать новую» (sent_notifications
  event='order_expired').
Проверено живьём: py_compile, node --check JS обеих страниц, test_routes 66 роутов,
редирект digit→token (302), expired-страница, format_requisites 3 кейса. Сервисы
перезапущены. Бот: @Obsidian666999bot.

### Сессия 13.07.2026 (reliability-скоринг + слой доверия к оплате + страж XPay + VPN)
Продолжение переноса паттернов Lumi в обменник + две задачи от юзера.
- **VPN (Xray Reality)**: жалоба «нет интернета». Диагностика — сервер 100% исправен
  (user4 живьём гонял трафик без ошибок, пара ключей совпадает, порт/UFW/сеть ок).
  Причина клиентская: в ссылке терялся `flow=xtls-rprx-vision` (Vision) → хендшейк
  проходит, данные рвутся. Пересобрал корректные vless-ссылки всем 4 юзерам + QR.
  Заработало. Ключи/pbk/sid — в памяти [[project-vpn-xray-reality]].
- **feat(trust) 7ae05ee — reliability-скоринг + публичный слой доверия** (уникальная
  фишка, выбор юзера — публичный агрегат). Движок smart_router: reliability_score =
  0.55·здоровье + 0.25·скользящий success-rate(1ч) + 0.20·латентность (адаптация Lumi
  provider_intelligence). Раньше выбор игнорировал avg_response_time, здоровье бинарное
  с амнезией → мигающий/медленный провайдер = «идеально здоров». provider_attempts.success
  добавлен для success-rate (нет данных → нейтрально). choose_provider взвешивает по
  reliability. get_trust_metrics() — OPSEC-безопасный агрегат БЕЗ имён провайдеров:
  число живых маршрутов, ~время до реквизитов, надёжность выдачи P=1-Π(1-rel_i) с полом
  90%. Поверхности (общий источник): /api/system-status (блок trust); mini app
  webapp.html + сайт index.html — виджет «⚡ Умный роутинг оплаты»; бот — строка в /start
  caption + reliability в /providers (админ). Проверено живьём: 3 маршрута, ~1с, 99%.
- **feat(xpay) 6deb80c — вывод XPay из песочницы**: доки (docs.xpayconnect.io) + живой
  тест → у XPay ОДИН base URL, НЕТ параметра окружения, «выход из песочницы» = действие
  мерчанта на стороне XPay. Мерчант Obsidian всё ещё в песочнице (sbp/card → 0000…,
  «Test Name», Альфа). Добавлен fail-closed страж тестовых реквизитов (см. таблицу
  провайдеров). Активация в прод после подтверждения XPay: XPAY_BUTTONS=1 + убрать xpay
  из DISABLED_PROVIDERS + restart relay-fastapi exchange-bot + reset_provider('XPayConnectProvider').
- **feat(payout) 41483e9 — fail-closed гейт выплаты**: `relay/services/payout_guard.py`
  verify_payment_settled() перепроверяет оплату у провайдера (get_status) в МОМЕНТ
  выплаты, не доверяя одному флагу status='paid'. auto_check_payments перестроен вокруг
  вердикта confirmed/hold/manual. СТРОГО (выбор юзера): крипта авто-уходит ТОЛЬКО по
  live-paid провайдера; hold при незакрытой verification_requested трейдера (Montera
  видео/PDF); всё сомнительное (unknown/ручное подтверждение/Fallback) → к работнику.
  ⚠️ Побочно: /confirm оператора больше НЕ авто-платит ≤5000 — уходит к работнику.
  Клиентские действия (я оплатил/PDF/видео) статус не ставили и раньше. Детали в памяти
  project-obsidian-exchange-status.
- **feat(xpay) 091787a — новый мерчант obsidian_sng_mono + bank-picker**: юзер дал новые
  креды XPay. Живьём: auth OK, но реквизиты ещё тестовые (мерчант в песочнице XPay).
  Методы сменились на ПОБАНКОВЫЕ переводы (sber/tbank/alfa/vtb/yumoney/gasprom/uralsib/
  mts — «строго между клиентами банка», реквизит=карта). sim/card теперь 403. Провайдер:
  XPAY_BANKS + приём кода банка как type. Бот: пикер банков (выбор клиентом — выбор юзера).
  Кнопки off до подтверждения прода XPay. Активация: XPAY_BUTTONS=1 + убрать xpay из
  DISABLED_PROVIDERS + restart + reset_provider('XPayConnectProvider').
- **fix(router) 16a4a23 — «мы сами отключаемся от Vertu»**: жалоба юзера (Vertu пишет
  «реквизиты есть», а мы отваливаемся). Живой тест: Vertu РЕАЛЬНО выдаёт SBP (5000→
  Т-Банк, 10000→Сбер), нет трейдера лишь на 2000/3000/card. Баг: основной путь
  create_session штрафовал health за «Не удалось выдать сделку» (нет трейдера, API
  ответил штатно) → Vertu unhealthy → роутер его выкидывал. Фикс общий для ВСЕХ:
  smart_router.is_no_trader_error() (единый детектор, паттерны расширены), оба пути
  payment_service не штрафуют health за нет-трейдера (реальные auth/сеть/5xx/блок —
  штрафуют). Осн. путь при no_trader сразу эскалирует. Vertu health сброшен, снова
  в ротации. Проверено: no-trader×6 не роняет, сбой×6 роняет.

### Сессия 12.07.2026 (Lumi: сервис + provider intelligence в роутере + мост в Kairos)
Развёрнут Lumi v1.7.0 (/root/lumi, systemd `lumi`, 127.0.0.1:8010, 203 теста зелёные) —
третий проект от того же знакомого: fail-closed ИИ-ассистент по коду. Его паттерны
интегрированы в обменник (9b088cf), работает на всех поверхностях, т.к. внутри
smart_router/PaymentService (бот + сайт + mini app — один путь create_session):
- **Статусы+blocker**: provider_health получил колонки status
  (READY/NO_TRADERS/BLOCKED/AUTH_ERROR/NETWORK/DEGRADED) + blocker (человекочитаемая
  причина, напр. «Мерчант заблокирован — писать в поддержку»). classify_error() в
  smart_router; на подсчёт здоровья НЕ влияет, только видимость. Миграция идемпотентна.
- **Probation self-heal**: unhealthy-провайдер с истёкшим cooldown получает редкий
  пробный запрос (вес ×0.05) — закрыт deadlock «weighted-провайдер unhealthy навсегда»
  (Brabus утром 12.07 завис так на 3 разовых сетевых фейлах; сброшен).
- **Kill-switch DISABLED_PROVIDERS** (bot/.env: platega,greenpay,xpay) — полное
  исключение из выбора/probation/эскалации. ⚠️ Критично для XPay-песочницы: раньше её
  держал вне ротации только ручной is_healthy=0, который снялся бы первым же «успешным»
  create_invoice с фейковыми реквизитами. Когда XPay переключат на прод — убрать xpay
  из DISABLED_PROVIDERS (+XPAY_BUTTONS=1).
- **Бюджет-лимиты** BUDGET_<SHORT>=N (попыток/час, журнал provider_attempts, чистка 2ч),
  по умолчанию выключены.
- **ESCALATION_CHAIN** (default stormtrade,fallback) — эскалация обобщена
  (_try_stormtrade → _escalate), поведение по умолчанию идентично прежнему;
  «нет реквизитов» не штрафует health ни для кого в цепочке.
- Поверхности: бот — команда /providers (статусы+причины, кнопки ♻️ сброс с аудитом
  в admin_log, 🔄 обновить; админы); admin analytics — status/blocker в providers
  (+fix легаси-500: ps.session_id → ps.id, эндпоинт /admin/analytics/data был сломан);
  mini app — статус-чип из /api/system-status (webapp.html).
- Проверено: py_compile, tests/test_routes.py (66 роутов), симуляция 300/2000 прогонов
  (kill-switch исключает, probation ~5%, бюджет отсекает), сервисы перезапущены, живой
  /api/system-status operational.
KAIROS: комитет получил Lumi-«мозг» (advisory, fail-closed) — голоса → POST
/conflict/resolve → combinedVerdict. LUMI_URL в kairos.service (НЕ в .env — его
переписывает _sync_env). Детали в памяти project-kairos / project-lumi.

### Сессия 11.07.2026 (вечер-2 — живой прогон ВСЕХ провайдеров + фиксы)
После рестарта relay-fastapi (код-фикс StormTrade загружен, healthy при старте:
Brabus/Fallback/StormTrade) прогнал живой create_invoice по всем провайдерам
(5000 ₽) и разобрал маппинг кнопок бота. Результаты:
- **Brabus** ✅ выдаёт по ВСЕМ методам (card/sbp/tbank/alfa/vietqr) — реальные
  карты 9762…, живые имена. Фактический рабочий провайдер + он же FallbackProvider
  (=BrabusProvider variant tbank_deeplink).
- **Montera** ✅ РАЗБЛОКИРОВАН (был «Мерчант заблокирован» с 07.07!): card 4500→
  Т-Банк, 5050→Сбер, sbp 7000→Альфа, 10000→Сбер. Отдаёт живой список лимитов
  трейдеров. Флаг здоровья сброшен (reset_provider). ⭐ ключевое открытие сессии.
- **Vertu** ⚠️ интермиттентно (сейчас 400 на 5000; ранее 4000/5000 выдавали).
- **StormTrade** ⚠️ жив (auth OK), но «нет свободных реквизитов» под все суммы в
  моменте — трейдеров нет (last-resort).
- **XPayConnect** ⚠️ методы включили, но ПЕСОЧНИЦА: реквизиты `0000…`, «Test Name»
  — платить нельзя, кнопки держать off.
- GreenPay/Lava/Platega ❌ (unhealthy/нет ключей/offline).
Цепочка эскалации в create_session: выбранный провайдер (3 попытки) → StormTrade
→ FallbackProvider(=Brabus). Т.е. ЛЮБАЯ кнопка при неудаче падает на Brabus, юзер
всегда получает реквизиты, пока жив хоть один из {выбранный, StormTrade, Brabus}.
Маппинг кнопок бота → форсируемый провайдер (build_payment_methods_kb, стр.459;
process_payment_method, стр.2530):
- «📱 СБП — по номеру телефона» pm_montera_sbp → Montera sbp (видна при ≥1 успехе)
- «💳 Карта — реквизиты на экране» pm_gp_card → **Montera** card (префикс gp —
  ЛЕГАСИ GreenPay, но роутится в MonteraProvider, стр.2671; ≥1 успех)
- «⚡ СБП/Карта — авто-подтверждение» pm_vertu_sbp/card → Vertu (при VERTU_LOGIN)
- «📷 QR-код (Сбер/ВТБ)» pm_brabus_vietqr → Brabus vietqr (сумма ≥1000)
- «🔳 QR СБП» pm_storm_sbpqr → StormTrade sbp_qr (при STORMTRADE_API_KEY)
- «🚀 …мгновенное» pm_xpay_* → XPay (скрыто, XPAY_BUTTONS!=1)
- «🌋 Все банки (Lava)» pm_lava → Lava (скрыто, нет LAVA_SHOP_ID)
Фиксы этой сессии:
- fix(b39ff3a) montera.py: create_invoice приводит user_id к int в начале —
  строковый user_id (initData/JSON) валил TypeError «'<' not supported str/int»
  на user_id>0 (стр.76) и user_id<0 в _get_user_rating. В проде telegram_id int
  (не стреляло), но путь хрупкий — захардили.
- (из vertu-сессии ранее) fix(348184c) StormTrade self-heal deadlock — см. ниже.

### Сессия 11.07.2026 (вечер — живая диагностика Vertu/StormTrade)
Продолжение диагностики. Логи relay: order 1493 (07:04) ещё ловил 422 (фикс
deal_id не был подтянут деплой-таймером), order 1501 (21:27) — уже 400 с
правильным deal_id (фикс задеплоился). Живая проверка провайдеров через
providers.* (venv /root/bot/venv):
- **Vertu**: РАБОТАЕТ интермиттентно, код корректен. sbp 4000/5000 ₽ создали
  сделки с ПОЛНЫМИ реквизитами прямо в ответе create (phone 795…, bank ВТБ,
  full_name «клиент 1», status Pending) — get_status подтвердил. sbp 6000+/10000/
  c2c → 400 «Не удалось выдать сделку». Вывод: 400 = НЕТ свободного трейдера под
  сумму в моменте (не порог, не код). balance 0.0 pay-in не блокирует. Кодом не
  лечится. ⚠️ создано 3 живых Pending-теста (0084-…1783808485/…538/…539) — у Vertu
  нет cancel-эндпоинта, истекут сами.
- **StormTrade**: auth OK, API отвечает штатно, но «нет свободных реквизитов» под
  все суммы/методы в моменте (last-resort, трейдеров мало). НЕ сломан.
- **НАЙДЕН И ИСПРАВЛЕН БАГ (348184c)**: self-heal deadlock эскалации StormTrade.
  Провайдер last_resort (вне weighted-выбора) → живой запрос только через
  _try_stormtrade, а та гейтила по is_healthy=0 → раз unhealthy = навсегда
  unhealthy (весь резерв отключён 10-11.07, «эскалация пропущена: unhealthy» в
  логах). Плюс штатное «нет реквизитов» писалось как health-failure и само
  загоняло в флаг. Фикс: убран гейт по is_healthy (last-resort пытаемся всегда,
  исход пишет сам вызов); «нет свободных реквизитов» больше не штрафует health
  (только auth/сеть/5xx). Флаг StormTrade сброшен (reset_provider) → эскалация
  восстановлена немедленно (running-процесс читает is_healthy из БД свежим).
  py_compile OK, закоммичено+запушено.
- Brabus (фактический основной) healthy, 0 fails; Read timeout в 21:27 — разовый
  сетевой сбой, cancel HTTP 400 на tbank_deeplink — норма (нельзя отменить
  истёкший инвойс).

### Сессия 11.07.2026 (регрессия Vertu deal_id → 422)
Продолжение висевшего незакоммиченного диффа vertu.py. Проверка живым API
(api.vertu.sh, balance 200 OK) выявила: коммит 7743de9 переименовал в payload
создания сделки `deal_id` → `platform_id`, из-за чего POST /v1/deals/ отвечал
**HTTP 422 «deal_id: Field required»** — ВСЕ сделки Vertu ломались с 10.07 ещё
до подбора трейдера. Проба:
- `platform_id`-only → 422 (deal_id required)
- `deal_id`-only → 400 «Не удалось выдать сделку» (доходит до подбора)
- оба ключа → 400 (platform_id в запросе игнорируется)
Фикс 59e8a8c: вернул `deal_id` (без лишнего platform_id — Vertu отдаёт свой
platform_id для GET-статуса в ОТВЕТЕ). Остаточный 400 — провайдерская сторона
(нет трейдеров/баланс 0), не код → писать в поддержку Vertu. Закоммичено+запушено.

### Сессия 10.07.2026 (miniapp-заявки, безопасность, UX, ретеншн)
Главный баг: Mini App висел на «заявка создаётся…» — открывался url-кнопкой, а не
web_app → tg.initData пуст, tg.sendData() молча не работал. Выполнено (5 коммитов):
- fix(069cfae): создание заявки через **POST /api/create_order** (auth по подписи
  initData, helper verify_init_data), кнопка «Личный кабинет» в главном меню →
  web_app=WebAppInfo. tg.sendData НЕ использовать (см. [[project-miniapp-order-flow]]).
- feat/security(d2d6ad0): in-app трекинг оплаты (таймер 15 мин, поллинг статуса,
  haptic); rate-limit /api/create_order (5/10мин на юзера + 60/мин глобально →429);
  144 файла main_bot*-бэкапов → backups/bot_legacy_20260710, паттерны в .gitignore.
- security(dffb829): закрыт **IDOR на /api/order/{id}** — статус/txid только
  владельцу (initData ИЛИ ?token=session_token), иначе 404; идемпотентность заявок
  (повтор те же параметры за 90с → та же заявка); session_token в логах усечён,
  адрес в bot.log маскируется.
- feat(9c7ec38): **QR СБП прямо в Mini App** (create_order отдаёт qr_image data-URI
  из qr_payload + pay_amount); explorer-ссылка на txid при sent; /api/stats/public
  обогащён (exchanges_total, volume_24h/total) → trust-strip на вкладке обмена.
- feat(f935243): explorer_url() в боте — кнопка «🔍 Транзакция в блокчейне» в
  уведомлениях о выплате (worker_send + force_payout); /api/history отдаёт txid;
  история в miniapp: pending открывает оплату внутри Telegram, sent → explorer.
- infra (НЕ в git, прод /etc/nginx): в regex вебхуков добавлены lava|stormtrade|xpay
  (были без rate-limit, падали в location / ). Бэкап:
  /root/backups/nginx_obsidian-exchange.org.bak_20260710. Проверено: 429 после burst.
- feat(bf09260): abandoned_order_reminder() — одноразовое напоминание о неоплаченной
  заявке (окно 8-13 мин), кнопка «Оплатить». Гарантия однократности через
  sent_notifications(event='pay_reminder').
- test(d5f0918): tests/test_routes.py — контракт-тест (критичные роуты + маппинг
  fetch() webapp), подключён в CI. Ловит «фронт дёргает несуществующий роут».
- feat(f8943e3): курируемые резервы — таблица reserves, бот /setreserve CUR AMOUNT
  и /reserves (админ), GET /api/reserves (+RUB-эквивалент), блок «🏦 Резервы» в
  miniapp (скрыт пока пусто). НЕ сырой баланс — задаётся вручную (OPSEC).
- security(c502de4): РЕВЬЮ диффа нашло IDOR — /api/history и /api/referral_stats
  брали user_id из query без auth (утечка чужой истории + session_token = обход
  IDOR-фикса /api/order). Теперь требуют подписанный initData, id из подписи.
- fix mobile(52c909a): широкие .dash-table скроллятся внутри себя ≤720px (viewport
  наследуется из base.html везде, body overflow-x:hidden, инпуты 16px — ост. в норме).
- security+fix бот(aa53f4b): РЕГРЕССИЯ — IDOR-фикс /api/order сломал колбэк check_
  (бот зовёт ?key=RELAY_SECRET) → восстановлен server-to-server ключ (compare_digest
  со SECRET_KEY, грузится из bot/.env). Проверка владения в inline_paid/inline_check
  (только владелец/админ). Глобальный @dp.errors() — нет «молчаливых» сбоев.
  Аудит авторизации колбэков: admin_confirm_(is_staff+2FA), worker_send_(is_worker),
  cancel_order_(владение) — уже были ОК.
UX-полировка бота/miniapp (db86da2, fdaa654, ca54dd4, dffa6dd):
- Menu Button у поля ввода → Mini App одним тапом (set_chat_menu_button MenuButtonWebApp)
- живой курс на кнопках выбора монеты (build_currency_kb, покупка+продажа)
- пресеты суммы 5к/10к/25к/50к на вводе RUB (_finalize_rub_amount, amtpreset_)
- реф-аналитика в miniapp: /api/referral_stats + active/bonus_rub/bonus_percent,
  стат-грид; withdrawRefBonus больше не через сломанный tg.sendData (шлёт в бота)
- РЕШЕНО НЕ делать in-place swap выбора монеты: menu_exchange — общая точка входа
  из 8+ сообщений (уведомления, завершение заявки, тарифы), edit_reply_markup
  испортил бы их клавиатуры. Паттерн «новое сообщение» здесь правильный.
Требует юзера: 1) протестировать miniapp-флоу в реальном Telegram (меню → Личный
кабинет → создать заявку → QR/трекинг); 2) задать резервы: /setreserve BTC 1.5
(иначе блок резервов скрыт).

### Сессия 09.07.2026 (роль «оператор»)
Выполнено:
- feat: роль оператора в main_bot.py — см. раздел «Роли в боте» выше. Таблица operators
  создаётся в init_db(). Аудит действий — в существующий admin_log (log_staff_action).
- support_bot/support_bot.py: мультисотрудниковый режим (было: только один ADMIN_ID),
  ADMIN_ID_2 добавлен в /root/support_bot/.env, медиа от клиентов теперь тоже пересылаются.
- fix: /reply_N без текста уводил админа в состояние создания тикета — следующее сообщение
  создавало НОВЫЙ тикет вместо ответа клиенту. Теперь ticket_enter_message проверяет
  admin_reply_tid.
- fix: кнопка «✉️ Написать клиенту» (admin_msg_) была нерабочей (ставила state-data без
  состояния) — теперь подсказывает команду /msg ID.
- ⚠️ bot/support_bot.py — легаси, сервисом НЕ используется; живой support-бот в /root/support_bot/.

### Сессия 09.07.2026 (кастом-эмодзи через юзербот)
Выполнено:
- feat: bot/emoji_userbot.py (Telethon 1.44 в bot/venv) — премиум-аккаунт
  редактирует посты бота в CHANNEL_ID и накладывает custom_emoji entities поверх
  fallback-строки 🔮💜💎⚡🌑⚡🟣✨💫 (O B S I D I A N EX из emoji_ids.json),
  текст и bold/blockquote сохраняются. Команды: login / edit <id> / watch.
  Оффсеты UTF-16 проверены юнит-тестом. systemd emoji-userbot.service создан,
  НЕ включён (нужен login)
- _PROMO_POST_HTML: первой строкой бренд-строка фолбэков (шапка для наложения)
Требует действий пользователя:
- my.telegram.org с ПРЕМИУМ-аккаунта (второй админ) → API development tools →
  TG_API_ID/TG_API_HASH в bot/.env; премиум-аккаунт должен быть админом канала
  с правом редактирования сообщений
- `! /root/bot/venv/bin/python3 /root/bot/emoji_userbot.py login` (телефон+код),
  затем `systemctl enable --now emoji-userbot`
- Проверка: /postpromo в канал → юзербот в течение секунды заменит шапку на
  анимированные буквы. Разово: emoji_userbot.py edit <msg_id>

### Сессия 09.07.2026 (новый провайдер XPayConnect)
Выполнено:
- feat: провайдер XPayConnectProvider (relay/providers/xpayconnect.py) по доке
  docs.xpayconnect.io (скачана в docs/xpayconnect/, 14 стр.). Подпись SHA-256
  `<KEY>|<тело>`; тело отправляется ровно той же компактной JSON-строкой, что
  подписана (data=, не json= — иначе подпись не совпадёт). order_id с timestamp
  (retry не ловит 409 ORDER_ALREADY_EXISTS). Финальная сумма после уникализации
  берётся из payment_details.amount → raw.amount_rub
- smart_router: weight 0.40, required_env XPAY_API_KEY
- payment_service: _load_provider, provider='xpay', user_id→client_id
- relay-fastapi/main.py: вебхук POST /xpay/webhook (подпись x-api-key от сырого
  тела, приходит только при success) — orders paid + уведомление юзеру.
  Проверено curl: неподписанный запрос → 401
- бот: кнопки «🚀 СБП/Карта — мгновенное подтверждение» (pm_xpay_*) — спрятаны
  за XPAY_BUTTONS=1 (см. ниже почему)
- Ключи в bot/.env: XPAY_API_KEY, XPAY_MERCHANT_ID=Obsidian. Сервисы перезапущены
- Мок-тесты: парсинг sim/card/nspk, ошибки, parse_webhook, подпись, роутер (300
  прогонов выбирает XPay) — всё ОК
Живой тест: auth работает (balance 200: 0.00 RUB, payoutEnabled=false), но
createOrder на sim/card/any → 403 «Payment type … is not allowed for this
merchant», allowed=[] — у мерчанта не включён НИ ОДИН метод. Провайдер помечен
unhealthy вручную (роутер скипает; авто-восстановится при первом успехе).
Действие юзера: написать администратору XPayConnect — включить методы sim/card
мерчанту Obsidian. После включения: XPAY_BUTTONS=1 в bot/.env,
systemctl restart relay-fastapi exchange-bot, reset_provider('XPayConnectProvider').

### Сессия 08.07.2026 (ночь — разбор Vertu «Не удалось выдать сделку»)
Полная диагностика, код НЕ виноват:
- auth OK (balance → 200, 0.0), payload сверен с OpenAPI api.vertu.sh
  (required: amount/deal_id/type_pay — всё отправляем корректно)
- суммы 100/500/1000/2000/3000/5000/7000/15000/50000/100000 ₽ на wt_sbp — все 400
- ГЛАВНОЕ: заведомо фейковый type_pay (totally_bogus_xyz) и все варианты
  (sbp/c2c/nspk/tpay/sbp_qr/wt_*) дают ОДИНАКОВУЮ ошибку «Не удалось выдать
  сделку» → это generic catch-all на 400, по ответу невозможно отличить
  «нет трейдеров» / «неверный код метода» / «мерчант ограничен»
- в спеке всего 8 эндпоинтов, ничего для диагностики (нет списка методов/лимитов)
- днём 08.07 тот же payload wt_sbp создал сделку 0084-… → на нашей стороне
  ничего не менялось, состояние поменялось у Vertu (кончились трейдеры или
  мерчанта ограничили; баланс 0 — возможно нужен депозит)
Действие ТОЛЬКО у юзера: написать в поддержку Vertu, спросить: 1) почему все
сделки отдают «Не удалось выдать сделку» с вечера 08.07; 2) нужен ли депозит
на балансе для выдачи pay-in; 3) актуальные коды type_pay для мерчанта;
4) висит ли незакрытая дневная тест-сделка 0084-… и мешает ли она.

### Сессия 08.07.2026 (тест StormTrade/Vertu, статистика провайдеров)
- StormTrade ✅: тестовые сделки SBP (телефон тест-трейдера + sberbank-link) и
  SBP_QR (реальный qr.nspk.ru) созданы и отменены через cancel_order. Эскалация
  в проде уже срабатывает: заявка 1463 (19:31) — Montera «Мерчант заблокирован»
  → StormTrade выдал реквизиты.
- Vertu ❌: VERTU_API_KEY как Bearer работает (get_balance → 0.0, не AuthError),
  но POST /v1/deals/ отдаёт «Не удалось выдать сделку» на wt_sbp/wt_c2c при
  3000/5000/10000 ₽. Днём wt_sbp работал → похоже, кончились трейдеры или нужен
  депозит (баланс 0). Действие юзера: написать в поддержку Vertu.
- Статистика payment_sessions за 7 дней: fallback 66 (2 paid), montera 28
  (3 paid, мёртв с 07.07), brabus+deeplink+vietqr 12 (2 paid), stormtrade 2.
  Healthy: Brabus, StormTrade, Fallback. Рабочая цепочка сейчас:
  Brabus → эскалация StormTrade → Fallback.

### Сессия 08.07.2026 (StormTrade — убран TO_ACCOUNT)
StormTrade написал: «Направляете перевод по номеру счёта. Нужно СБП/перевод на
карту». Выполнено:
- бот: удалена кнопка «🏦 Перевод по номеру счёта» и pm_storm_account_ из
  STORM_METHOD_BY_PM (старые кнопки → «временно недоступен»)
- stormtrade.py: account убран из METHOD_TO_OPTION/EXCLUSIVE_METHODS;
  пустой/неизвестный payment_method → paymentOption "SBP" (раньше null =
  «любые реквизиты», терминал мог выдать TO_ACCOUNT при эскалации)
- В логах реальных TO_ACCOUNT-сделок не было (только наш тест sttest…,
  без deals). Сервисы перезапущены, закоммичено (ef4ba92).

### Сессия 08.07.2026 (StormTrade)
Выполнено:
- feat: провайдер StormTradeProvider (relay/providers/stormtrade.py) — последний
  резерв с худшей ставкой. API оказался идентичен Brabus (white-label Merchant
  Integration API), провайдер по его образцу. Дока скачана с docs.stormtrade.club
  (PDF юзера содержал только 1-ю страницу) → docs/stormtrade/ (45 стр.)
- smart_router: StormTradeProvider с `last_resort: True` — исключён из
  weighted-выбора choose_provider (проверено на 300 прогонах), required_env
  STORMTRADE_API_KEY
- payment_service: _try_stormtrade() — эскалация ПЕРЕД FallbackProvider, когда
  выбранный провайдер после 3 ретраев не выдал реквизиты; скипается если ключей
  нет / unhealthy / упал сам StormTrade; provider='stormtrade' в payment_sessions.
  Работает для всех путей (бот + /dashboard/exchange), т.к. внутри create_session
- relay-fastapi/main.py: вебхук POST /stormtrade/webhook (X-Notification-Token,
  {"notificationType":"invoice"}) — orders.status='paid' + уведомление юзеру
- бот: кнопки эксклюзивных методов «🔳 QR СБП» (SBP_QR) и «🏦 Перевод по номеру
  счёта» (TO_ACCOUNT) — видны только при STORMTRADE_API_KEY; обработчик pm_storm_*
  (поддерживает также mobile/sbp/card на будущее); format_requisites понимает 'account'.
  По СБП/карте StormTrade в меню НЕ показывается — только автоэскалация
- Проверено на моках: подпись HMAC-SHA1/Base64, парсинг SBP_QR (payment_link из
  qr.nspk.ru) и TO_ACCOUNT, пустые deals → «нет реквизитов», parse_webhook,
  все 4 ветки эскалации
Ключи получены от юзера в той же сессии и заполнены в /root/bot/.env
(STORMTRADE_API_KEY/SECRET; NOTIFICATION_TOKEN сгенерирован openssl). API-домен —
api.stormtrade.club (ЛК: app.stormtrade.club). Живой тест: SBP_QR выдал реальный
QR НСПК (qr.nspk.ru), SBP — телефон (в терминале есть тестовый трейдер
«Test +7(999)999-99-99»), cancel работает; TO_ACCOUNT на момент теста без
свободных трейдеров (ошибка обработана штатно). Терминал поддерживает: SBP,
SBP_QR, TO_CARD, TO_ACCOUNT, CROSS_BORDER, MOBILE_TOP_UP, TIPS, TO_BANK_DETAILS,
VIET_QR, MANUAL_SBP_QR. Сервисы перезапущены — кнопки видны, эскалация активна.

### Сессия 08.07.2026 (Vertu)
Выполнено:
- fix: type_pay для Vertu — правильные коды `wt_sbp`/`wt_c2c` (по ответу поддержки
  Vertu), а не `sbp`/`c2c` из доков. Проверено на живом API: wt_sbp создаёт сделку
  (0084-…), старые коды и wt_c2c дают generic «Не удалось выдать сделку» (у wt_c2c
  это, вероятно, нет свободных карт-реквизитов — уточнить у поддержки). Сервисы
  перезапущены.
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
