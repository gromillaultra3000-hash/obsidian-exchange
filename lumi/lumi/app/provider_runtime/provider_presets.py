from lumi.app.schemas.provider_runtime import ProviderPreset
CONSOLE_URLS=['console.groq.com','platform.deepseek.com','aistudio.google.com','cloud.cerebras.ai','dashboard.openrouter.ai','platform.openai.com/api-keys','console.anthropic.com']
class ProviderPresetRegistry:
    def __init__(self):
        self._presets={
        'openai':ProviderPreset(presetId='openai',displayName='OpenAI',defaultBaseUrl='https://api.openai.com/v1',defaultModel='gpt-4o-mini',supportsModelDiscovery=True),
        'openrouter':ProviderPreset(presetId='openrouter',displayName='OpenRouter',defaultBaseUrl='https://openrouter.ai/api/v1'),
        'groq':ProviderPreset(presetId='groq',displayName='Groq',defaultBaseUrl='https://api.groq.com/openai/v1'),
        'deepseek':ProviderPreset(presetId='deepseek',displayName='DeepSeek',defaultBaseUrl='https://api.deepseek.com/v1'),
        'gemini_openai_compatible':ProviderPreset(presetId='gemini_openai_compatible',displayName='Gemini OpenAI Compatible',defaultBaseUrl='https://generativelanguage.googleapis.com/v1beta/openai'),
        'together':ProviderPreset(presetId='together',displayName='Together AI',defaultBaseUrl='https://api.together.xyz/v1'),
        'mistral':ProviderPreset(presetId='mistral',displayName='Mistral AI',defaultBaseUrl='https://api.mistral.ai/v1'),
        'cerebras':ProviderPreset(presetId='cerebras',displayName='Cerebras',defaultBaseUrl='https://api.cerebras.ai/v1'),
        'custom_openai_compatible':ProviderPreset(presetId='custom_openai_compatible',displayName='Custom OpenAI Compatible',defaultBaseUrl=''),
        'local_mock':ProviderPreset(presetId='local_mock',displayName='Local Mock',runtimeType='mock',defaultBaseUrl='local',authType='none')}
    def list_presets(self): return list(self._presets.values())
    def get_preset(self,preset_id): return self._presets.get(preset_id)
    def block_console_url(self,url): return any(c in (url or '').lower() for c in CONSOLE_URLS)
    def get_suggested_api_url(self,preset_id):
        p=self.get_preset(preset_id); return p.defaultBaseUrl if p else None
