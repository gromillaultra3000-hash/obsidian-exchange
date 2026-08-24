import re
import uuid
from typing import List
from lumi.app.schemas.validation import ValidationIssue


class UnsafeWordingDetector:
    def __init__(self):
        self.forbidden_execution_patterns = [
            (re.compile(r"\bI\s+(have\s+)?executed\b", re.IGNORECASE), "FORBIDDEN_EXECUTION_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?deployed\s+to\s+production\b", re.IGNORECASE), "FORBIDDEN_DEPLOYMENT_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?sent\b", re.IGNORECASE), "FORBIDDEN_SEND_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?transferred\b", re.IGNORECASE), "FORBIDDEN_TRANSFER_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?purchased\b", re.IGNORECASE), "FORBIDDEN_PURCHASE_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?deleted\b", re.IGNORECASE), "FORBIDDEN_DELETE_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?modified\s+production\b", re.IGNORECASE), "FORBIDDEN_MODIFY_PRODUCTION_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?bypassed\s+approval\b", re.IGNORECASE), "FORBIDDEN_BYPASS_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?used\s+the\s+secret\b", re.IGNORECASE), "FORBIDDEN_SECRET_USAGE_CLAIM_ENGLISH"),
            (re.compile(r"\bI\s+(have\s+)?exposed\s+the\s+key\b", re.IGNORECASE), "FORBIDDEN_KEY_EXPOSURE_CLAIM_ENGLISH"),
            (re.compile(r"\bя\s+выполнил\b", re.IGNORECASE), "FORBIDDEN_EXECUTION_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+отправил\b", re.IGNORECASE), "FORBIDDEN_SEND_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+перев[её]л\b", re.IGNORECASE), "FORBIDDEN_TRANSFER_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+купил\b", re.IGNORECASE), "FORBIDDEN_PURCHASE_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+удалил\b", re.IGNORECASE), "FORBIDDEN_DELETE_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+изменил\s+production\b", re.IGNORECASE), "FORBIDDEN_MODIFY_PRODUCTION_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+задеплоил\b", re.IGNORECASE), "FORBIDDEN_DEPLOY_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+использовал\s+секрет\b", re.IGNORECASE), "FORBIDDEN_SECRET_USAGE_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+раскрыл\s+ключ\b", re.IGNORECASE), "FORBIDDEN_KEY_EXPOSURE_CLAIM_RUSSIAN"),
            (re.compile(r"\bя\s+обош[её]л\s+подтверждение\b", re.IGNORECASE), "FORBIDDEN_BYPASS_CLAIM_RUSSIAN"),
        ]
        self.secret_patterns = [
            (re.compile(r"(?i)(api[_\s-]?key|apikey)\s*[:=]\s*[^\s,;]+"), "SECRET_API_KEY"),
            (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]+"), "SECRET_BEARER_TOKEN"),
            (re.compile(r"(?i)(password|passwd)\s*[:=]\s*\S+"), "SECRET_PASSWORD"),
            (re.compile(r"(?i)(secret|token)\s*[:=]\s*[A-Za-z0-9_\-]+"), "SECRET_TOKEN"),
            (re.compile(r"sk-[A-Za-z0-9_\-]{6,}", re.IGNORECASE), "SECRET_OPENAI_LIKE_KEY"),
        ]
        self.permissive_context_patterns = [
            re.compile(r"\b(recommend|suggest|propose|should|could|would|might|consider)\b.{0,80}\b(deploy|delete|send|transfer|execute|purchase|modify)\b", re.IGNORECASE),
            re.compile(r"\b(я\s+(рекомендую|предлагаю|советую)|стоит|следует|можно|нужно|необходимо)\b.{0,80}\b(задеплоить|удалить|отправить|выполнить|изменить)\b", re.IGNORECASE),
        ]

    def detect_unsafe_wording(self, text: str) -> List[ValidationIssue]:
        return self.detect_forbidden_execution_claim(text) + self.detect_secret_like_content(text)

    def detect_forbidden_execution_claim(self, text: str) -> List[ValidationIssue]:
        if not text:
            return []
        if any(pattern.search(text) for pattern in self.permissive_context_patterns):
            return []
        issues = []
        for pattern, code in self.forbidden_execution_patterns:
            if pattern.search(text):
                issues.append(ValidationIssue(
                    issueId=str(uuid.uuid4()),
                    code=code,
                    severity="critical",
                    message=f"Forbidden execution claim detected: {code}",
                    field="answer",
                    recoverable=False,
                    details={"pattern": code},
                ))
                break
        return issues

    def detect_secret_like_content(self, text: str) -> List[ValidationIssue]:
        if not text:
            return []
        issues = []
        for pattern, code in self.secret_patterns:
            if pattern.search(text):
                issues.append(ValidationIssue(
                    issueId=str(uuid.uuid4()),
                    code="SECRET_LIKE_CONTENT",
                    severity="critical",
                    message=f"Secret-like content detected in answer: {code}",
                    field="answer",
                    recoverable=False,
                    details={"pattern": code},
                ))
                break
        return issues
