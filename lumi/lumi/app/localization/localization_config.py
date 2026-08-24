from lumi.app.schemas.localization import LocalizationConfig, SetLanguageResult
class LocalizationConfigService:
    def __init__(self): self._config=LocalizationConfig()
    def get_config(self): return self._config
    def set_language(self, language: str, profile_id: str='default'):
        if language not in ('ru','en'):
            return SetLanguageResult(language='ru', applied=False, message=f'Unsupported language: {language}', warnings=['Use ru or en'])
        self._config.activeLanguage=language
        return SetLanguageResult(language=language, applied=True, message=f'Language set to {language}')
    def get_active_language(self): return self._config.activeLanguage
    def get_fallback_language(self): return self._config.fallbackLanguage
    def reset_to_default(self): self._config.activeLanguage=self._config.defaultLanguage
