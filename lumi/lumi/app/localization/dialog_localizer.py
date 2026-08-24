class DialogLocalizer:
    def __init__(self, translation_service): self.translation_service=translation_service
    def get_command_patterns(self, language=None):
        lang=language or 'ru'
        ru=[('project_scan',['проверь проект','просканируй проект','проверь код','проанализируй проект']),('patch_preview',['подготовь патч','сделай патч','подготовь исправление','покажи патч']),('provider_setup',['подключи провайдера','подключи ии','проверь подключение','покажи провайдеры']),('storage_management',['хранилище','сохранить состояние','экспортировать состояние']),('security_management',['безопасность','секреты','разблокировать']),('create_sandbox',['создай песочницу','создай sandbox','песочница']),('sandbox_test',['запусти тесты в песочнице','проверь в песочнице']),('prepare_apply_package',['подготовь пакет применения','подготовь apply package']),('show_diff_preview',['покажи diff','покажи изменения']),('show_test_plan',['план тестов','как проверить']),('show_rollback_plan',['как откатить','план отката','откат'])]
        en=[('project_scan',['scan project','check project','analyze project']),('patch_preview',['prepare patch','patch preview','show patch']),('provider_setup',['connect provider','provider setup','test connection','show providers']),('storage_management',['storage','save state','export state']),('security_management',['security','secrets','unlock']),('create_sandbox',['create sandbox','sandbox workspace']),('sandbox_test',['run sandbox test','sandbox test','test in sandbox']),('prepare_apply_package',['prepare apply package','prepare apply']),('show_diff_preview',['show diff','show changes']),('show_test_plan',['test plan','how to test']),('show_rollback_plan',['rollback plan','how to rollback'])]
        src = ru if lang=='ru' else en
        return [{'commandType':c,'language':lang,'patterns':p,'examples':p[:2]} for c,p in src]
    def detect_language_from_text(self, text: str):
        ru=sum(1 for c in text if 'а' <= c.lower() <= 'я'); en=sum(1 for c in text if 'a' <= c.lower() <= 'z')
        return 'ru' if ru>en else 'en'
    def localize_dialog_response(self, response, language=None):
        lang=language or 'ru'
        if hasattr(response,'text') and response.text:
            if 'Project ID required' in response.text or 'Please provide a project ID' in response.text:
                response.text=self.translation_service.translate('dialog.project_id_required',lang)
            elif 'No host files' in response.text:
                response.text=self.translation_service.translate('dialog.no_host_writes',lang)
        if hasattr(response,'shortAnswer') and response.shortAnswer:
            if response.shortAnswer == 'Project ID required': response.shortAnswer=self.translation_service.translate('dialog.project_id_required',lang)
        return response
