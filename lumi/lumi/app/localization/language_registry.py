from lumi.app.schemas.localization import LanguageProfile
class LanguageRegistry:
    def __init__(self):
        self._languages={"ru":LanguageProfile(languageCode="ru",displayName="Russian",nativeName="Русский",isDefault=True),"en":LanguageProfile(languageCode="en",displayName="English",nativeName="English",isDefault=False)}
    def list_languages(self): return list(self._languages.values())
    def get_language(self, language_code: str): return self._languages.get(language_code)
    def is_supported(self, language_code: str): return language_code in self._languages
