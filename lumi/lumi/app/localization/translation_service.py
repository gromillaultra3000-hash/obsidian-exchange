from lumi.app.schemas.localization import TranslationLookupResult
from lumi.app.localization.dictionaries import DICTIONARIES
class TranslationService:
    def __init__(self, language_registry): self.language_registry=language_registry
    def translate(self, key: str, language: str|None=None, params: dict|None=None):
        language=language or 'ru'
        value=DICTIONARIES.get(language,{}).get(key)
        if value is None: value=DICTIONARIES.get('en',{}).get(key, key)
        for k,v in (params or {}).items(): value=value.replace('{'+str(k)+'}', str(v))
        return value
    def lookup(self, request):
        language=request.language or 'ru'; found=True; fallback=False
        value=DICTIONARIES.get(language,{}).get(request.key)
        if value is None:
            value=DICTIONARIES.get('en',{}).get(request.key)
            fallback=value is not None; found=value is not None
        if value is None: value=request.key
        for k,v in (request.params or {}).items(): value=value.replace('{'+str(k)+'}', str(v))
        return TranslationLookupResult(key=request.key, language=language, value=value, found=found, fallbackUsed=fallback)
    def get_dictionary(self, language: str): return DICTIONARIES.get(language, DICTIONARIES['en'])
