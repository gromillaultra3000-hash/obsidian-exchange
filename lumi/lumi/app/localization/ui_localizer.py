class UiLocalizer:
    def __init__(self, translation_service): self.translation_service=translation_service
    def build_localized_ui_state(self, runtime):
        language = runtime.get_active_language() if hasattr(runtime,'get_active_language') else 'ru'
        langs = runtime.list_languages() if hasattr(runtime,'list_languages') else []
        labels={k.replace('.','_'): self.translation_service.translate(k, language) for k in [
            'app.title','nav.overview','nav.dialog','nav.approvals','nav.history','nav.integration','nav.projects','nav.patches','nav.sandbox','nav.storage','nav.security','nav.providers','nav.settings']}
        safety=[{'labelId':'no_host_writes','title':self.translation_service.translate('safety.no_host_writes',language),'level':'critical'}, {'labelId':'no_real_apply','title':self.translation_service.translate('safety.no_real_apply',language),'level':'critical'}, {'labelId':'approval_required','title':self.translation_service.translate('safety.approval_required',language),'level':'warning'}, {'labelId':'sandbox_only','title':self.translation_service.translate('safety.sandbox_only',language),'level':'warning'}, {'labelId':'secrets_redacted','title':self.translation_service.translate('safety.secrets_redacted',language),'level':'critical'}]
        return {'language': language, 'availableLanguages':[l.model_dump() if hasattr(l,'model_dump') else l for l in langs], 'labels':labels, 'safetyLabels':safety, 'panels':[]}
