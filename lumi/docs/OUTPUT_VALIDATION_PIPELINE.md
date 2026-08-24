# Output Validation Pipeline

Lumi v0.3 normalizes every provider output before it can influence a final StructuredDecision.

Flow:

1. Raw output is accepted as `ProviderOutput`, `dict`, plain string, or `None`.
2. `OutputNormalizer` converts it into a normalized `ProviderOutput`.
3. `OutputValidator` applies deterministic validation rules.
4. `ValidationPipeline` marks each output as `valid`, `degraded`, or `rejected`.
5. `/resolve` uses only valid/degraded accepted outputs. Rejected outputs cannot approve anything.

Rejected outputs include fake success, forbidden execution claims, and secret-like content.
