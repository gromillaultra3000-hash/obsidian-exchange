RU_DICTIONARY = {
"app.title":"Lumi Dashboard","app.subtitle":"Панель управления","app.status.ready":"Готов","app.status.loading":"Загрузка...","app.status.error":"Ошибка",
"nav.overview":"Обзор","nav.dialog":"Диалог","nav.approvals":"Согласования","nav.history":"История","nav.integration":"Интеграция","nav.projects":"Проекты","nav.patches":"Патчи","nav.sandbox":"Песочница","nav.storage":"Хранилище","nav.security":"Безопасность","nav.providers":"Провайдеры","nav.settings":"Настройки","nav.api_status":"API Статус",
"safety.no_host_writes":"Без записи в host-проект","safety.no_real_apply":"Без реального применения","safety.approval_required":"Требуется согласование","safety.sandbox_only":"Только песочница","safety.secrets_redacted":"Секреты скрыты","safety.live_calls_disabled":"Внешние вызовы отключены","safety.vault_required":"Требуется Secret Vault","safety.locked":"Lumi заблокирован. Разблокируйте для продолжения.",
"action.refresh":"Обновить","action.create":"Создать","action.save":"Сохранить","action.load":"Загрузить","action.export":"Экспорт","action.import":"Импорт","action.unlock":"Разблокировать","action.lock":"Заблокировать","action.test_connection":"Проверить подключение","action.create_provider":"Создать провайдера","action.create_secret":"Создать секрет","action.run_scan":"Запустить сканирование","action.plan_patch":"Спланировать патч","action.create_sandbox":"Создать песочницу","action.prepare_apply_package":"Подготовить пакет применения",
"dialog.title":"Диалоговое окно","dialog.placeholder":"Введите сообщение...","dialog.create_session":"Создать сессию","dialog.send":"Отправить","dialog.project_id_required":"Нужен projectId. Укажите проект или сначала зарегистрируйте его.","dialog.response_ready":"Ответ готов","dialog.approval_required":"Требуется согласование","dialog.no_host_writes":"Файлы host-проекта не изменены.","dialog.patch_blocked":"План патча заблокирован: {reasons}",
"providers.title":"Провайдеры","providers.presets":"Предустановки","providers.create_from_preset":"Создать из предустановки","providers.secret_vault":"Secret Vault","providers.test_connection":"Проверить подключение","providers.live_call_warning":"Внешние вызовы отключены по умолчанию","providers.diagnostics":"Диагностика","providers.usage":"Использование",
"launcher.ready":"Готов","launcher.port_busy":"Порт занят","launcher.python_missing":"Python не найден","launcher.open_dashboard":"Открыть панель","launcher.port":"Порт","launcher.data_dir":"Директория данных","launcher.logs_dir":"Директория логов","launcher.ui_assets":"UI-ресурсы","launcher.diagnostics_failed":"Не удалось загрузить диагностику",
"first_run.title":"Первый запуск","first_run.step_security":"Настройте пароль безопасности","first_run.step_profile":"Создайте или выберите профиль","first_run.step_provider":"Подключите провайдера через Secret Vault","first_run.step_test":"Выполните metadata-only тест подключения",
"settings.language":"Язык","settings.current_language":"Текущий язык","settings.launcher":"Лаунчер","settings.launcher_diagnostics":"Диагностика лаунчера","settings.first_run":"Первый запуск","settings.about":"О программе","settings.about_text":"Lumi — встраиваемый модуль оркестрации провайдеров и runtime для host-приложений.","language.ru":"Русский","language.en":"English",
"status.ok":"OK","status.error":"Ошибка","status.warning":"Предупреждение","status.blocked":"Заблокировано","status.failed":"Не удалось","status.completed":"Завершено"}
EN_DICTIONARY = {
"app.title":"Lumi Dashboard","app.subtitle":"Control Panel","app.status.ready":"Ready","app.status.loading":"Loading...","app.status.error":"Error",
"nav.overview":"Overview","nav.dialog":"Dialog","nav.approvals":"Approvals","nav.history":"History","nav.integration":"Integration","nav.projects":"Projects","nav.patches":"Patches","nav.sandbox":"Sandbox","nav.storage":"Storage","nav.security":"Security","nav.providers":"Providers","nav.settings":"Settings","nav.api_status":"API Status",
"safety.no_host_writes":"No host writes","safety.no_real_apply":"No real patch apply","safety.approval_required":"Approval required","safety.sandbox_only":"Sandbox only","safety.secrets_redacted":"Secrets redacted","safety.live_calls_disabled":"Live calls disabled","safety.vault_required":"Secret Vault required","safety.locked":"Lumi is locked. Please unlock to continue.",
"action.refresh":"Refresh","action.create":"Create","action.save":"Save","action.load":"Load","action.export":"Export","action.import":"Import","action.unlock":"Unlock","action.lock":"Lock","action.test_connection":"Test Connection","action.create_provider":"Create Provider","action.create_secret":"Create Secret","action.run_scan":"Run Scan","action.plan_patch":"Plan Patch","action.create_sandbox":"Create Sandbox","action.prepare_apply_package":"Prepare Apply Package",
"dialog.title":"Dialog Window","dialog.placeholder":"Type your message...","dialog.create_session":"Create Session","dialog.send":"Send","dialog.project_id_required":"Project ID required. Provide a project or register one first.","dialog.response_ready":"Response ready","dialog.approval_required":"Approval required","dialog.no_host_writes":"No host files have been modified.","dialog.patch_blocked":"Patch plan blocked: {reasons}",
"providers.title":"Providers","providers.presets":"Presets","providers.create_from_preset":"Create from Preset","providers.secret_vault":"Secret Vault","providers.test_connection":"Test Connection","providers.live_call_warning":"Live calls disabled by default","providers.diagnostics":"Diagnostics","providers.usage":"Usage",
"launcher.ready":"Ready","launcher.port_busy":"Port busy","launcher.python_missing":"Python not found","launcher.open_dashboard":"Open Dashboard","launcher.port":"Port","launcher.data_dir":"Data directory","launcher.logs_dir":"Logs directory","launcher.ui_assets":"UI assets","launcher.diagnostics_failed":"Failed to load diagnostics",
"first_run.title":"First Run","first_run.step_security":"Set up security password","first_run.step_profile":"Create or select a profile","first_run.step_provider":"Connect a provider through Secret Vault","first_run.step_test":"Run metadata-only connection test",
"settings.language":"Language","settings.current_language":"Current language","settings.launcher":"Launcher","settings.launcher_diagnostics":"Launcher Diagnostics","settings.first_run":"First Run","settings.about":"About","settings.about_text":"Lumi is an embeddable provider orchestration module and runtime for host applications.","language.ru":"Русский","language.en":"English",
"status.ok":"OK","status.error":"Error","status.warning":"Warning","status.blocked":"Blocked","status.failed":"Failed","status.completed":"Completed"}
DICTIONARIES={"ru":RU_DICTIONARY,"en":EN_DICTIONARY}


