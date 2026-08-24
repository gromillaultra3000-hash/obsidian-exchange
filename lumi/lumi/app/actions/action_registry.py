from typing import List
from lumi.app.schemas.actions import ActionDefinition
from lumi.app.providers.redaction import RedactionUtil


class ActionRegistry:
    def __init__(self, audit_log=None, redaction: RedactionUtil | None = None):
        self._actions: dict[str, ActionDefinition] = {}
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()

    def register_action(self, action_def: ActionDefinition) -> ActionDefinition:
        if action_def.actionId in self._actions:
            raise ValueError(f"Action {action_def.actionId} already registered")
        self._actions[action_def.actionId] = action_def
        if self.audit_log:
            self.audit_log.add_entry("action_registered", summary=f"Action {action_def.actionId} registered", details={"action": self.redaction.redact_model(action_def)})
        return action_def

    def get_action(self, action_id: str) -> ActionDefinition | None:
        return self._actions.get(action_id)

    def list_actions(self) -> List[ActionDefinition]:
        return list(self._actions.values())

    def enable_action(self, action_id: str) -> ActionDefinition:
        if action_id not in self._actions:
            raise ValueError(f"Action {action_id} not found")
        self._actions[action_id].enabled = True
        if self.audit_log:
            self.audit_log.add_entry("action_enabled", summary=f"Action {action_id} enabled")
        return self._actions[action_id]

    def disable_action(self, action_id: str) -> ActionDefinition:
        if action_id not in self._actions:
            raise ValueError(f"Action {action_id} not found")
        self._actions[action_id].enabled = False
        if self.audit_log:
            self.audit_log.add_entry("action_disabled", summary=f"Action {action_id} disabled")
        return self._actions[action_id]

    def action_exists(self, action_id: str) -> bool:
        return action_id in self._actions

    def clear_for_tests(self):
        self._actions.clear()
