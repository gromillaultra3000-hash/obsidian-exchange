# Lumi Security

Lumi v1.3 adds local password setup, unlock sessions, protected API mode, Secret Vault and encryption-at-rest foundation. Compatibility mode remains the default for local development and older tests.

Secrets are stored as vault references and API responses return masked values only. Raw secrets are not included in normal runtime exports.
