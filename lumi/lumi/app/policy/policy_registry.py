from typing import List
from lumi.app.schemas.policy import PolicyRule, LimitDefinition, PolicySummary
from lumi.app.policy.policy_defaults import get_default_policy_rules, get_default_limits


class PolicyRegistry:
    def __init__(self, audit_log=None):
        self._rules: dict[str, PolicyRule] = {}
        self._limits: dict[str, LimitDefinition] = {}
        self.audit_log = audit_log

    def load_defaults(self):
        for rule in get_default_policy_rules():
            if rule.ruleId not in self._rules:
                self._rules[rule.ruleId] = rule
        for limit in get_default_limits():
            if limit.limitId not in self._limits:
                self._limits[limit.limitId] = limit

    def list_rules(self) -> List[PolicyRule]:
        return sorted(self._rules.values(), key=lambda r: (-r.priority, r.ruleId))

    def get_rule(self, rule_id: str) -> PolicyRule | None:
        return self._rules.get(rule_id)

    def add_rule(self, rule: PolicyRule) -> PolicyRule:
        if rule.ruleId in self._rules:
            raise ValueError(f"Policy rule {rule.ruleId} already exists")
        self._rules[rule.ruleId] = rule
        if self.audit_log:
            self.audit_log.add_entry("policy_rule_registered", summary=f"Policy rule {rule.ruleId} registered", details={"rule": rule.model_dump()})
        return rule

    def update_rule(self, rule_id: str, patch: dict) -> PolicyRule:
        if rule_id not in self._rules:
            raise ValueError(f"Policy rule {rule_id} not found")
        data = self._rules[rule_id].model_dump()
        data.update(patch)
        self._rules[rule_id] = PolicyRule(**data)
        return self._rules[rule_id]

    def enable_rule(self, rule_id: str) -> PolicyRule:
        if rule_id not in self._rules:
            raise ValueError(f"Policy rule {rule_id} not found")
        self._rules[rule_id].enabled = True
        if self.audit_log:
            self.audit_log.add_entry("policy_rule_enabled", summary=f"Policy rule {rule_id} enabled")
        return self._rules[rule_id]

    def disable_rule(self, rule_id: str) -> PolicyRule:
        if rule_id not in self._rules:
            raise ValueError(f"Policy rule {rule_id} not found")
        self._rules[rule_id].enabled = False
        if self.audit_log:
            self.audit_log.add_entry("policy_rule_disabled", summary=f"Policy rule {rule_id} disabled")
        return self._rules[rule_id]

    def list_limits(self) -> List[LimitDefinition]:
        return sorted(self._limits.values(), key=lambda l: l.limitId)

    def get_limit(self, limit_id: str) -> LimitDefinition | None:
        return self._limits.get(limit_id)

    def add_limit(self, limit: LimitDefinition) -> LimitDefinition:
        if limit.limitId in self._limits:
            raise ValueError(f"Limit {limit.limitId} already exists")
        self._limits[limit.limitId] = limit
        return limit

    def update_limit(self, limit_id: str, patch: dict) -> LimitDefinition:
        if limit_id not in self._limits:
            raise ValueError(f"Limit {limit_id} not found")
        data = self._limits[limit_id].model_dump()
        data.update(patch)
        self._limits[limit_id] = LimitDefinition(**data)
        return self._limits[limit_id]

    def enable_limit(self, limit_id: str) -> LimitDefinition:
        if limit_id not in self._limits:
            raise ValueError(f"Limit {limit_id} not found")
        self._limits[limit_id].enabled = True
        return self._limits[limit_id]

    def disable_limit(self, limit_id: str) -> LimitDefinition:
        if limit_id not in self._limits:
            raise ValueError(f"Limit {limit_id} not found")
        self._limits[limit_id].enabled = False
        return self._limits[limit_id]

    def get_summary(self) -> PolicySummary:
        rules = self.list_rules()
        limits = self.list_limits()
        return PolicySummary(totalRules=len(rules), enabledRules=len([r for r in rules if r.enabled]), totalLimits=len(limits), enabledLimits=len([l for l in limits if l.enabled]), status="ok")

    def clear_for_tests(self):
        self._rules.clear()
        self._limits.clear()
        self.load_defaults()
