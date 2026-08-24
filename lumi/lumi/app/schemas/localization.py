from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

LanguageCode = Literal["ru", "en"]
LanguageStatus = Literal["active", "fallback", "missing", "disabled"]

class LanguageProfile(BaseModel):
    languageCode: LanguageCode
    displayName: str
    nativeName: str
    status: LanguageStatus = "active"
    isDefault: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LocalizationConfig(BaseModel):
    defaultLanguage: LanguageCode = "ru"
    activeLanguage: LanguageCode = "ru"
    fallbackLanguage: LanguageCode = "en"
    persistLanguagePreference: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TranslationLookupRequest(BaseModel):
    key: str
    language: Optional[LanguageCode] = None
    params: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TranslationLookupResult(BaseModel):
    key: str
    language: LanguageCode = "ru"
    value: str = ""
    found: bool = False
    fallbackUsed: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SetLanguageRequest(BaseModel):
    language: LanguageCode
    profileId: Optional[str] = "default"
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SetLanguageResult(BaseModel):
    language: LanguageCode
    applied: bool = False
    message: str = ""
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LocalizedDialogCommand(BaseModel):
    commandType: str
    language: LanguageCode
    patterns: List[str] = Field(default_factory=list)
    examples: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
