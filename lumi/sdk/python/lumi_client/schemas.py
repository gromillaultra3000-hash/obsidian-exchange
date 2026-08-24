"""Lightweight SDK schema helpers for Lumi v0.7."""

def host_manifest(host_app_id: str, display_name: str, app_type: str = "desktop") -> dict:
    return {
        "hostAppId": host_app_id,
        "displayName": display_name,
        "appType": app_type,
        "allowedModes": ["rest"],
        "capabilitiesRequested": ["resolve", "dialog_sessions"],
        "actionsAllowed": [],
        "eventsSupported": ["user_message"],
        "callbacks": {"mode": "mock"},
        "metadata": {},
    }
