import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.localization import SetLanguageRequest, TranslationLookupRequest
from lumi.app.schemas.errors import ErrorEnvelope
router=APIRouter(prefix='/localization', tags=['localization'])

def _err(code,msg): return ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=msg, recoverable=True, details={}, redacted=True).model_dump()
@router.get('/languages')
async def list_languages(): return runtime_instance.list_languages()
@router.get('/config')
async def localization_config(): return runtime_instance.get_localization_config()
@router.post('/language')
async def set_language(request: SetLanguageRequest):
    result=runtime_instance.set_language(request)
    if not result.applied: raise HTTPException(status_code=400, detail=_err('LANGUAGE_ERROR', result.message))
    return result
@router.post('/translate')
async def translate(request: TranslationLookupRequest): return runtime_instance.translate(request)
@router.get('/dictionary/{language}')
async def get_dictionary(language: str):
    if language not in ('ru','en'): raise HTTPException(status_code=400, detail=_err('UNSUPPORTED_LANGUAGE', f'Language {language} not supported. Use ru or en.'))
    return runtime_instance.get_dictionary(language)
@router.get('/ui-state')
async def localized_ui_state(): return runtime_instance.get_localized_ui_state()