RU_DICTIONARY.update({
    "nav.real_apply": "Применение",
    "real_apply.title": "Контролируемое применение",
    "real_apply.config": "Конфигурация",
    "real_apply.workspaces": "Рабочие области",
    "real_apply.gate_check": "Проверка gate",
    "real_apply.backup": "Резервная копия",
    "real_apply.execute": "Выполнить применение",
    "real_apply.rollback": "Откат",
    "real_apply.disable_warning": "Применение отключено по умолчанию",
    "real_apply.confirm_apply": "Я понимаю, что это изменит файлы в зарегистрированной рабочей области.",
    "real_apply.confirm_rollback": "Я понимаю, что откат восстановит файлы из резервной копии."
})
EN_DICTIONARY.update({
    "nav.real_apply": "Apply",
    "real_apply.title": "Controlled Apply",
    "real_apply.config": "Configuration",
    "real_apply.workspaces": "Workspaces",
    "real_apply.gate_check": "Gate Check",
    "real_apply.backup": "Backup",
    "real_apply.execute": "Execute Apply",
    "real_apply.rollback": "Rollback",
    "real_apply.disable_warning": "Apply is disabled by default",
    "real_apply.confirm_apply": "I understand this will modify files in the registered workspace.",
    "real_apply.confirm_rollback": "I understand rollback will restore files from backup."
})
DICTIONARIES = {"ru": RU_DICTIONARY, "en": EN_DICTIONARY}
