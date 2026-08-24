# Lumi v1.2.0 — Persistence, Profiles, Local Storage & Hardening

Implemented local SQLite persistence, runtime profiles, redacted export/import snapshots, storage health, retention dry-run, persistence API endpoints, integration events, and Storage UI panel.

Safety: no raw secrets are persisted or exported; storage failures degrade safely; host writes and real apply remain disabled.
