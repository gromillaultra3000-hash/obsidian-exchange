import uuid
from lumi.app.schemas.provider_intelligence import ProviderOutputComparison

class ProviderOutputComparator:
    def _text(self, o): return str((o or {}).get('answer') or (o or {}).get('outputText') or '').strip().lower()
    def compare_outputs(self, provider_outputs):
        outputs=[o for o in provider_outputs if o]
        ids=[o.get('providerId','') for o in outputs]
        if not outputs: return ProviderOutputComparison(comparisonId=str(uuid.uuid4()), providerIds=[], agreementLevel='unknown', summary='No outputs to compare')
        texts=[self._text(o) for o in outputs if self._text(o)]
        statuses={str(o.get('status','unknown')) for o in outputs}
        risk_flags=[]
        for o in outputs: risk_flags.extend(o.get('riskFlags') or [])
        disagreements=[]
        if len(statuses)>1: disagreements.append('Provider statuses differ')
        if len(texts)<2: level='unknown'
        elif len(set(texts))==1: level='high'
        else:
            shared=0
            base=set(texts[0].split())
            for t in texts[1:]: shared=max(shared, len(base & set(t.split()))/max(1,len(base | set(t.split()))))
            level='medium' if shared>=0.45 else 'low'
        recommended=ids[0] if ids else None
        return ProviderOutputComparison(comparisonId=str(uuid.uuid4()), providerIds=ids, summary=f'Compared {len(outputs)} provider outputs', agreementLevel=level, commonClaims=[], disagreements=disagreements, riskFlags=sorted(set(risk_flags)), recommendedProviderId=recommended)
